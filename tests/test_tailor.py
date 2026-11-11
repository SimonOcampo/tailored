from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.schemas import (
    Contact,
    ExperienceItem,
    ExperienceSection,
    MasterProfile,
    MPExperience,
    ParsedPosting,
    ProjectItem,
    ProjectsSection,
    ResearchFindings,
    ResumeDoc,
    TaggedBullet,
    TailorResult,
    UsageInfo,
)
from backend.app.services.deepseek import DeepSeekService
from backend.app.services.tailor import tailor_application, verify_truthfulness, restore_source_dates

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "fixtures"


class RecordingClaude(DeepSeekService):
    """Fake-mode DeepSeekService that records every structured() call's kwargs."""

    def __init__(self, fixtures_dir: Path):
        super().__init__(fake_mode=True, fixtures_dir=fixtures_dir)

    def structured(self, *, task, system, user_content, schema_model,
                   tools=None, max_tokens=16000):
        result = super().structured(
            task=task, system=system, user_content=user_content,
            schema_model=schema_model, tools=tools, max_tokens=max_tokens,
        )
        self.calls[-1] = {
            "task": task,
            "system": system,
            "user_content": user_content,
            "schema_model": schema_model,
            "tools": tools,
            "max_tokens": max_tokens,
        }
        return result


@pytest.fixture()
def deepseek_fake() -> RecordingClaude:
    return RecordingClaude(FIXTURES_DIR)


CONTACT = Contact(name="Test Person", email="tp@example.com")

PROFILE = MasterProfile(
    summary_notes="Backend engineer, 8 years, Python and cloud infrastructure.",
    experiences=[
        MPExperience(
            company="Acme Robotics",
            title="Senior Backend Engineer",
            start="2021-03",
            end=None,
            location="Portland, OR",
            bullets=[
                TaggedBullet(
                    text="Built telemetry ingestion services in Python",
                    tags=["python", "backend"],
                )
            ],
        )
    ],
)

PARSED = ParsedPosting(
    title="Staff Engineer",
    company="Initech",
    company_domain="initech.example.com",
    must_haves=["Python", "PostgreSQL"],
    keywords=["Python", "FastAPI"],
)


def test_tailor_returns_result_and_records_one_call(deepseek_fake):
    result, usage = tailor_application(PROFILE, CONTACT, PARSED, None, "slate", deepseek_fake)
    assert isinstance(result, TailorResult)
    assert isinstance(usage, UsageInfo)
    assert len(deepseek_fake.calls) == 1
    call = deepseek_fake.calls[0]
    assert call["task"] == "tailor"
    assert call["schema_model"] is TailorResult
    assert call["max_tokens"] == 32000
    assert call["tools"] is None
    assert "TRUTHFULNESS RUBRIC" in call["system"]
    assert "NEVER invent employers" in call["system"]


def test_user_content_assembly_without_research(deepseek_fake):
    tailor_application(PROFILE, CONTACT, PARSED, None, "slate", deepseek_fake)
    uc = deepseek_fake.calls[-1]["user_content"]
    assert "MASTER PROFILE" in uc
    assert "Test Person" in uc
    assert "Acme Robotics" in uc
    assert "RESEARCH FINDINGS:\nnone" in uc
    assert "experience-first" in uc
    assert "JOB-TITLE QUALIFICATION REFERENCE" in uc
    assert "not candidate evidence" in uc
    assert "REGENERATION FEEDBACK" not in uc


def test_terminal_template_gets_projects_forward_hint(deepseek_fake):
    tailor_application(PROFILE, CONTACT, PARSED, None, "terminal", deepseek_fake)
    assert "projects-forward" in deepseek_fake.calls[-1]["user_content"]


def test_research_findings_included_when_provided(deepseek_fake):
    findings = ResearchFindings(
        mission="Make warehouse robots reliable",
        sources=["https://initech.example.com/about"],
    )
    tailor_application(PROFILE, CONTACT, PARSED, findings, "slate", deepseek_fake)
    uc = deepseek_fake.calls[-1]["user_content"]
    assert "Make warehouse robots reliable" in uc
    assert "RESEARCH FINDINGS:\nnone" not in uc


def test_feedback_lands_in_user_content(deepseek_fake):
    tailor_application(
        PROFILE, CONTACT, PARSED, None, "slate", deepseek_fake,
        feedback="Lead with the migration project",
    )
    uc = deepseek_fake.calls[-1]["user_content"]
    assert "REGENERATION FEEDBACK" in uc
    assert "Lead with the migration project" in uc


