"""Fill the retained Word template, preserving every other package part.

Document paragraphs and hyperlink relationships change. Styles, numbering,
page settings and all other parts come from the supplied DOCX unchanged.
"""
from __future__ import annotations

from pathlib import Path
from xml.dom import minidom
from zipfile import ZipFile

from ..schemas import ResumeDoc
from .resume_guidance import format_resume_date, contact_links, display_url, safe_web_url

REFERENCE_DOCX = Path(__file__).resolve().parents[2] / "resources" / "headless-resume-template.docx"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def render_resume_docx(resume: ResumeDoc, out_path: Path) -> None:
    with ZipFile(REFERENCE_DOCX) as source:
        document = minidom.parseString(source.read("word/document.xml"))
        document.documentElement.setAttribute("xmlns:r", R)
        rel_path = "word/_rels/document.xml.rels"
        relationships = minidom.parseString(source.read(rel_path))
        used_ids = {n.getAttribute("Id") for n in relationships.getElementsByTagName("Relationship")}
        body = document.getElementsByTagNameNS(W, "body")[0]
        prototypes = [n for n in body.childNodes if n.localName == "p"]

        def paragraph(index: int, text: str = "", right: str | None = None,
                      *, segments=None, right_url=None, size=None, gap=None):
            node = prototypes[index].cloneNode(deep=True)
            prototype = node.getElementsByTagNameNS(W, "r")[0].cloneNode(deep=True)
            for child in list(node.childNodes):
                if child.localName != "pPr":
                    node.removeChild(child)
            for child in list(prototype.childNodes):
                if child.localName != "rPr":
                    prototype.removeChild(child)
            ppr = node.getElementsByTagNameNS(W, "pPr")[0]
            spacing = next((n for n in ppr.childNodes if n.localName == "spacing"), None)
            if spacing is None:
                spacing = document.createElementNS(W, "w:spacing")
                ppr.appendChild(spacing)
            spacing.setAttribute("w:before", "360" if index == 0 else "0")
            spacing.setAttribute("w:after", "80" if index in (0, 5, 9, 10) else "0")
            spacing.setAttribute("w:line", str(gap) if gap else "276" if index in (0, 1, 2) else "315")
            spacing.setAttribute("w:lineRule", "auto" if not gap and index in (0, 1, 2) else "exact")
            if right:
                tabs = next((n for n in ppr.childNodes if n.localName == "tabs"), None)
                if tabs is None:
                    tabs = document.createElementNS(W, "w:tabs")
                    ppr.appendChild(tabs)
                for child in list(tabs.childNodes):
                    tabs.removeChild(child)
                tab = document.createElementNS(W, "w:tab")
                tab.setAttribute("w:val", "right")
                tab.setAttribute("w:pos", "9360")  # Letter text width, 6.5in.
                tabs.appendChild(tab)

            def add_run(value, url=None, run_size=None):
                run = prototype.cloneNode(deep=True)
                if run_size or size:
                    rpr = run.getElementsByTagNameNS(W, "rPr")[0]
                    for name in ("sz", "szCs"):
                        prop = next((n for n in rpr.childNodes if n.localName == name), None)
                        if prop is None:
                            prop = document.createElementNS(W, "w:" + name)
                            rpr.appendChild(prop)
                        prop.setAttribute("w:val", str(int((run_size or size) * 2)))
                if url and run_size:
                    for name in ("i", "iCs"):
                        prop = document.createElementNS(W, "w:" + name)
                        prop.setAttribute("w:val", "0")
                        for old in list(rpr.childNodes):
                            if old.localName == name:
                                rpr.removeChild(old)
                        rpr.appendChild(prop)
                element = document.createElementNS(W, "w:t")
                element.setAttribute("xml:space", "preserve")
                element.appendChild(document.createTextNode(value))
                run.appendChild(element)
                if not url:
                    node.appendChild(run)
                    return
                rid = f"rIdTailoredLink{len(used_ids)}"
                while rid in used_ids:
                    rid += "x"
                used_ids.add(rid)
                relation = relationships.createElementNS(REL, "Relationship")
                for key, val in {"Id": rid, "Type": R + "/hyperlink", "Target": url, "TargetMode": "External"}.items():
                    relation.setAttribute(key, val)
                relationships.documentElement.appendChild(relation)
                hyperlink = document.createElementNS(W, "w:hyperlink")
                hyperlink.setAttribute("r:id", rid)
                hyperlink.appendChild(run)
                node.appendChild(hyperlink)

            if segments is not None:
                for i, link in enumerate(segments):
                    if i:
                        add_run(" | ")
                    add_run(link["label"], link["url"])
            else:
                add_run(text)
            if right:
                tab_run = prototype.cloneNode(deep=True)
                tab_run.appendChild(document.createElementNS(W, "w:tab"))
                node.appendChild(tab_run)
                add_run(right, right_url, 9 if right_url else None)
            return node

        # Preserve sectPr (including exact template margins and page geometry).
        for node in list(body.childNodes):
            if node.localName != "sectPr":
                body.removeChild(node)
        section_properties = body.getElementsByTagNameNS(W, "sectPr")[0]

        def append(node):
            body.insertBefore(node, section_properties)

        append(paragraph(0, resume.contact.name))
        if resume.contact.authorization_note:
            append(paragraph(1, resume.contact.authorization_note, size=9))
        append(paragraph(1, segments=contact_links(resume.contact), size=9.5))
        if resume.contact.location:
            append(paragraph(2, resume.contact.location, size=9.5))
        for text in (resume.headline, resume.summary):
            if text:
                intro = paragraph(11, text)
                # Optional introductory text is not a work-history bullet.
                ppr = intro.getElementsByTagNameNS(W, "pPr")[0]
                for tag in ("numPr", "ind"):
                    for child in list(ppr.childNodes):
                        if child.localName == tag:
                            ppr.removeChild(child)
                append(intro)
        append(paragraph(3, gap=210))

        credentials = [s for s in resume.sections if s.type in ("education", "certifications") and s.items]
        if credentials:
            kinds = {s.type for s in credentials}
            append(paragraph(5, "Education & Certificates" if len(kinds) == 2 else "Education" if "education" in kinds else "Certificates"))
            for section in sorted(credentials, key=lambda s: s.type != "education"):
                for item in section.items:
                    if section.type == "education":
                        text = f"{item.credential}, {item.institution}" + (f" | {item.detail}" if item.detail else "")
                        append(paragraph(6, text, item.year))
                    else:
                        text = item.name + (f", {item.issuer}" if item.issuer else "")
                        append(paragraph(7, text, item.year))
            append(paragraph(8, gap=210))

        for kind, title in (("experience", "Work History"), ("projects", "Projects"),
                            ("skills", "Skills"), ("extras", "Additional")):
            sections = [s for s in resume.sections if s.type == kind]
            for section in sections:
                entries = section.groups if kind == "skills" else section.items
                if not entries:
                    continue
                append(paragraph(9, title))
                for item in entries:
                    if kind == "experience":
                        identity = f"{item.role} at {item.company}"
                        if item.location:
                            identity += f", {item.location}"
                        dates = f"{format_resume_date(item.start)} to {format_resume_date(item.end) if item.end else 'Current'}"
                        append(paragraph(10, identity, dates))
                        for bullet in item.bullets:
                            append(paragraph(11, bullet))
                        append(paragraph(15, gap=210))
                    elif kind == "projects":
                        append(paragraph(10, item.name, display_url(item.url) if item.url else None, right_url=safe_web_url(item.url)))
                        for bullet in item.bullets:
                            append(paragraph(11, bullet))
                        append(paragraph(15, gap=210))
                    elif kind == "skills":
                        append(paragraph(11, f"{item.label}: {', '.join(item.items)}"))
                    else:
                        append(paragraph(11, item))

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(out_path, "w") as output:
            for part in source.infolist():
                payload = (document.toxml(encoding="UTF-8") if part.filename == "word/document.xml"
                           else relationships.toxml(encoding="UTF-8") if part.filename == rel_path
                           else source.read(part.filename))
                output.writestr(part, payload)
