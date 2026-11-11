# Headless resume template contract

Design authority: the user-supplied `Headless+Resume+Template.docx`, retained
unchanged at `backend/resources/headless-resume-template.docx`.
SHA-256: `C22A09E7DC337ECAFCFBFE9E43204C17AC829A5D1F45EDD98A4C16BF256762E5`.
The annotated `Resume+Template.pdf` is retained at
`backend/resources/resume-layout-reference.pdf`. The candidate's explicit
overrides below take precedence over either reference's example instructions.

The reference has one portrait Letter section, one column, no tables, pictures,
page furniture or fields. Page margins from `word/document.xml`: top 720 twips,
left/right 1440, bottom 1359. The app preserves its existing per-person page-size
choice while applying those margins. The default is Letter.

Typography: Arial, black, 14pt bold centered name; 9pt authorization line and
9.5pt contact line; 10.5pt bold section labels and regular body; italic job lines.
The candidate-supplied authorization_note goes below the name and above the
contact line. Compact contact labels have real mailto/tel/web hyperlinks.
Body line height is 1.5em; DOCX uses exact 315-twip spacing to match the PDF's
15.75pt grid. Headers use 1.15 spacing. Name retains 18pt before/4pt after;
the header ends with a 10.5pt gap. Bullet text starts 720 twips from the text
margin with a 360-twip hanging marker. GPA is inline with education, separated
by a vertical bar. The heading is Education when there are no certificates.
Project headings contain only the name and a smaller clickable repository
URL; project descriptions are omitted in every export.

Reference rendered read-only with Microsoft Word to `tmp/headless-reference.pdf`
and Poppler to `tmp/headless-reference.png`. The packaged renderer was unavailable
because LibreOffice was absent. Word's Symbol font renders the source's U+23AA
contact separators as spades on this machine; HTML uses ordinary vertical bars
for the intended separator rather than reproducing that font-mapping artifact.

Slot map (`word/document.xml`, zero-based body paragraph indexes):

- 0: candidate name. 1: compact contact links, also reused for the explicit
  authorization note between name and contact. 2: supported location.
  Never fill citizenship from a placeholder.
- 3-4: blank separation before the opening section.
- 5: Education & Certificates label. 6: degree/institution with status/year at
  right. 7: certification. Repeat evidence-backed entries as needed.
- 8: section separation. 9: Work History OR Projects example section label;
  instantiate Work History and/or Projects for the candidate's actual evidence.
- 10, 16, 22: repeated role/company/location/date lines; repeat for supported
  roles only. Format known YYYY-MM as MM/YYYY; preserve year-only dates.
- 11-14, 17-20, 23-26: summary and achievement bullet examples. Replace all
  instructional text; never print the minimum/maximum placeholder as a bullet.
- 15, 21: separation between roles. No fixed three-role requirement.

`headless_resume.html`, `_headless_resume_body.html`, and `resume_guide.css` own
the HTML/PDF adaptation. Education and certifications are displayed together
first, then work, projects, and optional supported Skills/Additional sections.
The original section indexes remain in edit paths despite visual ordering;
rendering never mutates saved ResumeDoc facts. Optional headline/summary remains
available for explicit candidate direction. Cover letters retain their chosen
template. Existing legacy partials remain intact.

Before the API saves generated content, equivalent month/year spellings are
restored to the bank's literal dates only when the employer, title and both
dates identify one source role. Changed dates or date precision still fail the
truthfulness gate. Dated work history is ordered with ongoing roles first,
then completed roles in reverse chronology.
Projects retain at most the first three selected bullets. HTML/PDF entries can
continue across pages, keeping headings with following content and individual
bullets together, instead of moving a whole entry and leaving a large gap.

`headless_docx.py` also fills the original DOCX directly for the Word download.
It clones the reference paragraph/run properties for each slot and changes
`word/document.xml` and its hyperlink relationships; every other ZIP part remains byte-identical. Its section
properties preserve Letter geometry exactly. It requires no Word installation
for generation. All original example jobs and instruction placeholders are
replaced; optional evidence can extend the repeated role/list pattern.

Word and Chromium have different text metrics, so identical
pagination across engines is not guaranteed for arbitrary text. Compare complete generated pages
at normal zoom; confirm margins, hierarchy, indents, alignment, wrapping, and no
placeholder or unsupported status leakage. Preserve the original DOCX hash.

The saved per-profile one_page_resume preference enforces a measured PDF page
limit before content is saved by pipeline, API edit/template switches or MCP
saves. Fitting removes optional skills/extras first, then lower-priority
projects, excess bullets and older roles. It preserves the source bank,
authorization note, education and readable body type. If minimal content still
cannot fit, saving fails explicitly. The current Simon resume was visually
verified as one page in both Chromium PDF and Microsoft Word.
