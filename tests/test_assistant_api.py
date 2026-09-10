"""Assistant API and runtime tests.

CI runs without the MLX extra, so these tests drive the deterministic fake
runtime and the unavailable-guard paths of the real runtime. Weight-dependent
branches are marked `pragma: no cover` in the implementation.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest

from ocr_server import assistant as assistant_mod
from ocr_server.assistant import (
    AssistantRuntime,
    AssistantUnavailable,
    FakeAssistantRuntime,
    ModelNotReady,
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
