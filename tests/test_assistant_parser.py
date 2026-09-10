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


# ---------- mutation triage: helpers and stream-filter boundaries ----------

from ocr_server.assistant_parser import (  # noqa: E402
    _content_text,
    _normalize_tool_calls,
    _partial_suffix_hold,
    _space_hold,
    _strip_wrapping_newlines,
    clean_parameter_value,
)


def test_strip_wrapping_newlines_exact():
    assert _strip_wrapping_newlines("\nx\n") == "x"
    assert _strip_wrapping_newlines("\nx") == "x"
    assert _strip_wrapping_newlines("x\n") == "x"
    assert _strip_wrapping_newlines("x") == "x"
    assert _strip_wrapping_newlines("\n") == ""
    assert _strip_wrapping_newlines("\n\n") == ""


def test_space_hold_exact():
    assert _space_hold("") == 0
    assert _space_hold("abc") == 0
    assert _space_hold("abc ") == 1
    assert _space_hold("a  ") == 2
    assert _space_hold("abc      ") == 4
    assert _space_hold("abc   ", limit=2) == 2


def test_partial_suffix_hold_exact():
    assert _partial_suffix_hold("") == 0
    assert _partial_suffix_hold("abc") == 0
    assert _partial_suffix_hold("<") == 1
    assert _partial_suffix_hold("</thin") == len("</thin")
    assert _partial_suffix_hold("x<tool_call") == len("<tool_call")
    assert _partial_suffix_hold("</think>") == 0


def test_clean_parameter_value_exact():
    assert clean_parameter_value("plain") == "plain"
    assert clean_parameter_value("\nplain\n") == "plain"
    assert clean_parameter_value("<parameter=query>café") == "café"
    assert clean_parameter_value("satellite<parameter=query>inner") == "inner"
    assert (
        clean_parameter_value("satellite<tool_call><function=x>inner")
        == "satelliteinner"
    )


def test_normalize_tool_calls_processes_all_and_shapes():
    calls = _normalize_tool_calls(
        [
            "not-a-call",
            {"function": None},
            {"function": {"name": "", "arguments": "{}"}},
            {"function": {"name": "a", "arguments": {"x": 1}}},
            {"function": {"name": "b", "arguments": "{bad"}},
            {"function": {"name": "c", "arguments": '{"y": "2"}'}},
        ]
    )
    assert [call["function"]["name"] for call in calls] == ["a", "b", "c"]
    for call in calls:
        assert call == {
            "type": "function",
            "function": {
                "name": call["function"]["name"],
                "arguments": call["function"]["arguments"],
            },
        }
    assert calls[0]["function"]["arguments"] == {"x": 1}
    assert calls[1]["function"]["arguments"] == {}
    assert calls[2]["function"]["arguments"] == {"y": "2"}


def test_content_text_joins_with_single_newline():
    assert _content_text([{"text": "a"}, {"text": "b"}]) == "a\nb"
    assert _content_text([{"other": 1}, "x", None]) == ""


def test_to_chat_messages_preserves_assistant_content():
    converted = to_chat_messages(
        [
            {"role": "assistant", "content": "calling now"},
            {"content": "no role at all"},
        ]
    )
    assert converted == [{"role": "assistant", "content": "calling now"}]


def test_parse_tool_calls_keeps_unicode_verbatim():
    block = "<function=search>\n<parameter=query>\ncafé\n</parameter>\n</function>"
    call = parse_tool_calls([block])[0]
    assert "café" in call["function"]["arguments"]


def test_filter_initial_state_flags():
    flt = QwenStreamFilter()
    assert flt._swallow_newlines is False
    tail, blocks = flt.finish()
    assert (tail, blocks) == ("", [])


def test_filter_swallows_leading_spaces_before_stray_closer():
    flt = QwenStreamFilter()
    emitted = flt.feed("alpha   </parameter>")
    assert emitted == "alpha"


def test_filter_stops_swallowing_after_real_text():
    flt = QwenStreamFilter()
    emitted = flt.feed("</tool_call>")
    emitted += flt.feed("\n\nXtail")
    assert emitted == "Xtail"


def test_filter_keeps_runs_longer_than_hold_limit():
    flt = QwenStreamFilter()
    assert flt.feed("abc      ") == "abc  "
    tail, _blocks = flt.finish()
    assert tail == "    "


def test_filter_picks_the_earliest_tag_not_the_last():
    flt = QwenStreamFilter()
    emitted = flt.feed("hello <parameter=a>1<parameter=b>2")
    assert emitted == "hello "
    tail, _blocks = flt.finish()
    assert tail == ""


