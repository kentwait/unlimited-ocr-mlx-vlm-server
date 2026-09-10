"""Assistant runtime: local chat model lifecycle and OpenAI-subset streaming.

The assistant is optional: when the ``mlx-vlm`` extra is not installed the
endpoint reports ``available: false`` and returns 501. CI and contract checks
use `FakeAssistantRuntime`, selected by ``OCR_ASSISTANT_FAKE=1``.

Models are a data-driven catalog of pinned Qwen3.5-9B MLX quantizations. Each
entry tracks its own download state; the runtime loads at most one for
generation. Lifecycle: ``not_downloaded -> downloading -> loading -> ready``
with ``paused`` for a cancelled (resumable) download and ``failed`` for
download/load errors. Downloads are cancellable through a ``tqdm_class`` that
raises on a cancel event, leaving partial files in the Hugging Face cache so a
later download resumes. Generation is serialized through a lock; each
streaming request runs in a worker thread and stops early when the client
disconnects.
"""

from __future__ import annotations

import asyncio
import gc
import importlib.util
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from .assistant_parser import (
    QwenStreamFilter,
    parse_tool_calls,
    to_chat_messages,
)

log = logging.getLogger("ocr_server.assistant")


@dataclass(frozen=True)
class ModelSpec:
    """One pinned model in the catalog: a Hugging Face ref and a short label."""

    id: str
    label: str
    bits: int


#: Catalog of pinned Qwen3.5-9B MLX quantizations from the same upstream
#: family. Data-driven: an int6 entry is added when/if the family publishes
#: one (``mlx-community/Qwen3.5-9B-MLX-6bit`` does not exist today; the
#: ``Qwen3.5-9B-6bit`` repo is a different base family and is excluded).
MODEL_CATALOG: tuple[ModelSpec, ...] = (
    ModelSpec("mlx-community/Qwen3.5-9B-MLX-8bit", "int8", 8),
    ModelSpec("mlx-community/Qwen3.5-9B-MLX-4bit", "int4", 4),
)
DEFAULT_MODEL = MODEL_CATALOG[0].id
DEFAULT_MAX_TOKENS = 1024
#: Qwen3.5's evaluated best-practice sampling (model card). Without the
#: presence penalty the small models loop on repeated parameter values.
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 0.95
DEFAULT_TOP_K = 20
DEFAULT_PRESENCE_PENALTY = 1.5

STATE_NOT_DOWNLOADED = "not_downloaded"
STATE_DOWNLOADING = "downloading"
STATE_PAUSED = "paused"
STATE_LOADING = "loading"
STATE_READY = "ready"
STATE_FAILED = "failed"


class AssistantUnavailable(RuntimeError):
    """The optional assistant extra is not installed in this server build."""


class ModelNotReady(RuntimeError):
    """The model is missing or failed to load; the client should download."""


class AssistantBusy(RuntimeError):
    """A different model lifecycle operation is already running."""


class DownloadCancelled(Exception):
    """Raised inside a cancellable tqdm when the user cancels a download."""


def _now() -> int:
    return int(time.time())


def _dir_size(root: Path) -> int:
    """Total bytes of files under a directory (missing dirs are zero)."""
    total = 0
    for base, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                continue
    return total


def cancellable_tqdm(cancel: threading.Event) -> type:
    """Build a tqdm subclass that raises ``DownloadCancelled`` when set.

    ``huggingface_hub.snapshot_download`` accepts ``tqdm_class`` and
    instantiates it per file, so raising from ``update`` aborts the transfer
    and leaves partial files that a subsequent download resumes.
    """

    from tqdm.auto import tqdm as _base

    class CancellableTqdm(_base):  # type: ignore[misc]
        def update(self, n: float | None = 1) -> bool | None:
            if cancel.is_set():
                raise DownloadCancelled()
            return super().update(n)

        def __iter__(self) -> Iterator[Any]:
            for item in super().__iter__():
                if cancel.is_set():
                    raise DownloadCancelled()
                yield item

    return CancellableTqdm


