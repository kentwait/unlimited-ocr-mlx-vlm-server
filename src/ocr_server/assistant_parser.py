"""Qwen tool-call parsing and OpenAI-subset message conversion.

The sidecar exposes an OpenAI-compatible chat surface. Qwen3.5 emits tool
calls as XML, so this module converts between the two shapes:

- `QwenStreamFilter` incrementally strips ``<think>`` blocks and withholds
  ``<tool_call>`` blocks from display content while collecting them.
- `parse_tool_calls` turns collected blocks into OpenAI ``tool_calls`` entries.
- `to_chat_messages` converts request messages into the HF-style list the
  Qwen chat template renders (tool results stay role ``tool``; the template
  wraps them in ``<tool_response>``).

The filter is deliberately stateful and total: malformed or truncated output
must never raise, and withheld content must never leak into the answer.
"""

from __future__ import annotations

import json
import re
from typing import Any

FUNCTION_RE = re.compile(r"<function=([^>\s]+)\s*>(.*?)</function>", re.DOTALL)
PARAMETER_RE = re.compile(r"<parameter=([^>\s]+)\s*>(.*?)</parameter>", re.DOTALL)

TEXT = "text"
THINK = "think"
TOOL = "tool"

_OPEN_THINK = "<think>"
_CLOSE_THINK = "</think>"
_OPEN_TOOL = "<tool_call>"
_CLOSE_TOOL = "</tool_call>"
_TAGS = (_OPEN_THINK, _CLOSE_THINK, _OPEN_TOOL, _CLOSE_TOOL)

#: Safety valve: never buffer an unterminated tool block forever.
MAX_TOOL_BUFFER = 64 * 1024


def _strip_wrapping_newlines(value: str) -> str:
    """Remove the single framing newline the template adds around values."""
    if value.startswith("\n"):
        value = value[1:]
    if value.endswith("\n"):
        value = value[:-1]
    return value


def parse_tool_calls(blocks: list[str]) -> list[dict[str, Any]]:
    """Convert raw tool-call blocks into OpenAI ``tool_calls`` entries.

    Each block is the content between ``<tool_call>`` and ``</tool_call>``.
    Parameters are returned as strings; tool schemas coerce where numeric.
    """
    calls: list[dict[str, Any]] = []
    for block in blocks:
        for match in FUNCTION_RE.finditer(block):
            name = match.group(1).strip()
            args: dict[str, str] = {}
            for param in PARAMETER_RE.finditer(match.group(2)):
                key = param.group(1).strip()
                if key:
                    args[key] = _strip_wrapping_newlines(param.group(2))
            calls.append(
                {
                    "id": f"call_{len(calls) + 1}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                }
            )
    return calls


def _partial_suffix_hold(buffer: str) -> int:
    """Length of a buffer suffix that could become one of the markers."""
    hold = 0
    for tag in _TAGS:
        for size in range(1, len(tag)):
            if buffer.endswith(tag[:size]):
                hold = max(hold, size)
    return hold


class QwenStreamFilter:
    """Incremental filter over generated text.

    ``feed`` returns the content safe to display. Thinking is dropped;
    tool-call blocks are withheld and collected for ``finish``.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._mode = TEXT
        self._blocks: list[str] = []

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def blocks(self) -> list[str]:
        return list(self._blocks)

    def feed(self, text: str) -> str:
        self._buffer += text
        emitted: list[str] = []
        while self._buffer:
            if self._mode == TEXT:
                index, tag = self._next_tag()
                if tag is None:
                    hold = _partial_suffix_hold(self._buffer)
                    cut = len(self._buffer) - hold
                    emitted.append(self._buffer[:cut])
                    self._buffer = self._buffer[cut:]
                    break
                emitted.append(self._buffer[:index])
                self._buffer = self._buffer[index + len(tag) :]
                if tag == _OPEN_THINK:
                    self._mode = THINK
                elif tag == _OPEN_TOOL:
                    self._mode = TOOL
            elif self._mode == THINK:
                index = self._buffer.find(_CLOSE_THINK)
                if index < 0:
                    hold = _partial_suffix_hold(self._buffer)
                    cut = len(self._buffer) - hold
                    self._buffer = self._buffer[cut:]
                    break
                self._buffer = self._buffer[index + len(_CLOSE_THINK) :]
                self._mode = TEXT
            else:  # TOOL
                index = self._buffer.find(_CLOSE_TOOL)
                if index < 0:
                    if len(self._buffer) > MAX_TOOL_BUFFER:
                        # Malformed output: give up on this block, resume text.
                        self._buffer = ""
                        self._mode = TEXT
                    break
                self._blocks.append(self._buffer[:index])
                self._buffer = self._buffer[index + len(_CLOSE_TOOL) :]
                self._mode = TEXT
        return "".join(emitted)

    def finish(self) -> tuple[str, list[str]]:
        """Flush: returns (trailing display text, collected tool blocks).

        An unterminated tool block is still parsed when it contains a
        function tag; otherwise it is discarded.
        """
        tail = ""
        if self._mode == TEXT:
            tail = self._buffer
        elif self._mode == TOOL and "<function=" in self._buffer:
            self._blocks.append(self._buffer)
        self._buffer = ""
        self._mode = TEXT
        return tail, list(self._blocks)

    def _next_tag(self) -> tuple[int, str | None]:
        best: tuple[int, str | None] = (len(self._buffer), None)
        for tag in _TAGS:
            index = self._buffer.find(tag)
            if index >= 0 and index < best[0]:
                best = (index, tag)
        return best


def _content_text(content: Any) -> str:
    """Flatten an OpenAI message content into text (images are out of v1)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "\n".join(parts)
    return ""


def to_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI request messages to the Qwen chat-template message list.

    System messages are merged into one leading system message (the Qwen
    template raises when system is not first). Tool results keep role
    ``tool``; the template wraps them in ``<tool_response>``.
    """
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", ""))
        if role == "system":
            text = _content_text(message.get("content"))
            if text:
                system_parts.append(text)
            continue
        if role == "user":
            converted.append({"role": "user", "content": _content_text(message.get("content"))})
        elif role == "assistant":
            item: dict[str, Any] = {
                "role": "assistant",
                "content": _content_text(message.get("content")),
            }
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                item["tool_calls"] = tool_calls
            if item["content"] or item.get("tool_calls"):
                converted.append(item)
        elif role == "tool":
            converted.append(
                {"role": "tool", "content": _content_text(message.get("content"))}
            )
    if system_parts:
        converted.insert(0, {"role": "system", "content": "\n\n".join(system_parts)})
    return converted
