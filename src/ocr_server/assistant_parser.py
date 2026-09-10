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
#: Stray tag fragments a confused model can nest inside a parameter value.
TAG_FRAGMENT_RE = re.compile(r"</?(?:tool_call|function|parameter)[^>]*>")
#: A parameter opener, used to recover values from nested duplicate calls.
PARAMETER_OPEN_RE = re.compile(r"<parameter=[^>\s]+\s*>")

TEXT = "text"
THINK = "think"
TOOL = "tool"

_OPEN_THINK = "<think>"
_CLOSE_THINK = "</think>"
_OPEN_TOOL = "<tool_call>"
_CLOSE_TOOL = "</tool_call>"
_FUNCTION_OPEN = "<function="
_FUNCTION_CLOSE = "</function>"
_PARAM_OPEN = "<parameter="
_PARAM_CLOSE = "</parameter>"

#: Everything the scanner watches for in display text. Stray closers are
#: dropped; orphan openers put the filter into tool mode (the model forgot
#: the ``<tool_call>`` wrapper).
_SCAN_TAGS = (
    _OPEN_THINK,
    _OPEN_TOOL,
    _FUNCTION_OPEN,
    _PARAM_OPEN,
    _CLOSE_THINK,
    _CLOSE_TOOL,
    _FUNCTION_CLOSE,
    _PARAM_CLOSE,
)
_DROPPED_TAGS = (_CLOSE_THINK, _CLOSE_TOOL, _FUNCTION_CLOSE, _PARAM_CLOSE)
_TOOL_OPENERS = (_OPEN_TOOL, _FUNCTION_OPEN, _PARAM_OPEN)

#: Safety valve: never buffer an unterminated tool block forever.
MAX_TOOL_BUFFER = 64 * 1024


def _strip_wrapping_newlines(value: str) -> str:
    """Remove the framing newline the template adds around values."""
    if value.startswith("\n"):
        value = value[1:]
    if value.endswith("\n"):
        value = value[:-1]
    return value


def clean_parameter_value(value: str) -> str:
    """Recover a value from malformed output (nested duplicate calls).

    A model looping on tool calls can emit a whole call inside a parameter
    value. The real value is the text after the innermost parameter opener;
    any remaining tag fragments are stripped.
    """
    openers = list(PARAMETER_OPEN_RE.finditer(value))
    if openers:
        value = value[openers[-1].end() :]
    cleaned = TAG_FRAGMENT_RE.sub("", value)
    return _strip_wrapping_newlines(cleaned).strip()


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
                    args[key] = clean_parameter_value(param.group(2))
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


def _space_hold(buffer: str, limit: int = 4) -> int:
    """Hold back trailing whitespace so a dropped tag can swallow it."""
    hold = 0
    while hold < limit and hold < len(buffer) and buffer[-1 - hold].isspace():
        hold += 1
    return hold


