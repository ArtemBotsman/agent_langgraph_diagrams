"""Lossless text/usage assembly for completed provider SSE responses."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any


def events(raw: bytes) -> Iterator[Any]:
    for line in raw.decode("utf-8").splitlines():
        if line.startswith("data: "):
            text = line[6:]
            yield text if text == "[DONE]" else json.loads(text)


def openai_response(raw: bytes) -> dict[str, Any]:
    content = []
    reasoning = []
    result: dict[str, Any] = {}
    usage = None
    finish = None
    done = False
    for event in events(raw):
        if event == "[DONE]":
            done = True
            continue
        if "error" in event:
            raise ValueError("Provider stream error")
        result.update(
            {k: event[k] for k in ("id", "model", "created", "system_fingerprint") if k in event}
        )
        if event.get("usage"):
            usage = event["usage"]
        for choice in event.get("choices", []):
            if choice.get("index", 0) != 0:
                raise ValueError("Unexpected stream choice")
            delta = choice.get("delta", {})
            if delta.get("tool_calls"):
                raise ValueError("Unexpected tool call in text generator")
            content.append(delta.get("content") or "")
            reasoning.append(delta.get("reasoning_content") or "")
            finish = choice.get("finish_reason") or finish
    if not done or finish is None:
        raise ValueError("Incomplete OpenAI stream")
    result.update(
        usage=usage,
        choices=[
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "".join(content),
                    "reasoning_content": "".join(reasoning),
                },
                "finish_reason": finish,
            }
        ],
    )
    return result


def anthropic_response(raw: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {}
    texts: dict[int, str] = {}
    done = False
    for event in events(raw):
        kind = event.get("type")
        if kind == "error":
            raise ValueError("Provider stream error")
        if kind == "message_start":
            result = event["message"]
        elif kind == "content_block_start" and event["content_block"]["type"] == "text":
            texts[event["index"]] = event["content_block"].get("text", "")
        elif kind == "content_block_delta" and event["delta"]["type"] == "text_delta":
            index = event["index"]
            texts[index] = texts.get(index, "") + event["delta"]["text"]
        elif kind == "message_delta":
            result.update(event.get("delta", {}))
            result.setdefault("usage", {}).update(event.get("usage", {}))
        elif kind == "message_stop":
            done = True
    if not done or not result.get("stop_reason"):
        raise ValueError("Incomplete Anthropic stream")
    result["content"] = [{"type": "text", "text": texts[i]} for i in sorted(texts)]
    return result
