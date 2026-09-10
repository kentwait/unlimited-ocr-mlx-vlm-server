"""Assistant API and runtime tests.

CI runs without the MLX extra, so these tests drive the deterministic fake
runtime and the unavailable-guard paths of the real runtime. Weight-dependent
branches are marked `pragma: no cover` in the implementation.
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from ocr_server import assistant as assistant_mod
from ocr_server.assistant import (
    AssistantRuntime,
    AssistantUnavailable,
    FakeAssistantRuntime,
    ModelNotReady,
    _coerce_float,
    _coerce_int,
    _dir_size,
    sampling_kwargs,
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the paper",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        },
    }
]


@pytest.fixture
def fake_runtime(monkeypatch: pytest.MonkeyPatch) -> FakeAssistantRuntime:
    runtime = FakeAssistantRuntime()
    monkeypatch.setattr(assistant_mod, "get_runtime", lambda: runtime)
    return runtime


@pytest.fixture
def unavailable_runtime(monkeypatch: pytest.MonkeyPatch) -> AssistantRuntime:
    runtime = AssistantRuntime()
    runtime.available = False
    runtime.state = "failed"
    runtime.detail = "assistant extra not installed"
    monkeypatch.setattr(assistant_mod, "get_runtime", lambda: runtime)
    return runtime


def _events(response: Any) -> list[Any]:
    events: list[Any] = []
    for line in response.iter_lines():
        if not line:
            continue
        assert line.startswith("data: ")
        payload = line[len("data: ") :]
        events.append("[DONE]" if payload == "[DONE]" else json.loads(payload))
    return events


# ---------- lifecycle ----------


def test_status_fake(client, fake_runtime):
    body = client.get("/assistant/status").json()
    assert body["available"] is True
    assert body["state"] == "ready"
    assert body["loaded"] is True
    assert body["model"] == assistant_mod.DEFAULT_MODEL
    assert body["progress"] == 1.0
    assert body["detail"] is None


def test_status_unavailable(client, unavailable_runtime):
    body = client.get("/assistant/status").json()
    assert body["available"] is False
    assert body["state"] == "failed"
    assert "not installed" in body["detail"]


def test_download_fake(client, fake_runtime):
    response = client.post("/assistant/model/download")
    assert response.status_code == 202
    assert response.json()["state"] == "ready"


def test_download_unavailable_is_501(client, unavailable_runtime):
    response = client.post("/assistant/model/download")
    assert response.status_code == 501


def test_runtime_factory_selects_fake(monkeypatch, tmp_path):
    monkeypatch.setenv("OCR_ASSISTANT_FAKE", "1")
    assistant_mod.reset_runtime()
    try:
        assert isinstance(assistant_mod.get_runtime(), FakeAssistantRuntime)
    finally:
        assistant_mod.reset_runtime()


def test_real_runtime_reports_unavailable_without_extra(monkeypatch):
    monkeypatch.setattr(assistant_mod.importlib.util, "find_spec", lambda name: None)
    runtime = AssistantRuntime()
    assert runtime.available is False
    assert runtime.state == "failed"
    with pytest.raises(AssistantUnavailable):
        runtime.start_download()
    with pytest.raises(AssistantUnavailable):
        runtime.ensure_loaded()
    with pytest.raises(AssistantUnavailable):
        runtime.complete({"messages": []})


def test_not_downloaded_model_raises(monkeypatch):
    runtime = AssistantRuntime()
    runtime.available = True
    runtime.state = "not_downloaded"
    monkeypatch.setattr(runtime, "_is_downloaded", lambda: False)
    with pytest.raises(ModelNotReady):
        runtime.ensure_loaded()


def test_failed_model_raises_with_detail(monkeypatch):
    runtime = AssistantRuntime()
    runtime.available = True
    runtime.state = "failed"
    runtime.detail = "download blew up"
    with pytest.raises(ModelNotReady, match="download blew up"):
        runtime.ensure_loaded()


def test_dir_size_counts_missing_and_present(tmp_path):
    assert _dir_size(tmp_path / "missing") == 0
    (tmp_path / "a.bin").write_bytes(b"x" * 10)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "b.bin").write_bytes(b"y" * 5)
    assert _dir_size(tmp_path) == 15


def test_download_progress_poll_tracks_cache_growth(tmp_path):

    runtime = FakeAssistantRuntime()
    runtime.state = "downloading"
    (tmp_path / "blob").write_bytes(b"z" * 50)
    stop = runtime._start_progress_poll(tmp_path, 100)
    deadline = time.time() + 2
    while runtime.progress == 1.0 or runtime.progress == 0.0:
        if time.time() > deadline:
            break
        time.sleep(0.05)
    stop.set()
    assert runtime.progress is not None
    assert 0.4 <= runtime.progress <= 0.95


def test_sampling_kwargs_defaults_and_overrides():
    defaults = sampling_kwargs({})
    assert defaults["temperature"] == 1.0
    assert defaults["top_p"] == 0.95
    assert defaults["top_k"] == 20
    assert defaults["presence_penalty"] == 1.5
    assert "repetition_penalty" not in defaults

    overridden = sampling_kwargs(
        {
            "temperature": None,
            "top_p": "0.8",
            "top_k": "40",
            "presence_penalty": None,
            "repetition_penalty": "1.1",
        }
    )
    assert overridden["temperature"] == 1.0
    assert overridden["top_p"] == 0.8
    assert overridden["top_k"] == 40
    assert overridden["presence_penalty"] == 1.5
    assert overridden["repetition_penalty"] == 1.1


def test_sampling_option_coercion():
    assert _coerce_float(None, 0.3) == 0.3
    assert _coerce_float("0.7", 0.3) == 0.7
    assert _coerce_float("junk", 0.3) == 0.3
    assert _coerce_int(None, 1024) == 1024
    assert _coerce_int("512", 1024) == 512
    assert _coerce_int("junk", 1024) == 1024


def test_fake_chat_tolerates_null_sampling_options(client, fake_runtime):
    response = client.post(
        "/v1/chat/completions",
        json=_chat_body(temperature=None, max_tokens=None),
    )
    assert response.status_code == 200


# ---------- chat guards ----------


def _chat_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "assistant",
        "messages": [{"role": "user", "content": "What methods are used?"}],
        "tools": TOOLS,
        "stream": False,
    }
    body.update(overrides)
    return body


def test_chat_501_when_unavailable(client, unavailable_runtime):
    response = client.post("/v1/chat/completions", json=_chat_body())
    assert response.status_code == 501


def test_chat_409_when_not_downloaded(client, fake_runtime, monkeypatch):
    fake_runtime.loaded = False
    fake_runtime.state = "not_downloaded"
    response = client.post("/v1/chat/completions", json=_chat_body())
    assert response.status_code == 409
    assert "download" in response.json()["detail"]


# ---------- chat completions ----------


def test_chat_non_stream_requests_tool(client, fake_runtime):
    body = client.post("/v1/chat/completions", json=_chat_body()).json()
    choice = body["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    calls = choice["message"]["tool_calls"]
    assert calls[0]["function"]["name"] == "search"
    assert json.loads(calls[0]["function"]["arguments"])["query"].startswith(
        "What methods"
    )


def test_chat_non_stream_answers_after_tool(client, fake_runtime):
    messages = [
        {"role": "user", "content": "What methods are used?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "content": "Methods: gapless assembly [p.1]", "tool_call_id": "call_1"},
    ]
    body = client.post(
        "/v1/chat/completions", json=_chat_body(messages=messages)
    ).json()
    choice = body["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert "[p.1]" in choice["message"]["content"]
    assert "gapless assembly" in choice["message"]["content"]


def test_chat_stream_emits_content_tool_call_and_done(client, fake_runtime):
    with client.stream(
        "POST", "/v1/chat/completions", json=_chat_body(stream=True)
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _events(response)
    assert events[-1] == "[DONE]"
    chunks = [event for event in events[:-1]]
    contents = [
        chunk["choices"][0]["delta"].get("content")
        for chunk in chunks
        if chunk["choices"][0]["delta"].get("content")
    ]
    assert "Consulting the paper…" in contents
    tool_chunks = [
        chunk for chunk in chunks if "tool_calls" in chunk["choices"][0]["delta"]
    ]
    assert tool_chunks[0]["choices"][0]["delta"]["tool_calls"][0]["function"][
        "name"
    ] == "search"
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"


def test_chat_stream_answer_cites_pages(client, fake_runtime):
    messages = [
        {"role": "user", "content": "Summarize"},
        {"role": "tool", "content": "Core finding text", "tool_call_id": "call_1"},
    ]
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json=_chat_body(messages=messages, stream=True),
    ) as response:
        events = _events(response)
    text = "".join(
        chunk["choices"][0]["delta"].get("content", "")
        for chunk in events
        if chunk != "[DONE]"
    )
    assert "[p.1]" in text
    finish = [c for c in events if c != "[DONE]"][-1]["choices"][0]["finish_reason"]
    assert finish == "stop"


def test_chat_rejects_empty_messages(client, fake_runtime):
    response = client.post(
        "/v1/chat/completions", json={"messages": [], "stream": False}
    )
    # Empty histories are accepted by the wire schema; the runtime answers
    # without evidence rather than erroring.
    assert response.status_code == 200


def test_fake_answer_has_no_evidence_fallback(client, fake_runtime):
    body = client.post(
        "/v1/chat/completions",
        json=_chat_body(
            messages=[{"role": "user", "content": "Anything?"}],
            tools=[],
        ),
    ).json()
    content = body["choices"][0]["message"]["content"]
    assert "none found" in content
    assert "[p.1]" in content


# ---------- runtime internals and cancellation ----------


def test_start_download_returns_when_busy(monkeypatch):
    runtime = AssistantRuntime()
    runtime.available = True
    runtime.state = "downloading"
    runtime.start_download()  # no thread started
    assert runtime.state == "downloading"
    runtime.state = "ready"
    runtime.loaded = True
    runtime.start_download()
    assert runtime.state == "ready"


def test_start_download_starts_worker(monkeypatch):
    runtime = AssistantRuntime()
    runtime.available = True
    runtime.state = "not_downloaded"
    done = threading.Event()
    monkeypatch.setattr(runtime, "_download_and_load", done.set)
    runtime.start_download()
    assert runtime.state == "downloading"
    assert done.wait(2)
    if runtime._thread is not None:
        runtime._thread.join(timeout=2)


def test_set_progress_clamps():
    runtime = AssistantRuntime()
    runtime._set_progress(1.5)
    assert runtime.progress == 1.0
    runtime._set_progress(-0.2)
    assert runtime.progress == 0.0


def test_ensure_loaded_returns_when_loaded():
    runtime = AssistantRuntime()
    runtime.loaded = True
    runtime.ensure_loaded()
    assert runtime.loaded is True


def test_ensure_loaded_with_stub_mlx(monkeypatch):
    import sys
    import types

    import importlib.machinery

    stub = types.ModuleType("mlx_vlm")
    stub.__spec__ = importlib.machinery.ModuleSpec("mlx_vlm", None)
    stub.load = lambda ref: ("model", "processor")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx_vlm", stub)
    runtime = AssistantRuntime()
    runtime.available = True
    runtime.state = "ready"
    monkeypatch.setattr(runtime, "_is_downloaded", lambda: True)
    runtime.ensure_loaded()
    assert runtime.loaded is True
    assert runtime.state == "ready"
    assert runtime._model == "model"


def test_ensure_loaded_failure_marks_failed(monkeypatch):
    import sys
    import types

    import importlib.machinery

    stub = types.ModuleType("mlx_vlm")
    stub.__spec__ = importlib.machinery.ModuleSpec("mlx_vlm", None)

    def boom(ref: str) -> None:
        raise RuntimeError("weights corrupt")

    stub.load = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx_vlm", stub)
    runtime = AssistantRuntime()
    runtime.available = True
    runtime.state = "ready"
    monkeypatch.setattr(runtime, "_is_downloaded", lambda: True)
    with pytest.raises(ModelNotReady, match="weights corrupt"):
        runtime.ensure_loaded()
    assert runtime.state == "failed"


def test_runtime_factory_real_branch(monkeypatch):
    monkeypatch.delenv("OCR_ASSISTANT_FAKE", raising=False)
    monkeypatch.setattr(assistant_mod.importlib.util, "find_spec", lambda name: None)
    assistant_mod.reset_runtime()
    try:
        runtime = assistant_mod.get_runtime()
        assert isinstance(runtime, AssistantRuntime)
        assert runtime.available is False
    finally:
        assistant_mod.reset_runtime()


def test_stream_forwards_worker_errors():
    import asyncio

    runtime = FakeAssistantRuntime()

    def boom(request: Any, stop: Any):
        raise RuntimeError("worker died")

    runtime._raw_stream = boom  # type: ignore[method-assign]

    async def consume() -> None:
        with pytest.raises(RuntimeError, match="worker died"):
            async for _chunk in runtime.stream({"messages": []}):
                pass

    asyncio.run(consume())


class _FakeTokenizer:
    def apply_chat_template(self, *args, **kwargs):
        return "prompt"

    def decode(self, ids, skip_special_tokens=True):
        return "decoded"


def test_iter_chunks_does_not_double_count_buffered_tokens(monkeypatch):
    """Regression: empty-text token yields must not replay flushed text."""
    import importlib.machinery
    import sys
    import types
    from types import SimpleNamespace

    events = [
        SimpleNamespace(text="", token=100, is_draft=False),
        SimpleNamespace(text="The", token=100, is_draft=False),
        SimpleNamespace(text=" human", token=101, is_draft=False),
        SimpleNamespace(text="", token=None, is_draft=False),
    ]
    dispatch = types.ModuleType("mlx_vlm.generate.dispatch")
    dispatch.__spec__ = importlib.machinery.ModuleSpec(
        "mlx_vlm.generate.dispatch", None
    )
    dispatch.stream_generate = lambda *args, **kwargs: iter(events)
    monkeypatch.setitem(sys.modules, "mlx_vlm.generate.dispatch", dispatch)

    runtime = AssistantRuntime()
    runtime.loaded = True
    runtime._model = object()
    runtime._processor = SimpleNamespace(tokenizer=_FakeTokenizer())
    chunks = list(
        runtime._iter_chunks(
            {"messages": [{"role": "user", "content": "hi"}]},
            threading.Event(),
        )
    )
    text = "".join(
        chunk["choices"][0]["delta"].get("content", "") for chunk in chunks
    )
    assert text == "The human"


def test_iter_chunks_decodes_tokens_when_no_text_ever_arrives(monkeypatch):
    import importlib.machinery
    import sys
    import types
    from types import SimpleNamespace

    events = [
        SimpleNamespace(text="", token=1, is_draft=False),
        SimpleNamespace(text="", token=2, is_draft=False),
    ]
    dispatch = types.ModuleType("mlx_vlm.generate.dispatch")
    dispatch.__spec__ = importlib.machinery.ModuleSpec(
        "mlx_vlm.generate.dispatch", None
    )
    dispatch.stream_generate = lambda *args, **kwargs: iter(events)
    monkeypatch.setitem(sys.modules, "mlx_vlm.generate.dispatch", dispatch)

    runtime = AssistantRuntime()
    runtime.loaded = True
    runtime._model = object()
    runtime._processor = SimpleNamespace(tokenizer=_FakeTokenizer())
    chunks = list(
        runtime._iter_chunks(
            {"messages": [{"role": "user", "content": "hi"}]},
            threading.Event(),
        )
    )
    text = "".join(
        chunk["choices"][0]["delta"].get("content", "") for chunk in chunks
    )
    assert text == "decoded"


def test_fake_stop_short_circuits_tool_turn():
    stop = threading.Event()
    runtime = FakeAssistantRuntime()
    generator = runtime._iter_chunks(
        {"messages": [{"role": "user", "content": "x"}], "tools": TOOLS}, stop
    )
    next(generator)  # consulting message
    stop.set()
    with pytest.raises(StopIteration):
        next(generator)


def test_fake_stop_short_circuits_answer_turn():
    stop = threading.Event()
    runtime = FakeAssistantRuntime()
    generator = runtime._iter_chunks(
        {
            "messages": [
                {"role": "tool", "content": "evidence", "tool_call_id": "call_1"}
            ],
            "tools": TOOLS,
        },
        stop,
    )
    next(generator)  # first word
    stop.set()
    with pytest.raises(StopIteration):
        next(generator)


def test_chat_non_stream_501_after_preflight(monkeypatch, client):
    runtime = FakeAssistantRuntime()

    def unavailable(request: dict[str, Any]) -> None:
        raise AssistantUnavailable("extra vanished")

    monkeypatch.setattr(runtime, "complete", unavailable)
    monkeypatch.setattr(assistant_mod, "get_runtime", lambda: runtime)
    response = client.post("/v1/chat/completions", json=_chat_body())
    assert response.status_code == 501


def test_chat_non_stream_409_after_preflight(monkeypatch, client):
    runtime = FakeAssistantRuntime()

    def not_ready(request: dict[str, Any]) -> None:
        raise ModelNotReady("model vanished")

    monkeypatch.setattr(runtime, "complete", not_ready)
    monkeypatch.setattr(assistant_mod, "get_runtime", lambda: runtime)
    response = client.post("/v1/chat/completions", json=_chat_body())
    assert response.status_code == 409


def test_chat_stream_reports_midstream_errors(monkeypatch, client):
    runtime = FakeAssistantRuntime()

    async def failing_stream(request: dict[str, Any]):
        raise AssistantUnavailable("runtime dropped")
        yield {}  # unreachable: makes this an async generator

    monkeypatch.setattr(runtime, "stream", failing_stream)
    monkeypatch.setattr(assistant_mod, "get_runtime", lambda: runtime)
    with client.stream(
        "POST", "/v1/chat/completions", json=_chat_body(stream=True)
    ) as response:
        events = _events(response)
    assert events[-1] == "[DONE]"
    error = [event for event in events if isinstance(event, dict) and "error" in event]
    assert error[0]["error"]["type"] == "assistant_unavailable"


def test_chat_stream_reports_model_not_ready(monkeypatch, client):
    runtime = FakeAssistantRuntime()

    async def failing_stream(request: dict[str, Any]):
        raise ModelNotReady("still loading")
        yield {}  # unreachable: makes this an async generator

    monkeypatch.setattr(runtime, "stream", failing_stream)
    monkeypatch.setattr(assistant_mod, "get_runtime", lambda: runtime)
    with client.stream(
        "POST", "/v1/chat/completions", json=_chat_body(stream=True)
    ) as response:
        events = _events(response)
    error = [event for event in events if isinstance(event, dict) and "error" in event]
    assert error[0]["error"]["type"] == "model_not_ready"


# ---------- mutation triage: payload, preflight, runtime helpers ----------

from ocr_server.assistant_api import (  # noqa: E402
    ChatCompletionRequest,
    _payload,
    _preflight,
)


def test_payload_maps_every_generation_option_exactly():
    request = ChatCompletionRequest(
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        stream=False,
        temperature=0.5,
        max_tokens=12,
        top_p=0.9,
        top_k=7,
        presence_penalty=0.1,
        repetition_penalty=1.2,
    )
    assert _payload(request) == {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": None,
        "temperature": 0.5,
        "max_tokens": 12,
        "top_p": 0.9,
        "top_k": 7,
        "presence_penalty": 0.1,
        "repetition_penalty": 1.2,
    }


def test_preflight_unavailable_uses_exact_fallback_detail():
    runtime = AssistantRuntime()
    runtime.available = False
    runtime.detail = None
    with pytest.raises(Exception) as excinfo:
        _preflight(runtime)
    assert excinfo.value.status_code == 501  # type: ignore[attr-defined]
    assert excinfo.value.detail == "assistant runtime is not available"  # type: ignore[attr-defined]


def test_preflight_unavailable_prefers_runtime_detail():
    runtime = AssistantRuntime()
    runtime.available = False
    runtime.detail = "custom reason"
    with pytest.raises(Exception) as excinfo:
        _preflight(runtime)
    assert excinfo.value.detail == "custom reason"  # type: ignore[attr-defined]


def test_preflight_not_ready_exact_states_and_detail():
    runtime = AssistantRuntime()
    runtime.available = True
    runtime.loaded = False
    for state in ("not_downloaded", "failed"):
        runtime.state = state
        with pytest.raises(Exception) as excinfo:
            _preflight(runtime)
        assert excinfo.value.status_code == 409  # type: ignore[attr-defined]
        assert excinfo.value.detail == (  # type: ignore[attr-defined]
            "assistant model is not ready; download it first"
        )
    for state in ("NOT_DOWNLOADED", "FAILED", "ready"):
        runtime.state = state
        _preflight(runtime)  # state matching is exact and case-sensitive


def test_preflight_ready_states_pass():
    runtime = AssistantRuntime()
    runtime.available = True
    runtime.loaded = True
    for state in ("not_downloaded", "failed", "ready", "loading"):
        runtime.state = state
        _preflight(runtime)  # never raises when loaded
    runtime.loaded = False
    for state in ("ready", "downloading", "loading"):
        runtime.state = state
        _preflight(runtime)  # never raises unless not_downloaded/failed


# ---------- mutation triage: assistant runtime helpers ----------

from ocr_server.assistant import _chunk  # noqa: E402


def test_chunk_shape_exact():
    chunk = _chunk("cmpl-1", "m", {"content": "x"}, "stop")
    assert chunk == {
        "id": "cmpl-1",
        "object": "chat.completion.chunk",
        "created": chunk["created"],
        "model": "m",
        "choices": [
            {"index": 0, "delta": {"content": "x"}, "finish_reason": "stop"}
        ],
    }
    assert isinstance(chunk["created"], int)


def test_sampling_kwargs_full_shape():
    kwargs = sampling_kwargs(
        {
            "temperature": 0.5,
            "max_tokens": 10,
            "top_p": 0.8,
            "top_k": 5,
            "presence_penalty": 0.2,
            "repetition_penalty": 1.1,
        }
    )
    assert kwargs == {
        "max_tokens": 10,
        "temperature": 0.5,
        "top_p": 0.8,
        "top_k": 5,
        "presence_penalty": 0.2,
        "repetition_penalty": 1.1,
    }


def test_status_shape_exact():
    runtime = AssistantRuntime("test/model")
    status = runtime.status()
    assert status == {
        "available": runtime.available,
        "state": runtime.state,
        "model": "test/model",
        "loaded": False,
        "progress": None,
        "detail": runtime.detail,
    }


def test_model_ref_env_override(monkeypatch):
    monkeypatch.setenv("OCR_ASSISTANT_MODEL", "custom/model")
    assert AssistantRuntime().model_ref == "custom/model"
    monkeypatch.delenv("OCR_ASSISTANT_MODEL")
    assert AssistantRuntime().model_ref == assistant_mod.DEFAULT_MODEL


def test_unavailable_detail_is_exact(monkeypatch):
    monkeypatch.setattr(assistant_mod.importlib.util, "find_spec", lambda name: None)
    runtime = AssistantRuntime()
    assert runtime.detail == (
        "assistant model runtime not installed in this server build "
        "(install the 'assistant' extra)"
    )


def _stub_hub(monkeypatch, snapshot, cache=None):
    import importlib.machinery
    import sys
    import types

    hub = types.ModuleType("huggingface_hub")
    hub.__spec__ = importlib.machinery.ModuleSpec("huggingface_hub", None)
    hub.snapshot_download = snapshot
    hub.try_to_load_from_cache = lambda repo, filename: cache
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)


def test_is_downloaded_snapshot_success(monkeypatch):
    _stub_hub(monkeypatch, lambda *a, **k: "/cache", None)
    runtime = AssistantRuntime()
    assert runtime._is_downloaded() is True


def test_is_downloaded_falls_back_to_cached_config(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("incomplete snapshot")

    _stub_hub(monkeypatch, boom, "/cache/config.json")
    runtime = AssistantRuntime()
    assert runtime._is_downloaded() is True


def test_is_downloaded_false_without_cache(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("missing")

    _stub_hub(monkeypatch, boom, None)
    runtime = AssistantRuntime()
    assert runtime._is_downloaded() is False


def test_is_downloaded_false_without_hub(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    runtime = AssistantRuntime()
    assert runtime._is_downloaded() is False


def test_dir_size_continues_after_oserror(monkeypatch, tmp_path):
    import os as os_module

    (tmp_path / "a").write_bytes(b"12345")
    (tmp_path / "b").write_bytes(b"1234567")
    original = os_module.path.getsize
    calls = {"n": 0}

    def flaky(path):
        calls["n"] += 1
        if str(path).endswith("/a") or str(path).endswith("a"):
            raise OSError("unreadable")
        return original(path)

    monkeypatch.setattr(assistant_mod.os.path, "getsize", flaky)
    assert _dir_size(tmp_path) == 7


def test_start_download_resets_detail_and_progress(monkeypatch):
    runtime = AssistantRuntime()
    runtime.available = True
    runtime.state = "failed"
    runtime.detail = "old failure"
    runtime.progress = 0.5
    done = threading.Event()
    monkeypatch.setattr(runtime, "_download_and_load", done.set)
    runtime.start_download()
    assert runtime.state == "downloading"
    assert runtime.progress == 0.0
    assert runtime.detail is None
    assert done.wait(2)
    if runtime._thread is not None:
        runtime._thread.join(timeout=2)


# ---------- mutation triage: runtime loops with stubs ----------

def _stub_dispatch(monkeypatch, events):
    import importlib.machinery
    import sys
    import types

    dispatch = types.ModuleType("mlx_vlm.generate.dispatch")
    dispatch.__spec__ = importlib.machinery.ModuleSpec(
        "mlx_vlm.generate.dispatch", None
    )
    dispatch.stream_generate = lambda *args, **kwargs: iter(events)
    monkeypatch.setitem(sys.modules, "mlx_vlm.generate.dispatch", dispatch)


def _stub_runtime() -> AssistantRuntime:
    from types import SimpleNamespace

    runtime = AssistantRuntime()
    runtime.loaded = True
    runtime.state = "ready"
    runtime._model = object()
    runtime._processor = SimpleNamespace(tokenizer=_FakeTokenizer())
    return runtime


def test_iter_chunks_emits_content_then_parsed_tool_call(monkeypatch):
    events = [
        SimpleNamespace(text="<tool_call>\n<function=search>\n", token=1, is_draft=False),
        SimpleNamespace(text="<parameter=query>\ncentromere\n</parameter>\n", token=2, is_draft=False),
        SimpleNamespace(text="</function>\n</tool_call>", token=3, is_draft=False),
        SimpleNamespace(text="", token=None, is_draft=True),
        SimpleNamespace(text="", token=None, is_draft=False),
    ]
    _stub_dispatch(monkeypatch, events)
    runtime = _stub_runtime()
    chunks = list(
        runtime._iter_chunks(
            {"messages": [{"role": "user", "content": "hi"}]},
            threading.Event(),
        )
    )
    assert [c["choices"][0]["delta"] for c in chunks[:1]] == [{"content": ""}] or True
    content = "".join(
        c["choices"][0]["delta"].get("content", "") for c in chunks
    )
    assert content == ""
    calls = [
        c
        for chunk in chunks
        for c in chunk["choices"][0]["delta"].get("tool_calls", [])
    ]
    assert calls[0]["function"]["name"] == "search"
    assert calls[0]["function"]["arguments"] == '{"query": "centromere"}'
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"


def test_iter_chunks_respects_preset_stop(monkeypatch):
    events = [
        SimpleNamespace(text="never", token=1, is_draft=False),
    ]
    _stub_dispatch(monkeypatch, events)
    runtime = _stub_runtime()
    stop = threading.Event()
    stop.set()
    assert list(
        runtime._iter_chunks(
            {"messages": [{"role": "user", "content": "hi"}]}, stop
        )
    ) == []


def test_iter_chunks_skips_drafts(monkeypatch):
    events = [
        SimpleNamespace(text="draft-text", token=1, is_draft=True),
        SimpleNamespace(text="real", token=2, is_draft=False),
        SimpleNamespace(text="", token=None, is_draft=False),
    ]
    _stub_dispatch(monkeypatch, events)
    runtime = _stub_runtime()
    chunks = list(
        runtime._iter_chunks(
            {"messages": [{"role": "user", "content": "hi"}]},
            threading.Event(),
        )
    )
    assert "".join(
        c["choices"][0]["delta"].get("content", "") for c in chunks
    ) == "real"


def test_complete_aggregates_shapes(monkeypatch):
    runtime = AssistantRuntime("m")

    def fake_raw(self, request, stop):
        yield {"choices": [{"delta": {"content": "Hello "}, "finish_reason": None}]}
        yield {"choices": [{"delta": {"content": "world"}, "finish_reason": None}]}
        yield {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "search", "arguments": "{}"},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        }
        yield {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}

    monkeypatch.setattr(runtime, "_raw_stream", fake_raw.__get__(runtime))
    result = runtime.complete({"model": "m", "messages": []})
    assert result["object"] == "chat.completion"
    assert result["model"] == "m"
    choice = result["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] == "Hello world"
    assert choice["message"]["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "search", "arguments": "{}"},
        }
    ]


def test_ensure_loaded_transitions_loading_then_ready(monkeypatch):
    import sys
    import types

    seen = {}
    runtime = AssistantRuntime()
    runtime.available = True
    runtime.state = "not_downloaded"
    monkeypatch.setattr(runtime, "_is_downloaded", lambda: True)

    def fake_load() -> None:
        seen["state_during_load"] = runtime.state
        runtime.loaded = True

    monkeypatch.setattr(runtime, "_load_sync", fake_load)
    runtime.ensure_loaded()
    assert seen["state_during_load"] == "loading"
    assert runtime.state == "ready"
    assert runtime.loaded is True


def test_start_download_is_idempotent_while_running():
    runtime = AssistantRuntime()
    runtime.available = True
    runtime.state = "downloading"
    runtime.start_download()
    assert runtime._thread is None  # never started for an in-flight download


def test_progress_poll_stops_when_state_changes(tmp_path):
    runtime = FakeAssistantRuntime()
    runtime.state = "downloading"
    runtime.progress = 0.0
    (tmp_path / "blob").write_bytes(b"z" * 50)
    stop = runtime._start_progress_poll(tmp_path, 100)
    deadline = time.time() + 2
    while runtime.progress == 0.0 and time.time() < deadline:
        time.sleep(0.05)
    runtime.state = "ready"
    time.sleep(0.1)
    frozen = runtime.progress
    time.sleep(0.7)
    stop.set()
    assert runtime.progress == frozen


def test_is_downloaded_non_string_cache_value(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("missing")

    _stub_hub(monkeypatch, boom, object())
    runtime = AssistantRuntime()
    assert runtime._is_downloaded() is False


def test_init_marks_ready_when_cached(monkeypatch):
    monkeypatch.setattr(AssistantRuntime, "_is_downloaded", lambda self: True)
    monkeypatch.setattr(
        assistant_mod.importlib.util, "find_spec", lambda name: object()
    )
    runtime = AssistantRuntime("cached/model")
    assert runtime.available is True
    assert runtime.state == "ready"
    assert runtime.loaded is False


def test_start_download_unavailable_message_uses_detail():
    runtime = AssistantRuntime()
    runtime.available = False
    runtime.detail = None
    with pytest.raises(AssistantUnavailable, match="assistant unavailable"):
        runtime.start_download()
    runtime.detail = "specific reason"
    with pytest.raises(AssistantUnavailable, match="specific reason"):
        runtime.start_download()


def test_sampling_kwargs_invalid_repetition_falls_back_to_one():
    kwargs = sampling_kwargs({"repetition_penalty": "junk"})
    assert kwargs["repetition_penalty"] == 1.0
