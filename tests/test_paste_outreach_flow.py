import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlmodel import Session
from starlette.background import BackgroundTasks

from backend.app.db import init_db
from backend.app.models import Application, Profile, set_contact, set_master_profile
from backend.app.schemas import ContactResearch, OutreachDrafts, UsageInfo
from backend.app.services import fetcher, outreach, pipeline, render
from backend.app.services.deepseek import DeepSeekService
from backend.app.services.intake import IntakeResult
from test_outreach import lead, draft, SOURCE, QUOTE


@pytest.fixture()
def setup_flow(client, engine, fake_settings, deepseek_fake, monkeypatch):
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(render, "render_pdf", lambda html, path, page_size="Letter": Path(path).write_bytes(b"%PDF-1.4 test"))
    intake, _ = deepseek_fake.structured(task="intake", system="seed", user_content="seed", schema_model=IntakeResult)
    with Session(engine) as session:
        profile = Profile(name=intake.contact.name)
        set_contact(profile, intake.contact)
        set_master_profile(profile, intake.master_profile)
        session.add(profile)
        session.commit()
        session.refresh(profile)
        profile_id = profile.id
    response = client.post("/api/applications/batch", json={"profile_id": profile_id,
        "jobs": [{"posting_text": "Backend Engineer at Acme. Python services and APIs. Requirements: Python and SQL."}],
        "generate": False})
    assert response.status_code == 200, response.text
    app_id = response.json()[0]["id"]
    monkeypatch.setattr(fetcher, "fetch_posting", lambda *args: pytest.fail("Pasted text must skip URL fetching"))
    return app_id


def test_pasted_description_to_bank_based_resume_and_evidenced_drafts(
    setup_flow, client, engine, deepseek_fake, monkeypatch
):
    # Resume generation uses the existing fixture provider. Contact discovery
    # exercises the real search/verification/drafting orchestration separately.
    provider = DeepSeekService()
    def structured(**kwargs):
        if kwargs["task"] == "contact_research":
            # Parsed posting fixture names Northwind Labs, not the synthetic input.
            candidate = lead(company="Northwind Labs", source_url="https://northwindlabs.com/team",
                evidence_quote=QUOTE.replace("Acme", "Northwind Labs"),
                email=None, email_source_url=None, email_evidence_quote=None)
            return ContactResearch(contacts=[candidate]), UsageInfo(cost_usd=0.1)
        return OutreachDrafts(drafts=[draft()]), UsageInfo(cost_usd=0.05)
    monkeypatch.setattr(provider, "structured", structured)
    monkeypatch.setattr(outreach, "public_page", lambda url: SOURCE.replace("Acme", "Northwind Labs"))
    original = outreach.build_outreach
    monkeypatch.setattr(outreach, "build_outreach", lambda parsed, master, resume, deepseek, record, voice, **kwargs:
        original(parsed, master, resume, provider, record, voice, **kwargs))
    pipeline.process_application(setup_flow, engine=engine, deepseek=deepseek_fake)
    detail = client.get(f"/api/applications/{setup_flow}").json()
    assert detail["status"] == "ready", detail["error_message"]
    assert detail["raw_text_present"]
    assert detail["resume"]["contact"]["name"] == "Jordan Rivera"
    assert detail["outreach"]["status"] == "ready", detail["outreach"]
    assert detail["outreach"]["contacts"][0]["linkedin_url"]
    assert detail["cost_usd"] == pytest.approx(0.15)
    assert client.get(f"/api/applications/{setup_flow}/exports/resume.docx").content.startswith(b"PK")


def test_contact_outage_keeps_successful_resume_and_paid_usage(
    setup_flow, client, engine, deepseek_fake, monkeypatch
):
    def fail(parsed, profile, resume, deepseek, record, voice, **kwargs):
        record(UsageInfo(cost_usd=0.2))
        raise RuntimeError("Search service unavailable")
    monkeypatch.setattr(outreach, "build_outreach", fail)
    pipeline.process_application(setup_flow, engine=engine, deepseek=deepseek_fake)
    detail = client.get(f"/api/applications/{setup_flow}").json()
    assert detail["status"] == "ready"
    assert detail["outreach"]["status"] == "unavailable"
    assert detail["outreach"]["contacts"] == []
    assert detail["cost_usd"] == 0.2


def test_additive_outreach_migration_preserves_old_data_and_is_idempotent(engine):
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE application DROP COLUMN outreach_json"))
        conn.execute(text("INSERT INTO application (id, profile_id, job_id, template, status, stage, version, input_tokens, output_tokens, cost_usd, created_at, updated_at, resume_json) VALUES (999, 1, 1, 'slate', 'ready', 'drafted', 1, 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'legacy resume')"))
    init_db(engine)
    init_db(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT resume_json, outreach_json FROM application WHERE id=999")).one() == ("legacy resume", None)
