"""Assistant parser: XML tool-call extraction, stream filtering, conversion."""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ocr_server.assistant_parser import (
    QwenStreamFilter,
    parse_tool_calls,
    to_chat_messages,
)

TOOL_BLOCK = (
    "\n<function=search>\n"
    "<parameter=query>\ncentromere evolution\n</parameter>\n"
    "<parameter=limit>\n5\n</parameter>\n"
    "</function>\n"
)


def test_parse_tool_calls_canonical():
    calls = parse_tool_calls([TOOL_BLOCK])
    assert len(calls) == 1
    call = calls[0]
    assert call["id"] == "call_1"
    assert call["type"] == "function"
    assert call["function"]["name"] == "search"
    assert json.loads(call["function"]["arguments"]) == {
        "query": "centromere evolution",
        "limit": "5",
    }


def test_parse_tool_calls_multiple_blocks_and_calls():
    block = TOOL_BLOCK + "<function=outline>\n</function>\n"
    calls = parse_tool_calls([block, TOOL_BLOCK])
    assert [c["function"]["name"] for c in calls] == [
        "search",
        "outline",
        "search",
    ]
    assert [c["id"] for c in calls] == ["call_1", "call_2", "call_3"]


def test_parse_tool_calls_keeps_inner_newlines():
    block = "<function=read>\n<parameter=queries>\nline one\nline two\n</parameter>\n</function>"
    args = json.loads(parse_tool_calls([block])[0]["function"]["arguments"])
    assert args["queries"] == "line one\nline two"


def test_filter_drops_stray_closers_and_whitespace():
    flt = QwenStreamFilter()
    emitted = flt.feed("answer arrays")
    emitted += flt.feed("</parameter>\n</function>\n")
    emitted += flt.feed("</tool_call> tail")
    tail, blocks = flt.finish()
    assert emitted + tail == "answer arrays tail"
    assert blocks == []


def test_filter_captures_orphan_function_block():
    flt = QwenStreamFilter()
    emitted = flt.feed(
        "before <function=search><parameter=query>satellite"
        "</parameter></function> after"
    )
    tail, blocks = flt.finish()
    assert emitted + tail == "before  after"
    calls = parse_tool_calls(blocks)
    assert calls[0]["function"]["name"] == "search"
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "query": "satellite"
    }


def test_filter_absorbs_tool_call_close_and_newline():
    flt = QwenStreamFilter()
    emitted = flt.feed(
        "<tool_call>\n<function=search>\n<parameter=query>x\n</parameter>\n"
        "</function>\n</tool_call>\nanswer"
    )
    tail, blocks = flt.finish()
    assert emitted + tail == "answer"
    assert len(blocks) == 1


def test_parse_tool_calls_cleans_nested_fragments():
    block = (
        "<function=search><parameter=query>satellite<tool_call><function=search>"
        "<parameter=query>satellite</parameter></function>"
    )
    calls = parse_tool_calls([block])
    arguments = json.loads(calls[0]["function"]["arguments"])
    assert "<" not in arguments["query"]
    assert "satellite" in arguments["query"]


def test_parse_tool_calls_recovers_nested_duplicate_call():
    block = (
        "<function=search>\n<parameter=query>\n"
        "satellite<tool_call>\n<function=search>\n<parameter=query>\n"
        "satellite\n</parameter>\n</function>"
    )
    calls = parse_tool_calls([block])
    arguments = json.loads(calls[0]["function"]["arguments"])
    assert arguments["query"] == "satellite"


def test_parse_tool_calls_ignores_malformed():
    assert parse_tool_calls(["", "no function here", "<function=>\n</function>"]) == []


def test_filter_strips_thinking_and_withholds_tool_blocks():
    flt = QwenStreamFilter()
    emitted = flt.feed("<think>secret reasoning</think>Visible answer")
    assert emitted == "Visible answer"
    emitted += flt.feed("<tool_call>")
    emitted += flt.feed(TOOL_BLOCK)
    emitted += flt.feed("</tool_call>")
    emitted += flt.feed(" after")
    tail, blocks = flt.finish()
    emitted += tail
    assert emitted == "Visible answer after"
    assert len(blocks) == 1
    assert "search" in blocks[0]


