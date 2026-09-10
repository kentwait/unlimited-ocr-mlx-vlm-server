"""Assistant runtime: local chat model lifecycle and OpenAI-subset streaming.

The assistant is optional: when the ``mlx-vlm`` extra is not installed the
endpoint reports ``available: false`` and returns 501. CI and contract checks
use `FakeAssistantRuntime`, selected by ``OCR_ASSISTANT_FAKE=1``.

Lifecycle: ``not_downloaded -> downloading -> loading -> ready`` with
``failed`` for download/load errors. Generation is serialized through a lock;
each streaming request runs in a worker thread and stops early when the
client disconnects.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from .assistant_parser import (
    QwenStreamFilter,
    parse_tool_calls,
    to_chat_messages,
)

log = logging.getLogger("ocr_server.assistant")

DEFAULT_MODEL = "mlx-community/Qwen3.5-9B-MLX-8bit"
DEFAULT_MAX_TOKENS = 1024
#: Qwen3.5's evaluated best-practice sampling (model card). Without the
#: presence penalty the small models loop on repeated parameter values.
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 0.95
DEFAULT_TOP_K = 20
DEFAULT_PRESENCE_PENALTY = 1.5

STATE_NOT_DOWNLOADED = "not_downloaded"
STATE_DOWNLOADING = "downloading"
STATE_LOADING = "loading"
STATE_READY = "ready"
STATE_FAILED = "failed"


class AssistantUnavailable(RuntimeError):
    """The optional assistant extra is not installed in this server build."""


class ModelNotReady(RuntimeError):
    """The model is missing or failed to load; the client should download."""


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
    """mlx-vlm-backed runtime; loaded lazily and guarded by a single lock."""

    def __init__(self, model_ref: str | None = None) -> None:
        self.model_ref = model_ref or os.environ.get(
            "OCR_ASSISTANT_MODEL", DEFAULT_MODEL
        )
        self.available = importlib.util.find_spec("mlx_vlm") is not None
        self.loaded = False
        self.progress: float | None = None
        self.detail: str | None = None
        self.state = STATE_NOT_DOWNLOADED
        self._model: Any = None
        self._processor: Any = None
        self._infer_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        if not self.available:
            self.state = STATE_FAILED
            self.detail = (
                "assistant model runtime not installed in this server build "
                "(install the 'assistant' extra)"
            )
        elif self._is_downloaded():
            self.state = STATE_READY
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "state": self.state,
            "model": self.model_ref,
            "loaded": self.loaded,
            "progress": self.progress,
            "detail": self.detail,
        }

    def _is_downloaded(self) -> bool:
        try:
            from huggingface_hub import snapshot_download
            from huggingface_hub import try_to_load_from_cache
        except ImportError:  # pragma: no cover - extra missing
            return False
        try:
            snapshot_download(self.model_ref, local_files_only=True)
            return True
        except Exception:
            # Newer hubs raise IncompleteSnapshotError for caches written by
            # other tools (missing metadata files) even when the weights are
            # present — and that error subclasses LocalEntryNotFoundError; a
            # cached config is the practical signal, since loading can
            # complete the snapshot when the network is available.
            pass
        try:
            cached = try_to_load_from_cache(self.model_ref, "config.json")
            return isinstance(cached, str)
        except Exception:  # pragma: no cover - defensive
            return False

    def start_download(self) -> None:
        """Kick off download+load in the background (idempotent)."""
        if not self.available:
            raise AssistantUnavailable(self.detail or "assistant unavailable")
        with self._lifecycle_lock:
            if self.state in (STATE_DOWNLOADING, STATE_LOADING):
                return
            if self.state == STATE_READY and self.loaded:
                return
            self.state = STATE_DOWNLOADING
            self.progress = 0.0
            self.detail = None
            self._thread = threading.Thread(
                target=self._download_and_load, daemon=True
            )
            self._thread.start()

    def _set_progress(self, value: float) -> None:
        self.progress = max(0.0, min(1.0, value))

    def _download_and_load(self) -> None:  # pragma: no cover - needs weights
        try:
            self._download_sync()
            self.state = STATE_LOADING
            self._load_sync()
            self.progress = 1.0
            self.state = STATE_READY
        except Exception as exc:  # pragma: no cover - surfaced via status
            log.exception("assistant model setup failed")
            self.state = STATE_FAILED
            self.detail = str(exc)

    def _download_sync(self) -> None:  # pragma: no cover - network + weights
        from huggingface_hub import HfApi, snapshot_download

        total = 0
        cache_dir = self._cache_dir()
        try:
            info = HfApi().model_info(self.model_ref, files_metadata=True)
            total = sum(int(sibling.size or 0) for sibling in info.siblings or [])
        except Exception:
            total = 0
        stop: threading.Event | None = None
        if total > 0 and cache_dir is not None:
            stop = self._start_progress_poll(cache_dir, total)
        try:
            snapshot_download(self.model_ref)
        finally:
            if stop is not None:
                stop.set()

    def _cache_dir(self) -> Path | None:
        """Local Hugging Face cache directory for the pinned model."""
        try:
            from huggingface_hub.constants import HF_HUB_CACHE
        except ImportError:  # pragma: no cover - extra missing
            return None
        org, _, name = self.model_ref.partition("/")
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

    def _load_sync(self) -> None:  # pragma: no cover - loads MLX weights
        from mlx_vlm import load

        self._model, self._processor = load(self.model_ref)
        self.loaded = True

    def ensure_loaded(self) -> None:
        """Load on first use; raises ModelNotReady when the weights are absent."""
        if self.loaded:
            return
        if not self.available:
            raise AssistantUnavailable(self.detail or "assistant unavailable")
        if self.state == STATE_FAILED:
            raise ModelNotReady(self.detail or "assistant model failed to load")
        if not self._is_downloaded():
            self.state = STATE_NOT_DOWNLOADED
            raise ModelNotReady("assistant model is not downloaded")
        with self._lifecycle_lock:
            if self.loaded:
                return
            self.state = STATE_LOADING
            try:
                self._load_sync()
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
    tool calls, and citation parsing without weights.
    """

    def __init__(self, model_ref: str | None = None) -> None:
        super().__init__(model_ref)
        self.available = True
        self.loaded = True
        self.state = STATE_READY
        self.progress = 1.0
        self.detail = None

    def _is_downloaded(self) -> bool:  # pragma: no cover - trivial
        return True

    def start_download(self) -> None:
        self.state = STATE_READY
        self.progress = 1.0

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
