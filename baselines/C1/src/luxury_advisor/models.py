"""Validate inputs and generated messages at the application boundary."""

from enum import StrEnum
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Scenario(StrEnum):
    GREETING = "greeting"
    RECOMMENDATION = "recommendation"
    POST_PURCHASE = "post_purchase"
    REACTIVATION = "reactivation"
    INVITATION = "invitation"
    PRICE_OBJECTION = "price_objection"


LifecycleStage = Literal["unknown", "new", "developing", "established"]


class ClientBackground(StrictModel):
    gender: Literal["unknown", "female", "male", "other", "undisclosed"] = "unknown"
    age: int | None = Field(default=None, ge=0, le=120, strict=True)
    occupation: str = Field(default="", max_length=100)
    source: str = Field(default="", max_length=500)
    observed_on: date | None = None

    @model_validator(mode="after")
    def known_background_has_source(self):
        known = self.gender != "unknown" or self.age is not None or bool(self.occupation)
        if known and not self.source:
            raise ValueError("Known client background requires its source")
        today = datetime.now(timezone(timedelta(hours=8))).date()
        if self.observed_on and self.observed_on > today:
            raise ValueError("Background observation must not be in the future")
        if known and self.observed_on is None:
            self.observed_on = today
        return self


class Client(StrictModel):
    preferred_name: str = Field(min_length=1, max_length=40)
    relationship: str = Field(max_length=200)
    preferences: list[str] = Field(max_length=12)
    notes: list[str] = Field(default_factory=list, max_length=12)
    lifecycle_stage: LifecycleStage = "unknown"
    background: ClientBackground = Field(default_factory=ClientBackground)


class HistoryMessage(StrictModel):
    speaker: Literal["client", "advisor"]
    text: str = Field(min_length=1, max_length=2000)


class DraftRequest(StrictModel):
    scenario: Scenario
    client: Client
    conversation_history: list[HistoryMessage] = Field(default_factory=list, max_length=30)
    product_ids: list[str] = Field(default_factory=list, max_length=5)
    scenario_details: dict[str, str] = Field(default_factory=dict, max_length=12)
    client_id: UUID | None = None
    client_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def linked_profile_has_revision(self):
        if (self.client_id is None) != (self.client_revision is None):
            raise ValueError("Linked client and revision must be provided together")
        return self


class TestCase(StrictModel):
    case_id: str = Field(pattern=r"^D\d{3}$")
    purpose: str
    input: DraftRequest


class Candidate(StrictModel):
    strategy: str = Field(min_length=1, max_length=40)
    message: str = Field(min_length=1, max_length=160)


class CandidateSet(StrictModel):
    candidates: list[Candidate] = Field(min_length=3, max_length=3)


class ProfileCreate(StrictModel):
    preferred_name: str = Field(min_length=1, max_length=40)
    relationship: str = Field(default="", max_length=200)
    fictional: Literal[True] = True
    lifecycle_stage: LifecycleStage = "new"
    background: ClientBackground = Field(default_factory=ClientBackground)


class ProfileUpdate(ProfileCreate):
    expected_revision: int = Field(ge=1)
    contact_status: Literal["allowed", "paused"] = "allowed"


class RevisionRequest(StrictModel):
    expected_revision: int = Field(ge=1)


class ProfileFact(StrictModel):
    expected_revision: int = Field(ge=1)
    kind: Literal["preference", "style", "constraint", "experience", "intent"]
    topic: str = Field(min_length=1, max_length=60)
    value: str = Field(min_length=1, max_length=500)
    scope: Literal["all", "greeting", "recommendation", "post_purchase", "reactivation", "invitation", "price_objection"] = "all"
    source: str = Field(min_length=1, max_length=1000)
    status: Literal["confirmed", "pending"] = "confirmed"
    observed_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: AwareDatetime | None = None
    replaces_fact_id: UUID | None = None

    @model_validator(mode="after")
    def expiry_follows_observation(self):
        if self.observed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("Observation must not be in the future")
        if self.valid_until and self.valid_until <= self.observed_at:
            raise ValueError("Expiry must follow observation")
        return self


class InteractionCreate(StrictModel):
    expected_revision: int = Field(ge=1)
    speaker: Literal["client", "advisor"]
    text: str = Field(min_length=1, max_length=2000)
    source: str = Field(min_length=1, max_length=120)
    scenario: Scenario | None = None
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def interaction_has_occurred(self):
        if self.occurred_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("Only interactions that have occurred can be recorded")
        return self
