"""Assistant HTTP surface: catalog, model lifecycle, OpenAI-compatible chat.

The chat endpoint is a strict subset of the OpenAI chat-completions wire
format so the app's TanStack AI `openaiCompatible` adapter can talk to it:
SSE content deltas and `tool_calls` deltas in streaming mode, a single
completion object otherwise.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from . import assistant as assistant_runtime
from .assistant import (
    AssistantBusy,
    AssistantUnavailable,
    ModelNotReady,
)
from .schemas import (
    AssistantModel,
    AssistantModelRequest,
    AssistantModelsResponse,
    AssistantStatus,
)

router = APIRouter()


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str | None = None
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    presence_penalty: float | None = None
    repetition_penalty: float | None = None


def _payload(request: ChatCompletionRequest) -> dict[str, Any]:
    return {
        "model": request.model,
        "messages": request.messages,
        "tools": request.tools,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "top_p": request.top_p,
        "top_k": request.top_k,
        "presence_penalty": request.presence_penalty,
        "repetition_penalty": request.repetition_penalty,
    }


def _preflight(runtime: assistant_runtime.AssistantRuntime) -> None:
    """Reject before streaming so clients get real HTTP status codes."""
    if not runtime.available:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            runtime.detail or "assistant runtime is not available",
        )
    if not runtime.loaded and runtime.state in (
        "not_downloaded",
        "paused",
        "failed",
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            runtime.detail or "assistant model is not ready; download it first",
        )


@router.get("/assistant/status", response_model=AssistantStatus)
async def assistant_status() -> AssistantStatus:
    return AssistantStatus(**assistant_runtime.get_runtime().status())


@router.get("/assistant/models", response_model=AssistantModelsResponse)
async def assistant_models() -> AssistantModelsResponse:
    runtime = assistant_runtime.get_runtime()
    return AssistantModelsResponse(
        available=runtime.available,
        models=[AssistantModel(**entry) for entry in runtime.models()],
    )


@router.post(
    "/assistant/model/download",
    response_model=AssistantStatus,
    status_code=status.HTTP_202_ACCEPTED,
)
async def assistant_download(
    request: AssistantModelRequest | None = None,
) -> AssistantStatus:
    runtime = assistant_runtime.get_runtime()
    try:
        runtime.start_download(request.model if request else None)
    except AssistantUnavailable as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(exc)) from exc
    except AssistantBusy as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return AssistantStatus(**runtime.status())


@router.post("/assistant/model/use", response_model=AssistantStatus)
async def assistant_use(request: AssistantModelRequest) -> AssistantStatus:
    runtime = assistant_runtime.get_runtime()
    if request.model is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "model is required"
        )
    try:
        runtime.use(request.model)
    except AssistantUnavailable as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(exc)) from exc
    except ModelNotReady as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return AssistantStatus(**runtime.status())


@router.post("/assistant/model/cancel", response_model=AssistantStatus)
async def assistant_cancel() -> AssistantStatus:
    runtime = assistant_runtime.get_runtime()
    runtime.cancel_download()
    return AssistantStatus(**runtime.status())


@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest) -> Any:
    runtime = assistant_runtime.get_runtime()
    _preflight(runtime)
    payload = _payload(request)

    if not request.stream:
        try:
            return JSONResponse(runtime.complete(payload))
        except AssistantUnavailable as exc:
            raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(exc)) from exc
        except ModelNotReady as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    async def event_stream() -> Any:
        try:
            async for chunk in runtime.stream(payload):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except AssistantUnavailable as exc:
            error = {"error": {"message": str(exc), "type": "assistant_unavailable"}}
            yield f"data: {json.dumps(error)}\n\n"
        except ModelNotReady as exc:
            error = {"error": {"message": str(exc), "type": "model_not_ready"}}
            yield f"data: {json.dumps(error)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
