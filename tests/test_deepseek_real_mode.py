"""DeepSeek wire contract: SDK compatibility, schema retry, tools and billing.

No paid requests. The final tests run the actual SDK against mocked SSE over HTTP.
"""
import json
from types import SimpleNamespace as NS

import anthropic
import httpx
import pytest
import respx

from backend.app.schemas import ParsedPosting
from backend.app.services import deepseek as module
from backend.app.services.deepseek import (BASE_URL, MODEL_ID, DeepSeekError,
    DeepSeekService, compute_cost, strict_schema)

POSTING = {"title": "Engineer", "company": "Example"}


def block(kind="text", **kwargs):
    return NS(type=kind, **kwargs)


def message(text=None, reason="end_turn", blocks=None, inp=10, out=5, cache=0, searches=0):
    return NS(stop_reason=reason, content=blocks if blocks is not None else [block(text=text if text is not None else json.dumps(POSTING))],
        usage=NS(input_tokens=inp, output_tokens=out, cache_read_input_tokens=cache,
                 server_tool_use=NS(web_search_requests=searches, tool_search=searches)))


class Stream:
    def __init__(self, value): self.value = value
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def __iter__(self): yield NS(type="message_stop")
    def get_final_message(self): return self.value


class Messages:
    def __init__(self, values): self.values, self.calls = list(values), []
    def stream(self, **kwargs):
        self.calls.append(kwargs)
        value = self.values.pop(0)
        if isinstance(value, Exception): raise value
        return Stream(value)


def service(values):
    result = DeepSeekService(api_key="deepseek-test-key")
    stub = Messages(values)
    result._client = NS(messages=stub)
    return result, stub


def generate(client, **kwargs):
    return client.structured(task="parse_posting", system="Extract source facts.",
        user_content="Job posting", schema_model=ParsedPosting, **kwargs)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(module, "TRANSIENT_RETRY_BACKOFF_SECONDS", 0)


def error(status):
    response = httpx.Response(status, request=httpx.Request("POST", BASE_URL + "/v1/messages"))
    return anthropic.APIStatusError("secret request body", response=response, body={})


def test_deepseek_request_has_prompt_schema_not_ignored_output_format():
    client, stub = service([message()])
    result, usage = generate(client)
    request = stub.calls[0]
    assert result.company == "Example"
    assert request["model"] == MODEL_ID == "deepseek-flash"
    assert request["thinking"] == {"type": "enabled"}
    assert request["output_config"] == {"effort": "low"}
    assert json.dumps(strict_schema(ParsedPosting)) in request["system"]
    assert usage.cost_usd == compute_cost(10, 5)


@pytest.mark.parametrize("task, effort", [("outreach_drafts", "low"), ("tailor", "high"), ("intake", "high")])
def test_effort_fits_short_drafts_and_substantive_authoring(task, effort):
    client, stub = service([message()])
    client.structured(task=task, system="Source facts only", user_content="Posting", schema_model=ParsedPosting)
    assert stub.calls[0]["output_config"] == {"effort": effort}


def test_deepseek_credentials_and_fixed_host_ignore_old_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "wrong-provider-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "wrong-provider-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://wrong.example")
    client = DeepSeekService(api_key="deepseek-test-key")._get_client()
    try:
        assert str(client.base_url).rstrip("/") == BASE_URL
        assert client.api_key == "deepseek-test-key"
        assert client.auth_token == "deepseek-test-key"
    finally:
        client.close()


def test_missing_key_is_actionable_without_using_anthropic_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-deepseek-key")
    with pytest.raises(DeepSeekError, match="DEEPSEEK_API_KEY"):
        generate(DeepSeekService())


