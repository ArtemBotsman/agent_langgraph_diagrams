import json

import pytest

from traceable_spec.llm.streaming import anthropic_response, openai_response


def sse(events):
    return "".join(
        "data: " + (e if isinstance(e, str) else json.dumps(e)) + "\n\n" for e in events
    ).encode()


def test_openai_assembles_text_and_final_usage():
    events = [
        {
            "model": "gpt",
            "choices": [{"index": 0, "delta": {"content": '{"ok":'}, "finish_reason": None}],
        },
        {
            "model": "gpt",
            "choices": [{"index": 0, "delta": {"content": "true}"}, "finish_reason": "stop"}],
        },
        {"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}},
        "[DONE]",
    ]
    result = openai_response(sse(events))
    assert result["choices"][0]["message"]["content"] == '{"ok":true}'
    assert result["usage"]["total_tokens"] == 5
    assert result["model"] == "gpt"
    with pytest.raises(ValueError, match="Incomplete"):
        openai_response(sse(events[:-1]))


def test_openai_truncation_is_preserved():
    result = openai_response(
        sse([{"choices": [{"delta": {"content": "partial"}, "finish_reason": "length"}]}, "[DONE]"])
    )
    assert result["choices"][0]["finish_reason"] == "length"
    assert result["usage"] is None


def test_anthropic_preserves_cache_usage_and_stop():
    events = [
        {
            "type": "message_start",
            "message": {
                "model": "claude",
                "usage": {"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 20},
            },
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "{}"}},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]
    result = anthropic_response(sse(events))
    assert result["usage"] == {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_read_input_tokens": 20,
    }
    assert result["content"] == [{"type": "text", "text": "{}"}]
    with pytest.raises(ValueError, match="Incomplete"):
        anthropic_response(sse(events[:-1]))