def _load_intake(deepseek_fake):
    from backend.app.services.intake import IntakeResult

    intake, _usage = deepseek_fake.structured(
        task="intake", system="fixture-load", user_content="fixture-load",
        schema_model=IntakeResult,
    )
    return intake


def test_fixture_tailor_result_passes_truthfulness(deepseek_fake):
    intake = _load_intake(deepseek_fake)
    result, _usage = tailor_application(
        intake.master_profile, intake.contact, PARSED, None, "slate", deepseek_fake
    )
    assert verify_truthfulness(result.resume, intake.master_profile) == []


def test_single_changed_company_yields_exactly_one_violation(deepseek_fake):
    intake = _load_intake(deepseek_fake)
    result, _usage = tailor_application(
        intake.master_profile, intake.contact, PARSED, None, "slate", deepseek_fake
    )
    bad = result.resume.model_copy(deep=True)
    experience_sections = [s for s in bad.sections if s.type == "experience"]
    assert experience_sections and experience_sections[0].items
    experience_sections[0].items[0].company = "Fake Corp"
    violations = verify_truthfulness(bad, intake.master_profile)
    assert len(violations) == 1
    assert "Fake Corp" in violations[0]


def test_voice_sample_reaches_the_model_labelled_as_style_only(deepseek_fake):
    tailor_application(
        PROFILE, CONTACT, PARSED, None, "slate", deepseek_fake,
        voice_sample="I fix things that are broken. I do not oversell.",
    )
    content = deepseek_fake.calls[-1]["user_content"]
    assert "I fix things that are broken" in content
    assert "NOT a source of facts" in content


def test_voice_notes_reach_the_model(deepseek_fake):
    tailor_application(
        PROFILE, CONTACT, PARSED, None, "slate", deepseek_fake,
        voice_notes="Plain and direct. Short sentences.",
    )
    assert "Plain and direct. Short sentences." in deepseek_fake.calls[-1]["user_content"]


def test_voice_notes_are_marked_as_taking_precedence(deepseek_fake):
    """Explicit instruction beats inference, and the prompt has to say so."""
    tailor_application(
        PROFILE, CONTACT, PARSED, None, "slate", deepseek_fake,
        voice_sample="Some earlier writing.",
        voice_notes="Short sentences.",
    )
    content = deepseek_fake.calls[-1]["user_content"]
    assert content.index("Short sentences.") < content.index("Some earlier writing.")


def test_no_voice_information_leaves_the_input_unchanged(deepseek_fake):
    tailor_application(PROFILE, CONTACT, PARSED, None, "slate", deepseek_fake)
    content = deepseek_fake.calls[-1]["user_content"]
    assert "register reference" not in content.lower()
    assert "VOICE" not in content


def test_the_voice_sample_is_truncated(deepseek_fake):
    tailor_application(
        PROFILE, CONTACT, PARSED, None, "slate", deepseek_fake,
        voice_sample="x" * 10000,
    )
    content = deepseek_fake.calls[-1]["user_content"]
    assert content.count("x") <= 2100, "a whole resume would crowd out the real input"


def test_the_voice_notes_are_truncated(deepseek_fake):
    """Same cap as the sample: a pasted essay must not crowd out the input."""
    tailor_application(
        PROFILE, CONTACT, PARSED, None, "slate", deepseek_fake,
        voice_notes="x" * 10000,
    )
    content = deepseek_fake.calls[-1]["user_content"]
    assert content.count("x") <= 2100


def test_the_system_prompt_carries_the_baseline_style_rules():
    """Enforcement is the backstop; the prompt is the mechanism, so most runs
    pass first time and the retry rarely fires."""
    from backend.app.services.tailor import TAILOR_SYSTEM

    lowered = TAILOR_SYSTEM.lower()
    assert "em dash" in lowered
    assert "emoji" in lowered
    assert "passionate about" in lowered
    assert "straight quote" in lowered
    assert "i'm excited to" in lowered


def test_the_prompt_states_the_apostrophe_carve_out_the_gate_actually_makes():
    """The gate allows an intra-word U+2019 so Macy’s and O’Brien survive. A
    prompt that says "never use curly quotes" without that exception pushes the
    model to respell an employer, and verify_truthfulness compares employers
    verbatim, so the respelling fails the truthfulness check and burns the
    retry. The instruction has to match the rule it is a mechanism for."""
    from backend.app.services.tailor import TAILOR_SYSTEM

    assert "Macy’s" in TAILOR_SYSTEM
    assert "apostrophe" in TAILOR_SYSTEM.lower()
    # The gate side of this pair is test_style.py's
    # test_a_curly_apostrophe_inside_a_word_is_allowed.


