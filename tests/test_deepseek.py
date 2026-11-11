"""Tests for backend/app/services/deepseek.py."""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from backend.app.schemas import (
    ParsedPosting,
    ResearchFindings,
    ResumeDoc,
    TailorResult,
    UsageInfo,
)
from backend.app.services.deepseek import (
    COST_INPUT_PER_MTOK,
    COST_OUTPUT_PER_MTOK,
    DeepSeekError,
    compute_cost,
    make_deepseek,
    strict_schema,
)


class _Inner(BaseModel):
    value: str


class _Outer(BaseModel):
    name: str
    inner: _Inner
    rows: list[_Inner]


def _assert_all_object_nodes_strict(node) -> None:
    """Recursively assert every JSON-schema object node has additionalProperties=False."""
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            assert node.get("additionalProperties") is False, (
                f"object node missing additionalProperties=False: {node}"
            )
        for value in node.values():
            _assert_all_object_nodes_strict(value)
    elif isinstance(node, list):
        for item in node:
            _assert_all_object_nodes_strict(item)


def test_cost_constants():
    assert COST_INPUT_PER_MTOK == 0.3
    assert COST_OUTPUT_PER_MTOK == 1.2


def test_compute_cost_exact():
    assert compute_cost(0, 0) == 0.0
    assert compute_cost(1_000_000, 0) == 0.3
    assert compute_cost(0, 1_000_000) == 1.2
    assert compute_cost(123_456, 78_900) == 0.131717
    assert compute_cost(1_000_000, 0, 1_000_000, 2) == 0.0075


def test_compute_cost_rounds_six_decimals():
    assert compute_cost(7, 3) == 0.000006
    assert compute_cost(2, 0) == 0.000001


def test_strict_schema_marks_top_level_nested_and_defs():
    schema = strict_schema(_Outer)
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["_Inner"]["additionalProperties"] is False
    _assert_all_object_nodes_strict(schema)


def test_strict_schema_on_resumedoc_covers_all_defs():
    schema = strict_schema(ResumeDoc)
    assert schema["additionalProperties"] is False
    for def_schema in schema["$defs"].values():
        _assert_all_object_nodes_strict(def_schema)
    _assert_all_object_nodes_strict(schema)


def test_fake_mode_returns_validated_model_and_zero_usage(deepseek_fake):
    parsed, usage = deepseek_fake.structured(
        task="parse_posting",
        system="You parse postings.",
        user_content="raw posting text here",
        schema_model=ParsedPosting,
    )
    assert isinstance(parsed, ParsedPosting)
    assert parsed.title == "Senior Backend Engineer"
    assert parsed.company == "Northwind Labs"
    assert parsed.company_domain == "northwindlabs.com"
    assert usage == UsageInfo(input_tokens=0, output_tokens=0, cost_usd=0.0)


def test_fake_mode_records_calls(deepseek_fake):
    tools = [{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8}]
    deepseek_fake.structured(
        task="research_standard",
        system="Research the company.",
        user_content="ParsedPosting JSON here",
        schema_model=ResearchFindings,
        tools=tools,
    )
    assert len(deepseek_fake.calls) == 1
    assert deepseek_fake.calls[0] == {
        "task": "research_standard",
        "system": "Research the company.",
        "user_content": "ParsedPosting JSON here",
        "tools": tools,
        "schema_model_name": "ResearchFindings",
    }


def test_fake_mode_all_fixtures_validate(deepseek_fake):
    standard, _ = deepseek_fake.structured(
        task="research_standard", system="s", user_content="u",
        schema_model=ResearchFindings,
    )
    deep, _ = deepseek_fake.structured(
        task="research_deep", system="s", user_content="u",
        schema_model=ResearchFindings,
    )
    tailor, _ = deepseek_fake.structured(
        task="tailor", system="s", user_content="u", schema_model=TailorResult,
    )
    assert standard.mission
    assert deep.news and deep.sources
    assert tailor.resume.contact.name == "Jordan Rivera"
    assert tailor.cover_letter_md
    assert len(deepseek_fake.calls) == 3


def test_fake_mode_missing_fixture_raises(deepseek_fake):
    with pytest.raises(DeepSeekError):
        deepseek_fake.structured(
            task="does_not_exist", system="s", user_content="u",
            schema_model=ParsedPosting,
        )


def test_make_deepseek_honors_fake_mode():
    class FakeSettings:
        fake_mode = True
        deepseek_api_key = None

    class RealSettings:
        fake_mode = False
        deepseek_api_key = "sk-test-123"

    fake_service = make_deepseek(FakeSettings())
    assert fake_service.fake_mode is True
    assert fake_service.fixtures_dir is not None
    assert (fake_service.fixtures_dir / "parse_posting.json").exists()

    real_service = make_deepseek(RealSettings())
    assert real_service.fake_mode is False
    assert real_service.api_key == "sk-test-123"
    assert real_service.fixtures_dir == fake_service.fixtures_dir
