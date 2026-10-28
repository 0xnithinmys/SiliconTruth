"""Provider contract tests, written against the Meta Model API's real behaviour.

The shapes asserted here are not invented: they are copied from live
responses captured in docs/api-smoke/. The important one is that
muse-spark-1.3 is a REASONING model, so `content` is null and
finish_reason is "length" whenever max_tokens runs out during the
internal pass. Measured on 2026-10-28: 208 reasoning tokens to answer
"OK", 385 for a three-field JSON object.

That makes truncation an ordinary operating condition rather than an
edge case, and it must surface as Truncated -- never as None leaking out
of a `-> str` function, and never as a TypeError from json.loads(None).
"""

from __future__ import annotations

import json

import httpx
import pytest

from silicontruth.models.provider import (
    OpenAICompatProvider,
    ProviderError,
    Truncated,
)


def make_provider(handler) -> OpenAICompatProvider:
    p = OpenAICompatProvider(
        name="test",
        base_url="https://example.invalid/v1",
        api_key="not-a-real-key",
        text_model="muse-spark-1.3",
        vision_model="muse-spark-1.3",
    )
    p._client = httpx.Client(
        base_url="https://example.invalid/v1",
        transport=httpx.MockTransport(handler),
    )
    return p


def json_response(body: dict, status: int = 200):
    return lambda _req: httpx.Response(status, json=body)


def completion(content, *, finish="stop", reasoning=0) -> dict:
    return {
        "choices": [
            {
                "finish_reason": finish,
                "index": 0,
                "message": {"content": content, "refusal": None, "role": "assistant"},
            }
        ],
        "usage": {"completion_tokens_details": {"reasoning_tokens": reasoning}},
    }


# --- the truncation shape, verbatim from the live API ----------------------

TRUNCATED = completion(None, finish="length", reasoning=14)


def test_complete_raises_truncated_rather_than_returning_none():
    p = make_provider(json_response(TRUNCATED))
    with pytest.raises(Truncated) as e:
        p.complete("Reply with exactly: OK", max_tokens=16)
    assert "finish_reason=length" in str(e.value)
    assert "reasoning_tokens=14" in str(e.value)


def test_complete_never_returns_a_non_string():
    """The regression this guards: `-> str` returning None, which then
    blows up in whichever caller later does .strip()."""
    p = make_provider(json_response(TRUNCATED))
    try:
        got = p.complete("x")
    except Truncated:
        return
    pytest.fail(f"returned {got!r} instead of raising")


def test_extract_raises_truncated_not_typeerror():
    """json.loads(None) is a TypeError, which `except json.JSONDecodeError`
    does not catch -- so this used to crash unhandled."""
    p = make_provider(json_response(TRUNCATED))
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    with pytest.raises(Truncated):
        p.extract("extract the table", schema=schema)


def test_truncated_is_a_provider_error():
    """Callers that only know about ProviderError must still catch it."""
    assert issubclass(Truncated, ProviderError)


# --- the success shapes ----------------------------------------------------


def test_complete_returns_visible_text():
    p = make_provider(json_response(completion("OK", reasoning=208)))
    assert p.complete("Reply with exactly: OK") == "OK"


def test_extract_parses_strict_json_schema_output():
    body = completion(json.dumps({"name": "UE", "lsb": 0, "msb": 0}), reasoning=385)
    p = make_provider(json_response(body))
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "lsb": {"type": "integer"},
            "msb": {"type": "integer"},
        },
        "required": ["name", "lsb", "msb"],
        "additionalProperties": False,
    }
    assert p.extract("row: UE, bit 0", schema=schema) == {
        "name": "UE",
        "lsb": 0,
        "msb": 0,
    }


def test_extract_rejects_non_json_text():
    """A model that ignores the schema must not be mistaken for success."""
    p = make_provider(json_response(completion("I think the answer is UE.")))
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    with pytest.raises(ProviderError) as e:
        p.extract("x", schema=schema)
    assert "not valid JSON" in str(e.value)


def test_extract_sends_strict_schema_and_the_image():
    """Guards the request shape: strict must be on, or the model is free to
    return prose that happens to look like JSON."""
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        return httpx.Response(200, json=completion(json.dumps({"ok": True})))

    p = make_provider(handler)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    p.extract("read this crop", schema=schema, images=["data:image/png;base64,AAAA"])

    assert seen["response_format"]["json_schema"]["strict"] is True
    assert seen["response_format"]["json_schema"]["schema"] == schema
    parts = seen["messages"][0]["content"]
    assert [x["type"] for x in parts] == ["text", "image_url"]


# --- error surfaces -------------------------------------------------------


def test_billing_block_is_its_own_error():
    from silicontruth.models.provider import BillingBlocked

    p = make_provider(lambda _r: httpx.Response(402, text="billing_not_configured"))
    with pytest.raises(BillingBlocked):
        p.complete("x")


def test_no_api_key_fails_at_construction():
    with pytest.raises(ProviderError):
        OpenAICompatProvider(
            name="test", base_url="https://x.invalid", api_key="", text_model="m"
        )