def _resume_with(item: ExperienceItem) -> ResumeDoc:
    return ResumeDoc(
        contact=CONTACT, headline="Backend engineer", summary="Builds services.",
        sections=[ExperienceSection(items=[item])],
    )


def _acme(end: str | None) -> ExperienceItem:
    return ExperienceItem(
        company="Acme Robotics", role="Senior Backend Engineer",
        start="2021-03", end=end,
    )


@pytest.mark.parametrize("written", ["Present", "present", "Current", ""])
def test_an_ongoing_role_written_as_present_passes_the_guard(written):
    # Regression: the master profile stores an ongoing role with no end date,
    # which every template prints as "Present". The model wrote "Present",
    # the guard compared it with None, and the whole application failed.
    assert verify_truthfulness(_resume_with(_acme(written)), PROFILE) == []


def test_a_blank_master_profile_end_is_the_same_ongoing_role():
    # "Blank = present", as the profile editor's end field puts it, whether the
    # blank arrives as null or as an empty string through the API.
    blank_end = PROFILE.model_copy(deep=True)
    blank_end.experiences[0] = MPExperience.model_validate(
        {**PROFILE.experiences[0].model_dump(), "end": ""}
    )
    assert verify_truthfulness(_resume_with(_acme(None)), blank_end) == []
    assert verify_truthfulness(_resume_with(_acme("Present")), blank_end) == []


def test_present_does_not_stand_in_for_a_role_that_ended():
    ended = PROFILE.model_copy(deep=True)
    ended.experiences[0] = MPExperience.model_validate(
        {**PROFILE.experiences[0].model_dump(), "end": "2024-01"}
    )
    violations = verify_truthfulness(_resume_with(_acme("Present")), ended)
    assert len(violations) == 1
    assert "Acme Robotics" in violations[0]


@pytest.mark.parametrize("written", ["Mar 2021", "March 2021", "03/2021", "3/2021"])
def test_equivalent_dates_restore_source_values_without_changing_bank(written):
    item = _acme(None)
    item.start = written
    resume = _resume_with(item)
    restore_source_dates(resume, PROFILE)
    assert item.start == "2021-03"
    assert PROFILE.experiences[0].start == "2021-03"
    assert verify_truthfulness(resume, PROFILE) == []


@pytest.mark.parametrize("changes", [
    {"start": "Apr 2021"}, {"start": "2021"},
    {"start": "03/2022"}, {"end": "March 2024"},
    {"company": "Invented Corp", "start": "Mar 2021"},
    {"role": "Invented Role", "start": "Mar 2021"},
])
def test_date_restoration_does_not_accept_changed_facts(changes):
    item = _acme(None).model_copy(update=changes)
    resume = _resume_with(item)
    restore_source_dates(resume, PROFILE)
    assert verify_truthfulness(resume, PROFILE)


def test_date_restoration_cannot_add_month_to_year_only_evidence():
    profile = PROFILE.model_copy(deep=True)
    profile.experiences[0].start = "2021"
    resume = _resume_with(_acme(None))
    restore_source_dates(resume, profile)
    assert verify_truthfulness(resume, profile)


def test_tailoring_restores_dates_and_orders_current_role_first(monkeypatch):
    ended = _acme("Oct 2026")
    ended.start = "Jun 2026"
    current = _acme(None)
    current.company = "Current Corp"
    current.start = "Aug 2026"
    profile = MasterProfile(experiences=[
        MPExperience(company=ended.company, title=ended.role, start="2026-06", end="2026-10"),
        MPExperience(company=current.company, title=current.role, start="2026-08"),
    ])
    resume = ResumeDoc(contact=CONTACT, headline="", summary="", sections=[
        ExperienceSection(items=[ended, current]),
        ProjectsSection(items=[ProjectItem(name="Example", bullets=["First", "Second", "Third", "Fourth"])])])
    client = DeepSeekService()
    monkeypatch.setattr(client, "structured", lambda **kwargs:
        (TailorResult(resume=resume, cover_letter_md="", tailoring_notes=""), UsageInfo()))
    result, _ = tailor_application(profile, CONTACT, PARSED, None, "slate", client)
    items = result.resume.sections[0].items
    assert [(i.company, i.start, i.end) for i in items] == [
        ("Current Corp", "2026-08", None), ("Acme Robotics", "2026-06", "2026-10")]
    assert verify_truthfulness(result.resume, profile) == []
    assert result.resume.sections[1].items[0].bullets == ["First", "Second", "Third"]
