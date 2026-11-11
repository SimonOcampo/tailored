from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class LinkItem(BaseModel):
    label: str
    url: str


class Contact(BaseModel):
    name: str
    email: str = ""
    phone: Optional[str] = None
    location: Optional[str] = None
    links: list[LinkItem] = Field(default_factory=list)
    authorization_note: str = ""


# Spellings of "still in this role". None is the canonical one: every template
# prints it as "Present" and the JSON-LD omits endDate for it. Folding the other
# spellings into it on the way in means the truthfulness guard's exact match on
# (company, role, start, end) compares the fact rather than how it was typed:
# a model copying an ongoing role tends to write the word the rendered resume
# shows, and a person editing a profile may type it too. A real end date is
# untouched, so "Present" still cannot stand in for a role that ended.
_ONGOING_END = {"", "present", "current", "now"}


def _fold_ongoing_end(value):
    if isinstance(value, str) and value.strip().lower() in _ONGOING_END:
        return None
    return value


# --- Master profile (source of truth about a person) ---

class TaggedBullet(BaseModel):
    text: str
    tags: list[str] = Field(default_factory=list)


class MPExperience(BaseModel):
    company: str
    title: str
    start: str  # "YYYY-MM" or "YYYY"
    end: Optional[str] = None  # None means present
    location: Optional[str] = None
    bullets: list[TaggedBullet] = Field(default_factory=list)

    _ongoing_end_is_none = field_validator("end", mode="before")(_fold_ongoing_end)


class MPProject(BaseModel):
    name: str
    description: str = ""
    url: Optional[str] = None
    bullets: list[TaggedBullet] = Field(default_factory=list)


class SkillGroup(BaseModel):
    label: str
    items: list[str] = Field(default_factory=list)


class MPEducation(BaseModel):
    institution: str
    credential: str
    year: Optional[str] = None
    detail: Optional[str] = None


class MPCertification(BaseModel):
    name: str
    issuer: Optional[str] = None
    year: Optional[str] = None


class MasterProfile(BaseModel):
    summary_notes: str = ""
    experiences: list[MPExperience] = Field(default_factory=list)
    projects: list[MPProject] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    education: list[MPEducation] = Field(default_factory=list)
    certifications: list[MPCertification] = Field(default_factory=list)
    extras: list[str] = Field(default_factory=list)


# --- Posting analysis + research ---

class ParsedPosting(BaseModel):
    title: str
    company: str
    company_domain: Optional[str] = None
    must_haves: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    seniority: Optional[str] = None
    tone: Optional[str] = None


class ResearchFindings(BaseModel):
    mission: str = ""
    products: list[str] = Field(default_factory=list)
    news: list[str] = Field(default_factory=list)
    tech_stack_signals: list[str] = Field(default_factory=list)
    culture_language: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class ContactLead(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    company: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=200)
    relevance: str = Field(min_length=1, max_length=500)
    source_url: str
    evidence_quote: str = Field(min_length=12, max_length=1200)
    email: Optional[str] = None
    email_source_url: Optional[str] = None
    email_evidence_quote: Optional[str] = None
    linkedin_url: Optional[str] = None


class ContactResearch(BaseModel):
    contacts: list[ContactLead] = Field(default_factory=list, max_length=3)
    notes: str = ""


class OutreachDraft(BaseModel):
    contact_index: int = Field(ge=0, le=2)
    email_subject: str = Field(min_length=1, max_length=120)
    email_body: str = Field(min_length=1, max_length=900)
    linkedin_message: str = Field(min_length=1, max_length=280)

    @field_validator("email_body")
    @classmethod
    def short_email(cls, value: str) -> str:
        if len(value.split()) > 100:
            raise ValueError("Outreach emails must be at most 100 words")
        return value


class OutreachDrafts(BaseModel):
    drafts: list[OutreachDraft] = Field(default_factory=list, max_length=3)


class OutreachContact(ContactLead):
    email_subject: str = Field(min_length=1, max_length=120)
    email_body: str = Field(min_length=1, max_length=900)
    linkedin_message: str = Field(min_length=1, max_length=280)

    _short_email = field_validator("email_body")(OutreachDraft.short_email.__func__)


class OutreachPlan(BaseModel):
    status: Literal["ready", "no_contacts", "unavailable"]
    notes: str = ""
    checked_at: str = ""
    contacts: list[OutreachContact] = Field(default_factory=list, max_length=3)


# --- Resume document (renderer contract) ---

class ExperienceItem(BaseModel):
    company: str
    role: str
    start: str
    end: Optional[str] = None
    location: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)

    _ongoing_end_is_none = field_validator("end", mode="before")(_fold_ongoing_end)


class ProjectItem(BaseModel):
    name: str
    description: str = ""
    url: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    institution: str
    credential: str
    year: Optional[str] = None
    detail: Optional[str] = None


class CertificationItem(BaseModel):
    name: str
    issuer: Optional[str] = None
    year: Optional[str] = None


class ExperienceSection(BaseModel):
    type: Literal["experience"] = "experience"
    title: str = "Experience"
    items: list[ExperienceItem] = Field(default_factory=list)


class ProjectsSection(BaseModel):
    type: Literal["projects"] = "projects"
    title: str = "Projects"
    items: list[ProjectItem] = Field(default_factory=list)


class SkillsSection(BaseModel):
    type: Literal["skills"] = "skills"
    title: str = "Skills"
    groups: list[SkillGroup] = Field(default_factory=list)


class EducationSection(BaseModel):
    type: Literal["education"] = "education"
    title: str = "Education"
    items: list[EducationItem] = Field(default_factory=list)


class CertificationsSection(BaseModel):
    type: Literal["certifications"] = "certifications"
    title: str = "Certifications"
    items: list[CertificationItem] = Field(default_factory=list)


class ExtrasSection(BaseModel):
    type: Literal["extras"] = "extras"
    title: str = "Additional"
    items: list[str] = Field(default_factory=list)


ResumeSection = Union[
    ExperienceSection,
    ProjectsSection,
    SkillsSection,
    EducationSection,
    CertificationsSection,
    ExtrasSection,
]


class ResumeDoc(BaseModel):
    contact: Contact
    headline: str
    summary: str
    sections: list[ResumeSection] = Field(default_factory=list)


class TailorResult(BaseModel):
    resume: ResumeDoc
    cover_letter_md: str
    tailoring_notes: str = ""


class UsageInfo(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: "UsageInfo") -> "UsageInfo":
        return UsageInfo(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=round(self.cost_usd + other.cost_usd, 6),
        )


class FetchResult(BaseModel):
    status: Literal["fetched", "needs_paste"]
    text: str = ""
    reason: str = ""
