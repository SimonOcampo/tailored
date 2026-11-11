import json
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import ValidationError

from backend.app.schemas import (Contact, ContactLead, ContactResearch, MasterProfile,
    OutreachContact, OutreachDraft, OutreachDrafts, OutreachPlan, ParsedPosting, ResumeDoc, UsageInfo)
from backend.app.services import outreach, public_sources
from backend.app.services.deepseek import DeepSeekService

POSTING = ParsedPosting(title="Backend Engineer", company="Acme", company_domain="acme.example")
QUOTE = "Casey Smith is Engineering Manager at Acme, leading the platform team."
EMAIL_QUOTE = "Casey Smith: casey@acme.example"
SOURCE = f'<p>{QUOTE}</p><p>{EMAIL_QUOTE}</p><a href="https://www.linkedin.com/in/casey-smith">LinkedIn</a>'


def lead(**changes):
    return ContactLead.model_validate({"name": "Casey Smith", "company": "Acme",
        "role": "Engineering Manager", "relevance": "Leads the platform team hiring backend engineers.",
        "source_url": "https://acme.example/team", "evidence_quote": QUOTE,
        "email": "casey@acme.example", "email_source_url": "https://acme.example/team",
        "email_evidence_quote": EMAIL_QUOTE,
        "linkedin_url": "https://www.linkedin.com/in/casey-smith", **changes})


def draft(**changes):
    return OutreachDraft(contact_index=0, email_subject="A question about Acme's platform team",
        email_body="Hi Casey, I saw that you lead Acme's platform team. I am exploring the backend role and would appreciate your perspective. What does the team most value in a new engineer? Thanks for your time.",
        linkedin_message="Hi Casey, I am exploring Acme's backend role. Your platform work caught my interest. What does your team most value in a new engineer?", **changes)


@pytest.fixture()
def source(monkeypatch):
    calls = []
    def fetch(url):
        calls.append(url)
        return SOURCE
    monkeypatch.setattr(outreach, "public_page", fetch)
    return calls


def test_evidenced_contact_email_preference_and_source_cache(source):
    accepted = outreach.verify_contacts([lead()], POSTING)
    assert accepted[0].email == "casey@acme.example"
    assert accepted[0].linkedin_url.endswith("/casey-smith")
    assert source == ["https://acme.example/team"]


@pytest.mark.parametrize("changes", [
    {"email": "guessed@acme.example"}, {"email": "casey@gmail.com"},
    {"email_evidence_quote": None}, {"email_source_url": "https://unrelated.example/team"},
    {"email_evidence_quote": "Someone Else: casey@acme.example"},
])
def test_unsupported_email_is_removed_and_linkedin_is_used(source, changes):
    accepted = outreach.verify_contacts([lead(**changes)], POSTING)
    assert len(accepted) == 1
    assert accepted[0].email is None
    assert accepted[0].email_source_url is None
    assert accepted[0].linkedin_url


@pytest.mark.parametrize("changes", [
    {"company": "Different Company"}, {"name": "Invented Person"},
    {"role": "CEO"}, {"source_url": "https://acme.example.evil.test/team"},
    {"email": None, "linkedin_url": "https://www.linkedin.com/in/invented"},
    {"email": None, "linkedin_url": None},
])
def test_unsubstantiated_identity_or_channel_is_omitted(source, changes):
    assert outreach.verify_contacts([lead(**changes)], POSTING) == []


def test_unreachable_sources_are_not_presented_as_confirmed(monkeypatch):
    monkeypatch.setattr(outreach, "public_page", lambda url: (_ for _ in ()).throw(httpx.ConnectError("blocked")))
    assert outreach.verify_contacts([lead()], POSTING) == []


def test_team_page_cannot_assign_a_colleagues_linkedin(monkeypatch):
    raw = ('<main><div><p>' + QUOTE + '</p><a href="https://www.linkedin.com/in/casey-smith">Casey</a></div>'
           '<div><p>Taylor Jones, Engineering Manager</p><a href="https://www.linkedin.com/in/taylor-jones">Taylor</a></div></main>')
    monkeypatch.setattr(outreach, "public_page", lambda _: raw)
    assert outreach.verify_contacts([lead(email=None)], POSTING)
    assert outreach.verify_contacts([lead(email=None, linkedin_url="https://www.linkedin.com/in/taylor-jones")], POSTING) == []


def test_discovery_post_can_resolve_only_to_an_independently_evidenced_profile(monkeypatch):
    candidate = lead(email=None, source_url="https://www.linkedin.com/posts/acme-announcement")
    raw = '<title>Casey Smith - Acme | LinkedIn</title>' + SOURCE
    monkeypatch.setattr(outreach, "public_page", lambda _: raw)
    resolved = outreach._profile_sources([candidate])
    assert resolved[0].source_url == candidate.linkedin_url
    assert outreach.verify_contacts(resolved, POSTING)
    monkeypatch.setattr(outreach, "public_page", lambda _: raw.replace('Casey Smith - Acme', 'Taylor Jones - Acme'))
    assert outreach._profile_sources([candidate])[0].source_url == candidate.source_url
    monkeypatch.setattr(outreach, "public_page", lambda _: raw.replace(QUOTE, 'Casey Smith works at Acme.'))
    assert outreach._profile_sources([candidate])[0].source_url == candidate.source_url