def sampling_kwargs(request: dict[str, Any]) -> dict[str, Any]:
    """Generation options with Qwen3.5 best-practice defaults applied."""
    kwargs: dict[str, Any] = {
        "max_tokens": _coerce_int(
            request.get("max_tokens"), DEFAULT_MAX_TOKENS
        ),
        "temperature": _coerce_float(
            request.get("temperature"), DEFAULT_TEMPERATURE
        ),
        "top_p": _coerce_float(request.get("top_p"), DEFAULT_TOP_P),
        "top_k": _coerce_int(request.get("top_k"), DEFAULT_TOP_K),
        "presence_penalty": _coerce_float(
            request.get("presence_penalty"), DEFAULT_PRESENCE_PENALTY
        ),
    }
    if request.get("repetition_penalty") is not None:
        kwargs["repetition_penalty"] = _coerce_float(
            request.get("repetition_penalty"), 1.0
        )
    return kwargs


def _coerce_float(value: Any, fallback: float) -> float:
    """Sampling options arrive as JSON; nulls and junk fall back to defaults."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _chunk(
    completion_id: str,
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": _now(),
        "model": model,
        "choices": [
            {"index": 0, "delta": delta, "finish_reason": finish_reason}
        ],
    }


class AssistantRuntime:
    """mlx-vlm-backed catalog; loaded lazily and guarded by locks."""

    #: Class default so ``_is_downloaded`` is safe before ``__init__`` runs.
    _sizes: dict[str, int]

    def __init__(self, model_ref: str | None = None) -> None:
        self.model_ref = model_ref or os.environ.get(
            "OCR_ASSISTANT_MODEL", DEFAULT_MODEL
        )
        self.available = importlib.util.find_spec("mlx_vlm") is not None
        self.loaded = False
        self.progress: float | None = None
        self.detail: str | None = None
        self.state = STATE_NOT_DOWNLOADED
        self._sizes = {}
        self._model: Any = None
        self._processor: Any = None
        self._infer_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._cancel = threading.Event()
        self._download_target: str | None = None
        if not self.available:
            self.state = STATE_FAILED
            self.detail = (
                "assistant model runtime not installed in this server build "
                "(install the 'assistant' extra)"
            )
        elif self._is_downloaded(self.model_ref):
            self.state = STATE_READY
        self._thread: threading.Thread | None = None

    # -- catalog -----------------------------------------------------------

    def _catalog(self) -> list[ModelSpec]:
        specs = list(MODEL_CATALOG)
        if self.model_ref not in {spec.id for spec in specs}:
            specs.insert(
                0,
                ModelSpec(self.model_ref, self.model_ref.split("/")[-1], 0),
            )
        return specs

    def _size_bytes(self, ref: str) -> int | None:
        """Aggregate Hub file size for a model, cached; None when unknown."""
        if not self.available:
            return None
        if ref in self._sizes:
            return self._sizes[ref]
        try:
            from huggingface_hub import HfApi

            info = HfApi().model_info(ref, files_metadata=True)
            total = sum(
                int(sibling.size or 0) for sibling in info.siblings or []
            )
        except Exception:
            return None
        self._sizes[ref] = total
        return total or None

    def _models_status(self) -> list[dict[str, Any]]:
        active = (
            self.model_ref
            if self.loaded or self.state in (STATE_READY, STATE_LOADING)
            else None
        )
        return [
            {
                "id": spec.id,
                "label": spec.label,
                "bits": spec.bits,
                "size_bytes": self._size_bytes(spec.id),
                "downloaded": self._is_downloaded(spec.id),
                "active": spec.id == active,
            }
            for spec in self._catalog()
        ]

    def models(self) -> list[dict[str, Any]]:
        """Catalog with per-entry downloaded/active state."""
        return self._models_status()

    # -- lifecycle ---------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "state": self.state,
            "model": self.model_ref,
            "loaded": self.loaded,
            "progress": self.progress,
            "detail": self.detail,
            "download_target": (
                self._download_target
                if self.state in (STATE_DOWNLOADING, STATE_PAUSED)
                else None
            ),
            "models": self._models_status(),
        }

    def _is_downloaded(self, ref: str) -> bool:
        try:
            from huggingface_hub import snapshot_download
            from huggingface_hub import try_to_load_from_cache
        except ImportError:  # pragma: no cover - extra missing
            return False
        try:
            snapshot_download(ref, local_files_only=True)
            return True
        except Exception:
            # Newer hubs raise IncompleteSnapshotError for caches written by
            # other tools (missing metadata files) even when the weights are
            # present — and that error subclasses LocalEntryNotFoundError; a
            # cached config is the practical signal, since loading can
            # complete the snapshot when the network is available.
            pass
        try:
            cached = try_to_load_from_cache(ref, "config.json")
            return isinstance(cached, str)
        except Exception:  # pragma: no cover - defensive
            return False

    def start_download(self, model: str | None = None) -> None:
        """Kick off download+load of an entry in the background (idempotent)."""
        if not self.available:
            raise AssistantUnavailable(self.detail or "assistant unavailable")
        target = model or self.model_ref
        with self._lifecycle_lock:
            if self.state in (STATE_DOWNLOADING, STATE_LOADING):
                if self._download_target == target:
                    return
                raise AssistantBusy(
                    f"a model operation is already running ({self._download_target})"
                )
            if (
                self.state == STATE_READY
                and self.loaded
                and target == self.model_ref
            ):
                return
            self._cancel.clear()
            self._download_target = target
            self.state = STATE_DOWNLOADING
            self.progress = 0.0
            self.detail = None
            self._thread = threading.Thread(
                target=self._download_and_load, args=(target,), daemon=True
            )
            self._thread.start()

    def _set_progress(self, value: float) -> None:
        self.progress = max(0.0, min(1.0, value))

    def _should_auto_load(self, target: str) -> bool:
        """True only when this download would leave the app with no model.

        A download must never hijack an already-present model: if any other
        catalog entry is downloaded (or one is resident) the newly downloaded
        entry stays inactive until the user explicitly selects it.
        """
        if self.loaded:
            return False
        return not any(
            spec.id != target and self._is_downloaded(spec.id)
            for spec in self._catalog()
        )

    def _download_and_load(self, target: str) -> None:  # pragma: no cover - weights
        try:
            self._download_sync(target)
            if self._cancel.is_set():
                self.state = STATE_PAUSED
                self.detail = "download cancelled"
                return
            if self._should_auto_load(target):
                self.state = STATE_LOADING
                self._load_sync(target)
                self.model_ref = target
                self.loaded = True
            self.progress = 1.0
            self.detail = None
            self._download_target = None
            self.state = (
                STATE_READY
                if self.loaded or self._is_downloaded(self.model_ref)
                else STATE_NOT_DOWNLOADED
            )
        except DownloadCancelled:
            self.state = STATE_PAUSED
            self.detail = "download cancelled"
        except Exception as exc:  # pragma: no cover - surfaced via status
            if self._cancel.is_set():
                self.state = STATE_PAUSED
                self.detail = "download cancelled"
                return
            log.exception("assistant model setup failed")
            self.state = STATE_FAILED
            self.detail = str(exc)

    def _download_sync(self, target: str) -> None:  # pragma: no cover - network
        from huggingface_hub import HfApi, snapshot_download

        total = 0
        cache_dir = self._cache_dir(target)
        try:
            info = HfApi().model_info(target, files_metadata=True)
            total = sum(
                int(sibling.size or 0) for sibling in info.siblings or []
            )
            if total:
                self._sizes[target] = total
        except Exception:
            total = 0
        stop: threading.Event | None = None
        if total > 0 and cache_dir is not None:
            stop = self._start_progress_poll(cache_dir, total)
        try:
            snapshot_download(
                target, tqdm_class=cancellable_tqdm(self._cancel)
            )
        finally:
            if stop is not None:
                stop.set()

    def cancel_download(self) -> None:
        """Abort an in-flight download, leaving a resumable paused entry."""
        with self._lifecycle_lock:
            if self.state != STATE_DOWNLOADING:
                return
            self._cancel.set()
            self.state = STATE_PAUSED
            self.detail = "download cancelled"

    def use(self, model: str) -> None:
        """Switch the resident model: unload the current weights, load this."""
        if not self.available:
            raise AssistantUnavailable(self.detail or "assistant unavailable")
        if model == self.model_ref and self.loaded:
            return
        if not self._is_downloaded(model):
            raise ModelNotReady(f"assistant model {model} is not downloaded")
        with self._infer_lock:
            self.state = STATE_LOADING
            self.detail = None
            try:
                self._unload()
                self._load_sync(model)
            except Exception as exc:  # pragma: no cover - load failure path
                self.state = STATE_FAILED
                self.detail = str(exc)
                raise ModelNotReady(str(exc)) from exc
            self.model_ref = model
            self.loaded = True
            self.progress = 1.0
            self.state = STATE_READY

    def _cache_dir(self, ref: str) -> Path | None:
        """Local Hugging Face cache directory for a model ref."""
        try:
            from huggingface_hub.constants import HF_HUB_CACHE
        except ImportError:  # pragma: no cover - extra missing
            return None
        org, _, name = ref.partition("/")
        if not name:
            return None
        return Path(HF_HUB_CACHE) / f"models--{org}--{name}"

    def _start_progress_poll(
        self, cache_dir: Path, total: int
    ) -> threading.Event:  # pragma: no cover - poll loop
        """Report download progress from cache growth (hub tqdm is opaque)."""
        stop = threading.Event()

        def poll() -> None:
            while not stop.wait(0.5):
                if self.state != STATE_DOWNLOADING:
                    return
                size = _dir_size(cache_dir)
                if size > 0:
                    self._set_progress(min(0.95, size / total))

        threading.Thread(target=poll, daemon=True).start()
        return stop

    def _load_sync(self, ref: str) -> None:  # pragma: no cover - loads MLX
        from mlx_vlm import load

        self._model, self._processor = load(ref)
        self.loaded = True

    def _unload(self) -> None:  # pragma: no cover - frees MLX weights
        self._model = None
        self._processor = None
        self.loaded = False
        gc.collect()
        try:
            import mlx.core as mx

            if hasattr(mx, "clear_cache"):
                mx.clear_cache()
            elif hasattr(mx, "metal"):
                mx.metal.clear_cache()
        except Exception:
            pass

    def ensure_loaded(self) -> None:
        """Load on first use; raises ModelNotReady when the weights are absent."""
        if self.loaded:
            return
        if not self.available:
            raise AssistantUnavailable(self.detail or "assistant unavailable")
        if self.state in (STATE_FAILED, STATE_PAUSED):
            raise ModelNotReady(self.detail or "assistant model failed to load")
        if not self._is_downloaded(self.model_ref):
            self.state = STATE_NOT_DOWNLOADED
            raise ModelNotReady("assistant model is not downloaded")
        with self._lifecycle_lock:
            if self.loaded:
                return
            self.state = STATE_LOADING
            try:
                self._load_sync(self.model_ref)
            except Exception as exc:  # pragma: no cover - load failure path
                self.state = STATE_FAILED
                self.detail = str(exc)
                raise ModelNotReady(str(exc)) from exc
            self.state = STATE_READY

    # -- generation --------------------------------------------------------

    def _iter_chunks(
        self, request: dict[str, Any], stop: threading.Event
    ) -> Iterator[dict[str, Any]]:  # pragma: no cover - requires MLX weights
        messages = to_chat_messages(request.get("messages", []))
        tools = request.get("tools") or None
        tokenizer = self._processor.tokenizer
        prompt = tokenizer.apply_chat_template(
            messages,
            tools=tools,
            add_generation_prompt=True,
            enable_thinking=False,
            tokenize=False,
        )
        from mlx_vlm.generate.dispatch import stream_generate

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        model = str(request.get("model") or self.model_ref)
        options = sampling_kwargs(request)
        flt = QwenStreamFilter()
        token_ids: list[int] = []
        saw_text = False
        for response in stream_generate(
            self._model,
            self._processor,
            prompt,
            image=None,
            **options,
        ):
            if stop.is_set():
                break
            if getattr(response, "is_draft", False):
                continue
            token = getattr(response, "token", None)
            if token is not None:
                token_ids.append(int(token))
            # mlx-vlm yields empty-text results while the detokenizer buffers
            # a token; decoding those here would duplicate the text when the
            # buffer later flushes. Only `.text` deltas are authoritative.
            text = getattr(response, "text", None) or ""
            if not text:
                continue
            saw_text = True
            emitted = flt.feed(text)
            if emitted:
                yield _chunk(completion_id, model, {"content": emitted})
        if not saw_text and token_ids:
            # Degenerate tokenizers that never emit text: decode once.
            decoded = tokenizer.decode(token_ids, skip_special_tokens=True)
            emitted = flt.feed(decoded)
            if emitted:
                yield _chunk(completion_id, model, {"content": emitted})
        tail, blocks = flt.finish()
        if tail and not stop.is_set():
            yield _chunk(completion_id, model, {"content": tail})
        calls = parse_tool_calls(blocks)
        if calls and not stop.is_set():
            deltas = [
                {
                    "index": index,
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["function"]["name"],
                        "arguments": call["function"]["arguments"],
                    },
                }
                for index, call in enumerate(calls)
            ]
            yield _chunk(completion_id, model, {"tool_calls": deltas})
            yield _chunk(completion_id, model, {}, "tool_calls")
            return
        if not stop.is_set():
            yield _chunk(completion_id, model, {}, "stop")

    def _raw_stream(
        self, request: dict[str, Any], stop: threading.Event
    ) -> Iterator[dict[str, Any]]:
        with self._infer_lock:
            self.ensure_loaded()
            yield from self._iter_chunks(request, stop)

    async def stream(
        self, request: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Async chunk stream; cancels generation when the consumer stops."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue()
        stop = threading.Event()

        def produce() -> None:
            try:
                for chunk in self._raw_stream(request, stop):
                    if stop.is_set():
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except Exception as exc:  # noqa: BLE001 - forwarded to consumer
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        thread = threading.Thread(target=produce, daemon=True)
        thread.start()
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            stop.set()

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        """Non-streaming completion aggregated from the chunk stream."""
        stop = threading.Event()
        content_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        finish_reason = "stop"
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        for chunk in self._raw_stream(request, stop):
            choice = chunk["choices"][0]
            delta = choice["delta"]
            if isinstance(delta.get("content"), str):
                content_parts.append(delta["content"])
            if isinstance(delta.get("tool_calls"), list):
                tool_calls = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": dict(call["function"]),
                    }
                    for call in delta["tool_calls"]
                ]
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content_parts),
        }
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": _now(),
            "model": str(request.get("model") or self.model_ref),
            "choices": [
                {"index": 0, "message": message, "finish_reason": finish_reason}
            ],
        }


class FakeAssistantRuntime(AssistantRuntime):
    """Deterministic runtime for CI, contract checks, and UI development.

    Turn one (no tool result yet) requests the first available tool. Turn two
    answers from the tool result and cites page 1, exercising streaming,
    tool calls, and citation parsing without weights. The catalog starts with
    only the default entry downloaded; download/cancel/use mutate it
    synchronously so the model-management surface is contract-testable.
    """

    _fake_downloaded: set[str] = set()

    def __init__(self, model_ref: str | None = None) -> None:
        super().__init__(model_ref)
        self.available = True
        self.loaded = True
        self.state = STATE_READY
        self.progress = 1.0
        self.detail = None
        self._fake_downloaded = {DEFAULT_MODEL, self.model_ref}

    def _is_downloaded(self, ref: str) -> bool:  # pragma: no cover - trivial
        return ref in self._fake_downloaded

    def _size_bytes(self, ref: str) -> int | None:  # pragma: no cover - trivial
        return {
            "mlx-community/Qwen3.5-9B-MLX-8bit": 10_400_000_000,
            "mlx-community/Qwen3.5-9B-MLX-4bit": 5_500_000_000,
        }.get(ref)

    def start_download(self, model: str | None = None) -> None:
        target = model or self.model_ref
        self._download_target = target
        self._fake_downloaded.add(target)
        # Mirror the real runtime: only adopt the newly downloaded entry when
        # no other model is present; never hijack an existing one.
        if not self.loaded and not any(
            ref != target for ref in self._fake_downloaded
        ):
            self.model_ref = target
            self.loaded = True
        self.state = STATE_READY
        self.progress = 1.0
        self.detail = None

    def cancel_download(self) -> None:
        self.state = STATE_PAUSED
        self.detail = "download cancelled"
        self._download_target = self._download_target or self.model_ref

    def use(self, model: str) -> None:
        if model not in self._fake_downloaded:
            raise ModelNotReady(f"assistant model {model} is not downloaded")
        self.model_ref = model
        self._download_target = None
        self.loaded = True
        self.state = STATE_READY
        self.progress = 1.0
        self.detail = None

    def _load_sync(self, ref: str) -> None:  # pragma: no cover - trivial
        self.loaded = True

    def ensure_loaded(self) -> None:
        return

    def _iter_chunks(
        self, request: dict[str, Any], stop: threading.Event
    ) -> Iterator[dict[str, Any]]:
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        model = str(request.get("model") or self.model_ref)
        messages = request.get("messages", [])
        tools = request.get("tools") or []
        tool_messages = [
            message for message in messages if message.get("role") == "tool"
        ]
        if tools and not tool_messages:
            name = str(tools[0].get("function", {}).get("name", "search"))
            last_user = ""
            for message in reversed(messages):
                if message.get("role") == "user":
                    content = message.get("content")
                    last_user = content if isinstance(content, str) else ""
                    break
            call = {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(
                        {"query": last_user[-80:] or "paper"}, ensure_ascii=False
                    ),
                },
            }
            yield _chunk(completion_id, model, {"content": "Consulting the paper…"})
            if stop.is_set():
                return
            yield _chunk(completion_id, model, {"tool_calls": [call]})
            yield _chunk(completion_id, model, {}, "tool_calls")
            return
        evidence = ""
        if tool_messages:
            content = tool_messages[-1].get("content")
            evidence = content if isinstance(content, str) else ""
        answer = (
            "The paper reports this in its results [p.1]. "
            f"Evidence: {evidence[:160].strip() or 'none found'}."
        )
        for word in answer.split(" "):
            if stop.is_set():
                return
            yield _chunk(completion_id, model, {"content": word + " "})
        yield _chunk(completion_id, model, {}, "stop")


_runtime: AssistantRuntime | None = None


def get_runtime() -> AssistantRuntime:
    """Lazily build the process-wide runtime (fake under OCR_ASSISTANT_FAKE)."""
    global _runtime
    if _runtime is None:
        if os.environ.get("OCR_ASSISTANT_FAKE") == "1":
            _runtime = FakeAssistantRuntime()
        else:
            _runtime = AssistantRuntime()
    return _runtime


def reset_runtime() -> None:
    """Drop the cached runtime (tests switch fake/real between cases)."""
    global _runtime
    _runtime = None
