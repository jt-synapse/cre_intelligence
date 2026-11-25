from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .finance import FinancialInputs

Label = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
Body = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
Role = Literal[
    "authorized_owner_representative",
    "disclosed_manager",
    "asset_manager",
    "acquisitions_contact",
    "property_manager",
    "registered_agent",
    "officer",
    "other",
]
Stage = Literal[
    "prospect",
    "research",
    "contacted",
    "diligence",
    "under_contract",
    "closed",
    "passed",
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestigationIn(Model):
    property_id: UUID
    objective: Label = "find_business_contact"
    preferred_roles: list[Role] = Field(default_factory=list, max_length=8)
    max_external_requests: int = Field(default=0, ge=0, le=20)
    max_tokens: int = Field(default=1500, ge=0, le=8000)
    research_mode: Literal["approved_sources_only"] = "approved_sources_only"
    allow_external_outreach: Literal[False] = False
    require_evidence: Literal[True] = True


class EvidenceIn(Model):
    kind: Literal["entity_identity", "property_role", "business_channel", "ownership"]
    assertion: Body
    reference: Body
    locator: Label
    subject: Label
    relationship: Role | None = None
    channel_kind: (
        Literal["general_office", "business_email", "business_phone"] | None
    ) = None
    identity_finding_id: UUID | None = None
    channel_value: Label | None = None
    document_id: UUID | None = None
    exportable: bool = False
    effective_date: date | None = None
    source_excerpt: Body | None = None


class ReviewTyping(Model):
    relationship: Role | None = None
    identity_finding_id: UUID | None = None
    channel_kind: (
        Literal["general_office", "business_email", "business_phone"] | None
    ) = None
    channel_value: Label | None = None


class FindingReview(Model):
    enrichment: ReviewTyping | None = None
    finding_id: UUID
    decision: Literal["accept", "reject", "correct", "conflict", "stale"]
    reason: Body
    correction: Body | None = None

    @model_validator(mode="after")
    def check_correction(self):
        if self.enrichment is not None and self.decision != "accept":
            raise ValueError("Typed evidence is attached to an acceptance decision")
        if (self.decision == "correct") != bool(self.correction):
            raise ValueError("A correction requires replacement assertion text")
        return self


class OpportunityIn(Model):
    property_id: UUID
    title: Label
    stage: Stage = "prospect"
    assignee: Label | None = None


class OpportunityPatch(Model):
    stage: Stage | None = None
    assignee: Label | None = None


class ActivityIn(Model):
    kind: Literal["task", "visit", "note", "contact_attempt", "lease"]
    body: Body
    assignee: Label | None = None
    document_id: UUID | None = None


class ScenarioIn(Model):
    property_id: UUID
    name: Label
    period: Literal["Annual"] = "Annual"
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] = "USD"
    assumptions: Annotated[str, StringConstraints(max_length=4000)] = ""
    inputs: FinancialInputs
    sources: dict[str, Label] = Field(default_factory=dict, max_length=16)


class ReportIn(Model):
    property_id: UUID
    scenario_id: UUID | None = None
    investigation_id: UUID | None = None
    opportunity_id: UUID | None = None


class Decision(Model):
    decision: Literal["approve", "reject"]
    reason: Body


class DraftIn(Model):
    channel_finding_id: UUID
    body: Body


class SuppressionIn(Model):
    property_id: UUID
    channel: Label
    reason: Body