def test_native_search_and_client_fetch_are_declared_without_unsupported_server_fetch():
    client, stub = service([message()])
    generate(client, tools=[{"name": "web_search", "type": "web_search_20260209", "max_uses": 8},
                            {"name": "web_fetch", "type": "web_fetch_20260209", "max_uses": 8}])
    search, fetch = stub.calls[0]["tools"]
    assert search == {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
    assert "type" not in fetch
    assert fetch["input_schema"]["required"] == ["url"]
    assert stub.calls[0]["output_config"] == {"effort": "low"}


def test_tool_results_preserve_thinking_and_every_call_id(monkeypatch):
    thinking = block("thinking", thinking="internal", signature="preserve-me")
    first = message(reason="tool_use", blocks=[thinking,
        block("tool_use", id="a", name="web_fetch", input={"url": "https://example.com/about"}),
        block("tool_use", id="b", name="web_fetch", input={"url": "https://example.com/team"})], searches=1, cache=4)
    client, stub = service([first, message(inp=20, out=6, cache=3)])
    fetched = []
    def fetch(url, domains): fetched.append((url, domains)); return "source text"
    monkeypatch.setattr(client, "_web_fetch", fetch)
    _, usage = generate(client, tools=[{"name": "web_fetch", "max_uses": 2, "allowed_domains": ["example.com"]}])
    replay = stub.calls[1]["messages"]
    assert replay[1]["content"] is first.content
    assert [r["tool_use_id"] for r in replay[2]["content"]] == ["a", "b"]
    assert fetched[0][1] == ["example.com"]
    assert usage.input_tokens == 37
    assert usage.output_tokens == 11
    assert usage.cost_usd == compute_cost(37, 11, 7, 1)


def test_fetch_budget_does_not_reset_between_turns(monkeypatch):
    calls = [message(reason="tool_use", blocks=[block("tool_use", id=str(i), name="web_fetch", input={"url": "https://example.com"})]) for i in range(2)]
    client, stub = service(calls + [message()])
    fetched = []
    monkeypatch.setattr(client, "_web_fetch", lambda *args: fetched.append(args) or "ok")
    generate(client, tools=[{"name": "web_fetch", "max_uses": 1}])
    assert len(fetched) == 1
    assert "budget exhausted" in stub.calls[2]["messages"][-1]["content"][0]["content"]


def test_fetch_uses_bounded_public_retrieval_and_domain_policy(monkeypatch):
    fetched = []
    def fetch(url, allowed_domains=None):
        fetched.append((url, allowed_domains))
        return '<p>Company facts</p><a href="/team">Team</a>'
    monkeypatch.setattr(module, "public_page", fetch)
    result = json.loads(DeepSeekService._web_fetch("https://example.com", ["example.com"]))
    assert fetched == [("https://example.com", ["example.com"])]
    assert "Company facts" in result["content"]
    assert result["links"] == ["https://example.com/team"]


def test_fetch_keeps_personal_linkedin_after_long_navigation(monkeypatch):
    page = "".join(f'<a href="/nav/{i}">Menu</a>' for i in range(120))
    page += '<p>Casey Smith, Engineering Manager</p><a href="https://www.linkedin.com/in/casey-smith/">Casey</a>'
    monkeypatch.setattr(module, "public_page", lambda *args, **kwargs: page)
    result = json.loads(DeepSeekService._web_fetch("https://example.com/team", None))
    assert result["links"][0] == "https://www.linkedin.com/in/casey-smith/"
    assert len(result["links"]) == 100


def test_json_retry_is_bounded_and_usage_includes_both_requests():
    client, stub = service([message("not JSON"), message()])
    _, usage = generate(client)
    assert len(stub.calls) == 2
    assert "corrected JSON" in stub.calls[1]["messages"][-1]["content"]
    assert usage.input_tokens == 20
    assert usage.cost_usd == compute_cost(20, 10)
    client, stub = service([message("not JSON"), message("still invalid")])
    with pytest.raises(DeepSeekError, match="JSON twice"):
        generate(client)
    assert len(stub.calls) == 2


def test_fenced_json_is_validated():
    client, _ = service([message("```json\n" + json.dumps(POSTING) + "\n```")])
    assert generate(client)[0].company == "Example"


@pytest.mark.parametrize("reason", ["refusal", "max_tokens"])
def test_terminal_failure_is_not_retried_as_json(reason):
    client, stub = service([message(reason=reason)])
    with pytest.raises(DeepSeekError): generate(client)
    assert len(stub.calls) == 1


@pytest.mark.parametrize("status, attempts", [(401, 1), (402, 1), (400, 1), (429, 3), (500, 3), (200, 3)])
def test_provider_errors_have_bounded_retries_and_no_secret_payload(status, attempts):
    client, stub = service([error(status)] * attempts)
    with pytest.raises(DeepSeekError) as exc:
        generate(client)
    assert len(stub.calls) == attempts
    assert "secret request body" not in str(exc.value)
    assert "DeepSeek" in str(exc.value)


def test_transient_failure_can_recover():
    client, stub = service([error(500), message()])
    assert generate(client)[0].company == "Example"
    assert len(stub.calls) == 2


def test_continuation_limit_is_finite():
    client, stub = service([message(reason="pause_turn")] * 9)
    with pytest.raises(DeepSeekError, match="continuation limit"):
        generate(client)
    assert len(stub.calls) == 9


def sse_response(complete=True):
    events = [
        {"type": "message_start", "message": {"id": "test", "type": "message", "role": "assistant", "model": MODEL_ID,
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 4, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": json.dumps(POSTING)}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
         "usage": {"output_tokens": 5, "server_tool_use": {"web_search_requests": 1, "tool_search": 1}}},
    ]
    if complete: events.append({"type": "message_stop"})
    return "".join("event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n" for e in events)


def test_actual_sdk_sse_uses_only_deepseek_host_key_and_counts_custom_usage(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "wrong-token")
    client = DeepSeekService(api_key="deepseek-test-key")
    try:
        with respx.mock as router:
            route = router.post(BASE_URL + "/v1/messages").respond(200, text=sse_response(), headers={"content-type": "text/event-stream"})
            parsed, usage = generate(client)
            assert parsed.company == "Example"
            request = route.calls.last.request
            assert request.headers["x-api-key"] == "deepseek-test-key"
            assert request.headers["authorization"] == "Bearer deepseek-test-key"
            assert usage.input_tokens == 14
            assert usage.cost_usd == compute_cost(14, 5, 4, 1)
    finally:
        client._client.close()


def test_interrupted_stream_without_message_stop_is_retried_not_accepted():
    client = DeepSeekService(api_key="deepseek-test-key")
    try:
        with respx.mock as router:
            route = router.post(BASE_URL + "/v1/messages").respond(200, text=sse_response(False), headers={"content-type": "text/event-stream"})
            with pytest.raises(DeepSeekError, match="connection failed"):
                generate(client)
            assert route.call_count == 3
    finally:
        client._client.close()
