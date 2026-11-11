from backend import mcp_ops
from backend.app.schemas import ParsedPosting
from backend.app.services.resume_guidance import (
    RESUME_GUIDE, keyword_catalog, keyword_reference, matching_roles,
)
from backend.app.services.tailor import TAILOR_SYSTEM


def posting(title):
    return ParsedPosting(title=title, company="Example")


def test_both_generation_paths_receive_the_same_policy():
    assert RESUME_GUIDE in TAILOR_SYSTEM
    guide = mcp_ops.get_workflow_guide()
    assert RESUME_GUIDE in guide
    assert keyword_reference() in guide


def test_sheet_snapshot_preserves_role_qualifications_and_source():
    catalog = keyword_catalog()
    assert catalog["source_url"].endswith("pubhtml#gid=0")
    assert catalog["retrieved_on"] == "2026-11-10"
    ai = next(r for r in catalog["roles"] if r["title"] == "AI Engineer")
    assert "MCP" in ai["qualifications"]
    assert "Nice to Have" in ai["qualifications"]
    assert "\n" in ai["qualifications"]


def test_specific_title_matching_handles_seniority_and_common_aliases():
    assert matching_roles(posting("Senior Python Software Developer"))[0]["title"] == "Python SWE"
    assert matching_roles(posting("Senior Machine Learning Engineer"))[0]["title"] == "Machine Learning (ML) Engineer"
    assert matching_roles(posting("Frontend Developer"))[0]["title"] == "Front End Developer"


def test_intern_and_market_references_do_not_leak_into_other_roles():
    for title in ("Python SWE", "Data Engineer", "Software Engineer"):
        matches = matching_roles(posting(title))
        assert matches
        assert all("Intern" not in r["title"] for r in matches)
        assert all("(EU)" not in r["title"] and "India" not in r["title"] for r in matches)
    assert matching_roles(posting("Data Engineer Intern"))[0]["title"] == "Data Engineer Intern"
    assert matching_roles(posting("Python SWE (EU)"))[0]["title"] == "Python SWE (EU)"


def test_unmatched_role_uses_posting_alone_even_with_overlapping_skills():
    parsed = posting("Veterinarian")
    parsed.keywords = ["Python", "SQL", "AI"]
    assert matching_roles(parsed) == []
    assert '"roles": []' in keyword_reference(parsed)


def test_reference_is_bounded_and_is_not_posting_or_candidate_evidence():
    reference = keyword_reference(posting("AI Engineer"))
    assert "not candidate evidence" in reference
    assert "not additional posting requirements" in reference
    assert "AI Engineer" in reference
    assert "Cashier" not in reference
    assert len(matching_roles(posting("Software Engineer"))) <= 3
