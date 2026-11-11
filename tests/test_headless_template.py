import hashlib
from xml.dom import minidom
from zipfile import ZipFile

import pytest
from lxml import html as html_parser

from backend.app.services.headless_docx import REFERENCE_DOCX, W, render_resume_docx
from backend.app.services.render import render_resume_html
from test_inline_edit import _full_resume


def test_native_export_preserves_template_package_and_replaces_all_placeholders(tmp_path):
    resume = _full_resume()
    before = resume.model_dump_json()
    output = tmp_path / "resume.docx"
    render_resume_docx(resume, output)
    assert hashlib.sha256(REFERENCE_DOCX.read_bytes()).hexdigest().upper() == (
        "C22A09E7DC337ECAFCFBFE9E43204C17AC829A5D1F45EDD98A4C16BF256762E5"
    )
    with ZipFile(REFERENCE_DOCX) as reference, ZipFile(output) as exported:
        assert reference.namelist() == exported.namelist()
        for name in reference.namelist():
            if name not in {"word/document.xml", "word/_rels/document.xml.rels"}:
                assert reference.read(name) == exported.read(name), name
        source_xml = minidom.parseString(reference.read("word/document.xml"))
        result_xml = minidom.parseString(exported.read("word/document.xml"))
        assert source_xml.getElementsByTagNameNS(W, "sectPr")[0].toxml() == result_xml.getElementsByTagNameNS(W, "sectPr")[0].toxml()
        text = " ".join(t.firstChild.data for t in result_xml.getElementsByTagNameNS(W, "t") if t.firstChild)
        assert "Jane Doe" in text
        assert "Staff Engineer at Initech, Remote" in text
        assert "2021 to Current" in text  # no invented month
        assert "Education & Certificates" in text
        assert text.index("Education & Certificates") < text.index("Work History") < text.index("Projects")
        for placeholder in ("First Name Last Name", "Citizenship status", "8-year-old", "Keyword + HOW", "Minimum 3 bullets", "Status - Graduated"):
            assert placeholder not in text
    assert resume.model_dump_json() == before


def test_preview_uses_headless_slots_without_mutating_saved_section_paths():
    resume = _full_resume()
    resume.sections[0].items[0].start = "2021-03"
    before = resume.model_dump_json()
    html = render_resume_html(resume, "plainwork", edit_mode=True)
    assert html.index('class="section section-education') < html.index('class="section section-experience')
    body = html.split('<body>', 1)[1]
    assert body.index('555-0100') < body.index('jane@example.com')
    assert "03/2021 to Current" in html
    assert 'class="contact-line location-line"' in html
    assert 'continued-education' in html
    assert 'data-edit-path="sections.0.items.0.bullets.0"' in html
    assert resume.model_dump_json() == before


def test_missing_contact_and_credentials_do_not_create_template_placeholders(tmp_path):
    resume = _full_resume()
    resume.contact.phone = None
    resume.contact.location = None
    resume.sections = [s for s in resume.sections if s.type == "experience"]
    html = render_resume_html(resume, "slate")
    assert 'class="contact-line location-line"' not in html
    assert '<h2 class="section-title">Education & Certificates' not in html
    assert "Citizenship status" not in html
    output = tmp_path / "minimal.docx"
    render_resume_docx(resume, output)
    with ZipFile(output) as archive:
        xml = archive.read("word/document.xml").decode()
        assert "Education &amp; Certificates" not in xml
        assert "Citizenship status" not in xml


def test_compact_layout_and_real_hyperlinks_match_in_html_and_word(tmp_path):
    resume = _full_resume()
    resume.contact.authorization_note = "F-1 Student eligible for OPT. Candidate-supplied statement."
    resume.sections = [s for s in resume.sections if s.type != "certifications"]
    education = next(s for s in resume.sections if s.type == "education")
    education.items[0].detail = "GPA: 3.82"
    project = next(s for s in resume.sections if s.type == "projects").items[0]
    project.url = "https://github.com/janedoe/project"
    tree = html_parser.fromstring(render_resume_html(resume, "slate", edit_mode=True))
    assert tree.xpath('//header/*')[1].text_content() == resume.contact.authorization_note
    assert tree.xpath('//section[contains(@class,"section-education")]//h2')[0].text_content().startswith("Education")
    assert "Certificates" not in tree.xpath('//section[contains(@class,"section-education")]//h2')[0].text_content()
    assert "GPA: 3.82" in tree.xpath('//section[contains(@class,"section-education")]//div[contains(@class,"item-head")]')[0].text_content()
    field = tree.xpath('//*[@data-edit-path="sections.3.items.0.detail"]')[0]
    assert field.text_content() == "GPA: 3.82"  # The separator must not be saved as part of the field.
    body = tree.xpath('//body')[0].text_content()
    assert project.description not in body
    assert tree.xpath('//a[@href="mailto:jane@example.com"]')
    assert tree.xpath('//a[@href="tel:5550100"]')
    assert tree.xpath('//a[@href="https://github.com/janedoe/project"]')
    out = tmp_path / "linked.docx"
    render_resume_docx(resume, out)
    with ZipFile(out) as z:
        xml = minidom.parseString(z.read("word/document.xml"))
        paragraphs = ["".join(t.firstChild.data for t in p.getElementsByTagNameNS(W, "t") if t.firstChild)
                      for p in xml.getElementsByTagNameNS(W, "p")]
        assert paragraphs[1] == resume.contact.authorization_note
        assert any("GPA: 3.82" in p and education.items[0].institution in p for p in paragraphs)
        assert any(project.name in p and "github.com/janedoe/project" in p for p in paragraphs)
        assert not any(project.description in p for p in paragraphs)
        rels = minidom.parseString(z.read("word/_rels/document.xml.rels"))
        links = {r.getAttribute("Id"): r.getAttribute("Target") for r in rels.getElementsByTagName("Relationship")}
        ids = [h.getAttribute("r:id") for h in xml.getElementsByTagNameNS(W, "hyperlink")]
        assert {links[i] for i in ids} >= {"mailto:jane@example.com", "tel:5550100", project.url}


@pytest.mark.pdf
def test_one_page_selection_is_measured_and_does_not_mutate_source(tmp_path):
    from backend.app.services.render import prepare_resume, render_pdf
    from pypdf import PdfReader
    resume = _full_resume()
    resume.headline = resume.summary = ""
    resume.contact.authorization_note = "Candidate-supplied authorization statement."
    for section in resume.sections:
        if section.type in {"experience", "projects"}:
            for item in section.items:
                item.bullets = ["Built source-backed services with Python and PostgreSQL for document review and validation workflows." for _ in range(8)]
    before = resume.model_dump_json()
    fitted = prepare_resume(resume, "slate", one_page=True)
    assert resume.model_dump_json() == before
    assert fitted.contact == resume.contact
    assert any(s.type == "education" for s in fitted.sections)
    assert not any(s.type == "skills" for s in fitted.sections)
    path = tmp_path / "one-page.pdf"
    render_pdf(render_resume_html(fitted, "slate"), path)
    reader = PdfReader(path)
    assert len(reader.pages) == 1
    assert fitted.contact.authorization_note in reader.pages[0].extract_text()