def test_filter_handles_tags_split_across_feeds():
    whole = "<think>hidden</think>Hello <tool_call>" + TOOL_BLOCK + "</tool_call> world"
    reference = QwenStreamFilter()
    ref_text = reference.feed(whole)
    tail, blocks = reference.finish()
    ref_text += tail

    for split in range(len(whole) + 1):
        flt = QwenStreamFilter()
        text = flt.feed(whole[:split]) + flt.feed(whole[split:])
        end, blocks_split = flt.finish()
        text += end
        assert text == ref_text
        assert blocks_split == blocks
    assert ref_text == "Hello  world"
    assert len(blocks) == 1


def test_filter_unterminated_tool_block_is_parsed():
    flt = QwenStreamFilter()
    flt.feed("<tool_call>" + TOOL_BLOCK)
    tail, blocks = flt.finish()
    assert tail == ""
    assert "function=search" in blocks[0]


def test_filter_unterminated_think_is_dropped():
    flt = QwenStreamFilter()
    assert flt.feed("<think>never finished") == ""
    tail, blocks = flt.finish()
    assert tail == ""
    assert blocks == []


@given(st.text(max_size=2000))
@settings(max_examples=100, deadline=None)
def test_filter_never_raises_and_keeps_markers_out(text: str):
    flt = QwenStreamFilter()
    emitted = flt.feed(text)
    tail, _blocks = flt.finish()
    emitted += tail
    assert "<tool_call>" not in emitted
    assert "<think>" not in emitted


@given(st.text(max_size=500), st.integers(min_value=0, max_value=500))
@settings(max_examples=60, deadline=None)
def test_filter_chunking_is_equivalent(text: str, split: int):
    cut = min(split, len(text))
    one = QwenStreamFilter()
    expected = one.feed(text)
    expected_tail, expected_blocks = one.finish()
    expected += expected_tail

    two = QwenStreamFilter()
    actual = two.feed(text[:cut]) + two.feed(text[cut:])
    actual_tail, actual_blocks = two.finish()
    actual += actual_tail
    assert actual == expected
    assert actual_blocks == expected_blocks


def test_to_chat_messages_merges_system_and_flattens_parts():
    messages = [
        {"role": "system", "content": "one"},
        {"role": "system", "content": [{"type": "text", "text": "two"}]},
        {"role": "user", "content": [{"type": "text", "text": "ask"}]},
        {"role": "assistant", "content": ""},
        {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "content": "result", "tool_call_id": "call_1"},
    ]
    converted = to_chat_messages(messages)
    assert converted[0] == {"role": "system", "content": "one\n\ntwo"}
    assert converted[1] == {"role": "user", "content": "ask"}
    assert converted[2]["role"] == "assistant"
    assert converted[2]["tool_calls"][0]["function"]["name"] == "search"
    # The Qwen template iterates arguments as a mapping, not a JSON string.
    assert converted[2]["tool_calls"][0]["function"]["arguments"] == {}
    assert converted[3] == {"role": "tool", "content": "result"}
    # The empty assistant message is dropped.
    assert len(converted) == 4


def test_to_chat_messages_parses_arguments_and_drops_junk():
    converted = to_chat_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "read",
                            "arguments": '{"pages": "2"}',
                        },
                    },
                    {"function": {"name": "bad", "arguments": "{not json"}},
                    "not-a-call",
                ],
            }
        ]
    )
    calls = converted[0]["tool_calls"]
    assert calls[0]["function"]["arguments"] == {"pages": "2"}
    assert calls[1]["function"]["arguments"] == {}


def test_to_chat_messages_ignores_images():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
            ],
        }
    ]
    assert to_chat_messages(messages) == [{"role": "user", "content": "look"}]


def test_filter_exposes_mode_and_blocks():
    flt = QwenStreamFilter()
    assert flt.mode == "text"
    flt.feed("<think>")
    assert flt.mode == "think"
    flt.feed("</think>")
    flt.feed("<tool_call><function=search>")
    assert flt.mode == "tool"
    assert flt.blocks == []
    flt.feed("</function></tool_call>")
    assert flt.mode == "text"
    assert len(flt.blocks) == 1


def test_filter_abandons_oversized_tool_block():
    flt = QwenStreamFilter()
    flt.feed("<tool_call>" + "x" * (70 * 1024))
    assert flt.mode == "text"
    emitted = flt.feed("recovered")
    assert emitted == "recovered"


def test_content_text_handles_other_types():
    messages = [{"role": "user", "content": None}]
    assert to_chat_messages(messages) == [{"role": "user", "content": ""}]
