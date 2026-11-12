from pydantic import BaseModel, Field


class JobSpec(BaseModel):
    job_id: str
    title: str
    deliverables: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    budget_min: float | None = None
    budget_max: float | None = None
    budget_currency: str | None = None
    duration_days: int | None = None
    screening_questions: list[str] = Field(default_factory=list)
    connects_cost: int | None = None


class RiskReport(BaseModel):
    score: float = Field(ge=0, le=1)
    flags: list[str] = Field(default_factory=list)
    explanation: str


class FitReport(BaseModel):
    score: float = Field(ge=0, le=1)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class PriceQuote(BaseModel):
    recommended_price: float | None = None
    currency: str | None = None
    rationale: str
    connects_cost: int | None = None
    action: str


class ClaimCheck(BaseModel):
    claim: str
    evidence_ids: list[str] = Field(default_factory=list)
    status: str
    explanation: str


class Critique(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    revision_count: int = 0


class ComplianceVerdict(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)


class ConversationDraft(BaseModel):
    conversation_id: str
    intent: str
    risk_flags: list[str] = Field(default_factory=list)
    message: str
    interview_slots: list[str] = Field(default_factory=list)
    status: str = "pending_review"


class ProposalDraft(BaseModel):
    job_id: str
    cover_letter: str
    screening_answers: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    status: str = "pending_review"