def test_real_service_orchestration_uses_verified_contacts_and_accounts_for_usage(source, monkeypatch):
    deepseek = DeepSeekService()
    calls = []
    def structured(**kwargs):
        calls.append(kwargs)
        result = ContactResearch(contacts=[lead()]) if kwargs["task"] == "contact_research" else OutreachDrafts(drafts=[draft()])
        return result, UsageInfo(cost_usd=0.1)
    monkeypatch.setattr(deepseek, "structured", structured)
    charged = []
    result = outreach.build_outreach(POSTING, MasterProfile(),
        ResumeDoc(contact=Contact(name="Alex"), headline="", summary=""), deepseek, charged.append)
    assert result.status == "ready"
    assert len(charged) == 2
    assert calls[0]["tools"][0]["name"] == "web_search"
    assert calls[1].get("tools") is None
    assert "VERIFIED CONTACTS" in calls[1]["user_content"]
    assert result.contacts[0].email_body == draft().email_body
    assert len(source) == 1, "do not refetch the same evidence after drafting"


def test_short_drafts_are_enforced():
    for model in (OutreachDraft, OutreachContact):
        values = {**lead().model_dump(), **draft().model_dump()}
        with pytest.raises(ValidationError):
            model.model_validate({**values, "email_body": "word " * 101})
        with pytest.raises(ValidationError):
            model.model_validate({**values, "linkedin_message": "x" * 281})


def test_discovered_names_without_channels_get_separate_evidence_retrieval(source, monkeypatch):
    client = DeepSeekService()
    calls = []
    def structured(**kwargs):
        calls.append(kwargs)
        if kwargs["task"] == "contact_research":
            result = ContactResearch(contacts=[lead(email=None, linkedin_url=None)])
        elif kwargs["task"] == "contact_evidence":
            result = ContactResearch(contacts=[lead()])
        else:
            result = OutreachDrafts(drafts=[draft()])
        return result, UsageInfo(cost_usd=0.1)
    monkeypatch.setattr(client, "structured", structured)
    charged = []
    result = outreach.build_outreach(POSTING, MasterProfile(),
        ResumeDoc(contact=Contact(name="Alex"), headline="", summary=""), client, charged.append)
    assert result.status == "ready"
    assert [c["task"] for c in calls] == ["contact_research", "contact_evidence", "outreach_drafts"]
    assert [t["name"] for t in calls[1]["tools"]] == ["web_fetch"]
    assert len(charged) == 3


def test_no_contacts_remains_an_honest_bounded_outcome(monkeypatch):
    client = DeepSeekService()
    calls = []
    def structured(**kwargs):
        calls.append(kwargs["task"])
        return ContactResearch(), UsageInfo()
    monkeypatch.setattr(client, "structured", structured)
    result = outreach.build_outreach(POSTING, MasterProfile(),
        ResumeDoc(contact=Contact(name="Alex"), headline="", summary=""), client, lambda _: None)
    assert result.status == "no_contacts"
    assert calls == ["contact_research", "contact_evidence"]


def test_mcp_gate_rejects_unverified_contacts_and_inconsistent_status(source):
    contact = OutreachContact(**lead(name="Invented Person").model_dump(), **draft().model_dump(exclude={"contact_index"}))
    with pytest.raises(ValueError, match="public evidence"):
        outreach.validate_plan(OutreachPlan(status="ready", contacts=[contact]), POSTING)
    with pytest.raises(ValueError, match="at least one"):
        outreach.validate_plan(OutreachPlan(status="ready"), POSTING)


@pytest.mark.parametrize("url", ["http://public.example/a", "https://user:pass@public.example/a", "https://public.example:8443/a"])
def test_evidence_fetch_rejects_non_https_or_credentials(url):
    with pytest.raises(ValueError):
        public_sources.public_page(url)


def test_evidence_fetch_pins_public_ip_and_rechecks_redirects(monkeypatch):
    def resolve(host, *args, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1" if host == "localhost" else "93.184.216.34", 443))]
    monkeypatch.setattr(public_sources.socket, "getaddrinfo", resolve)
    with respx.mock as router:
        route = router.get("https://93.184.216.34/team").respond(200, text=SOURCE, headers={"content-type": "text/html"})
        assert public_sources.public_page("https://public.example/team") == SOURCE
        assert route.calls.last.request.headers["host"] == "public.example"
        assert route.calls.last.request.extensions["sni_hostname"] == "public.example"
        route.mock(return_value=httpx.Response(302, headers={"location": "https://localhost/private"}))
        with pytest.raises(ValueError, match="public addresses"):
            public_sources.public_page("https://public.example/team")
        assert len(route.calls) == 2  # no request reached the redirect target
        route.mock(return_value=httpx.Response(302, headers={"location": "https://other.example/private"}))
        with pytest.raises(ValueError, match="allowed company domains"):
            public_sources.public_page("https://public.example/team", allowed_domains=["public.example"])
        assert len(route.calls) == 3  # company restrictions also apply after redirects