def test_filter_captures_each_function_separately():
    flt = QwenStreamFilter()
    emitted = flt.feed(
        "<tool_call><function=a></function></tool_call>"
        "<tool_call><function=b></function></tool_call>"
    )
    tail, blocks = flt.finish()
    assert emitted == "" and tail == ""
    assert len(blocks) == 2
    assert [parse_tool_calls(blocks)[0]["function"]["name"], parse_tool_calls(blocks)[1]["function"]["name"]] == ["a", "b"]


def test_filter_drops_second_think_block_too():
    flt = QwenStreamFilter()
    emitted = flt.feed("<think>one</think>a<think>two</think>b")
    assert emitted == "ab"


def test_filter_tool_buffer_boundary_is_strict():
    from ocr_server.assistant_parser import MAX_TOOL_BUFFER

    flt = QwenStreamFilter()
    flt.feed("<tool_call>" + "x" * (MAX_TOOL_BUFFER - len("<tool_call>")))
    assert flt.mode == "tool"
    emitted = flt.feed("more")
    assert flt.mode == "text"
    assert emitted == ""


def test_filter_finish_text_tail_prefers_buffer_over_flag():
    flt = QwenStreamFilter()
    flt.feed("<tool_call><function=a></function>")
    emitted = flt.feed("</tool_call>")  # sets swallow flag
    emitted += flt.feed("\nX")
    tail, _blocks = flt.finish()
    assert emitted + tail == "X"


def test_filter_finish_tool_block_without_function_is_dropped():
    flt = QwenStreamFilter()
    flt.feed("<tool_call>")
    tail, blocks = flt.finish()
    assert tail == "" and blocks == []


def test_filter_exact_output_matrix():
    cases = [
        ("plain text", "plain text", []),
        ("a<think>x</think>b", "ab", []),
        ("a</parameter>b", "ab", []),
        ("a</function>b", "ab", []),
        ("a</tool_call>b", "ab", []),
        ("a</think>b", "ab", []),
        (
            "<tool_call><function=s><parameter=q>v</parameter></function>"
            "</tool_call>",
            "",
            ["s"],
        ),
        ("x<function=s><parameter=q>v</parameter></function>y", "xy", ["s"]),
        # Premature close with no function close: unparseable, dropped.
        (
            "<tool_call><function=s><parameter=q>v</tool_call>w",
            "",
            [],
        ),
    ]
    for raw, expected_display, expected_tools in cases:
        flt = QwenStreamFilter()
        displayed = flt.feed(raw)
        tail, blocks = flt.finish()
        displayed += tail
        assert displayed == expected_display, raw
        assert [
            call["function"]["name"] for call in parse_tool_calls(blocks)
        ] == expected_tools, raw
        # Chunk-invariance: every two-way split must agree exactly.
        for split in range(len(raw) + 1):
            split_flt = QwenStreamFilter()
            split_text = split_flt.feed(raw[:split]) + split_flt.feed(raw[split:])
            split_tail, split_blocks = split_flt.finish()
            split_text += split_tail
            assert split_text == expected_display, (raw, split)
            assert [
                call["function"]["name"]
                for call in parse_tool_calls(split_blocks)
            ] == expected_tools, (raw, split)


def test_filter_swallow_flag_survives_until_real_text():
    flt = QwenStreamFilter()
    flt.feed("</tool_call>")
    assert flt.feed("X") == "X"
    assert flt.feed("\n\ntail") == "\n\ntail"


def test_filter_swallow_strips_newline_but_not_other_letters():
    flt = QwenStreamFilter()
    flt.feed("</tool_call>")
    assert flt.feed("\nX") == "X"


def test_filter_swallows_all_leading_spaces_before_closer():
    flt = QwenStreamFilter()
    assert flt.feed("  </parameter>") == ""
    assert flt.feed("a   </parameter>") == "a"


def test_filter_finish_lstrip_branch_is_total_on_empty_buffer():
    flt = QwenStreamFilter()
    flt.feed("</tool_call>")
    tail, blocks = flt.finish()
    assert (tail, blocks) == ("", [])


def test_finish_tool_state_conditions_whitebox():
    flt = QwenStreamFilter()
    flt._mode = "tool"
    flt._buffer = "<function=x>"
    tail, blocks = flt.finish()
    assert tail == ""
    assert blocks == ["<function=x>"]
    assert flt._buffer == ""
    assert flt._mode == "text"
    assert flt._swallow_newlines is False

    other = QwenStreamFilter()
    other._mode = "tool"
    other._buffer = "no function here"
    tail2, blocks2 = other.finish()
    assert tail2 == "" and blocks2 == []

    plain = QwenStreamFilter()
    plain._buffer = "visible"
    tail3, blocks3 = plain.finish()
    assert tail3 == "visible" and blocks3 == []


def test_finish_swallow_branch_whitebox():
    flt = QwenStreamFilter()
    flt._swallow_newlines = True
    flt._buffer = " X"
    tail, blocks = flt.finish()
    assert tail == " X"
    assert blocks == []
    assert flt._swallow_newlines is False