def _partial_suffix_hold(buffer: str) -> int:
    """Length of a buffer suffix that could become one of the markers."""
    hold = 0
    for tag in _SCAN_TAGS:
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
        #: A stray closer was dropped; swallow line breaks until real text.
        self._swallow_newlines = False

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
                if self._swallow_newlines:
                    self._buffer = self._buffer.lstrip("\r\n")
                    if self._buffer and self._buffer[0] not in "\r\n":
                        self._swallow_newlines = False
                    if not self._buffer:
                        break
                index, tag = self._next_tag()
                if tag is None:
                    partial = _partial_suffix_hold(self._buffer)
                    if partial > 0:
                        # Hold the partial tag plus any whitespace before it,
                        # so a dropped tag can still swallow that whitespace.
                        hold = partial
                        while (
                            hold < len(self._buffer)
                            and self._buffer[-1 - hold].isspace()
                        ):
                            hold += 1
                    else:
                        hold = _space_hold(self._buffer)
                    cut = len(self._buffer) - hold
                    emitted.append(self._buffer[:cut])
                    self._buffer = self._buffer[cut:]
                    break
                if tag in _DROPPED_TAGS:
                    # A stray closer with no opener (malformed generation):
                    # swallow it (plus its leading spaces) so no tag text
                    # reaches the answer.
                    start = index
                    while start > 0 and self._buffer[start - 1].isspace():
                        start -= 1
                    self._buffer = self._buffer[:start] + self._buffer[index + len(tag) :]
                    self._swallow_newlines = True
                    continue
                if tag in _TOOL_OPENERS:
                    # Emit the text before the opener, then keep the opener in
                    # the buffer: block capture starts with it, and
                    # parse_tool_calls needs the `<function=` form.
                    emitted.append(self._buffer[:index])
                    self._buffer = self._buffer[index:]
                    self._mode = TOOL
                    continue
                # Remaining opener: `<think>`.
                emitted.append(self._buffer[:index])
                self._buffer = self._buffer[index + len(tag) :]
                self._mode = THINK
            elif self._mode == THINK:
                index = self._buffer.find(_CLOSE_THINK)
                if index < 0:
                    hold = _partial_suffix_hold(self._buffer)
                    cut = len(self._buffer) - hold
                    self._buffer = self._buffer[cut:]
                    break
                self._buffer = self._buffer[index + len(_CLOSE_THINK) :]
                self._mode = TEXT
            else:  # TOOL: capture through `</function>` (+ optional close)
                index = self._buffer.find(_FUNCTION_CLOSE)
                if index < 0:
                    if len(self._buffer) > MAX_TOOL_BUFFER:
                        # Malformed output: give up on this block, resume text.
                        self._buffer = ""
                        self._mode = TEXT
                    break
                end = index + len(_FUNCTION_CLOSE)
                self._blocks.append(self._buffer[:end])
                self._buffer = self._buffer[end:]
                self._mode = TEXT
        return "".join(emitted)

    def finish(self) -> tuple[str, list[str]]:
        """Flush: returns (trailing display text, collected tool blocks).

        An unterminated tool block is still parsed when it contains a
        function tag; otherwise it is discarded.
        """
        tail = ""
        if self._mode == TEXT:
            if self._blocks and self._buffer.isspace():
                tail = ""
            elif self._swallow_newlines:
                tail = self._buffer.lstrip("\r\n")
            else:
                tail = self._buffer
        elif self._mode == TOOL and "<function=" in self._buffer:
            self._blocks.append(self._buffer)
        self._buffer = ""
        self._mode = TEXT
        self._swallow_newlines = False
        return tail, list(self._blocks)

    def _next_tag(self) -> tuple[int, str | None]:
        best: tuple[int, str | None] = (len(self._buffer), None)
        for tag in _SCAN_TAGS:
            index = self._buffer.find(tag)
            if index >= 0 and index < best[0]:
                best = (index, tag)
        return best


def _normalize_tool_calls(
    tool_calls: list[Any],
) -> list[dict[str, Any]]:
    """Convert OpenAI tool calls to the shape the Qwen template renders.

    The template iterates ``tool_call.arguments | items``, so arguments must
    be a mapping, not the JSON string OpenAI transports.
    """
    normalized: list[dict[str, Any]] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        arguments = function.get("arguments")
        parsed: Any = {}
        if isinstance(arguments, dict):
            parsed = arguments
        elif isinstance(arguments, str):
            try:
                candidate = json.loads(arguments)
            except json.JSONDecodeError:
                candidate = None
            if isinstance(candidate, dict):
                parsed = candidate
        normalized.append(
            {"type": "function", "function": {"name": name, "arguments": parsed}}
        )
    return normalized


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
                normalized = _normalize_tool_calls(tool_calls)
                if normalized:
                    item["tool_calls"] = normalized
            if item["content"] or item.get("tool_calls"):
                converted.append(item)
        elif role == "tool":
            converted.append(
                {"role": "tool", "content": _content_text(message.get("content"))}
            )
    if system_parts:
        converted.insert(0, {"role": "system", "content": "\n\n".join(system_parts)})
    return converted
