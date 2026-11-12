import hashlib
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field


class InterviewHold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hold_id: str
    slot: datetime
    status: str = "tentative"


class EmailDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    conversation_id: str
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    status: str = "draft"


class LocalWorkspace:
    """In-memory calendar/email mock; it never contacts Google or sends email."""

    def __init__(self, available_slots: list[datetime] | None = None) -> None:
        if available_slots is None:
            tomorrow = datetime.now(UTC).replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
            available_slots = [
                tomorrow.replace(hour=10),
                tomorrow.replace(hour=14),
            ]
        self._available_slots = set(available_slots)
        self._holds: dict[str, InterviewHold] = {}
        self._hold_keys: dict[str, str] = {}
        self._drafts: dict[str, EmailDraft] = {}
        self._draft_keys: dict[str, str] = {}

    def free_slots(self, start: datetime, end: datetime) -> list[datetime]:
        if end <= start:
            raise ValueError("end must be later than start")
        held_slots = {hold.slot for hold in self._holds.values()}
        return sorted(
            slot
            for slot in self._available_slots
            if start <= slot <= end and slot not in held_slots
        )

    def create_tentative_hold(
        self, slot: datetime, idempotency_key: str
    ) -> InterviewHold:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")
        if idempotency_key in self._hold_keys:
            hold_id = self._hold_keys[idempotency_key]
            existing = self._holds[hold_id]
            if existing.slot != slot:
                raise ValueError("idempotency_key was already used for a different slot")
            return existing
        if slot not in self._available_slots:
            raise ValueError("requested slot is not in the local calendar")
        if slot in {hold.slot for hold in self._holds.values()}:
            raise ValueError("requested slot is already held")

        hold_id = self._stable_id("hold", idempotency_key)
        hold = InterviewHold(hold_id=hold_id, slot=slot)
        self._holds[hold_id] = hold
        self._hold_keys[idempotency_key] = hold_id
        return hold

    def create_email_draft(
        self,
        conversation_id: str,
        subject: str,
        body: str,
        idempotency_key: str,
    ) -> EmailDraft:
        if not conversation_id.strip():
            raise ValueError("conversation_id must not be empty")
        if not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")
        if idempotency_key in self._draft_keys:
            draft_id = self._draft_keys[idempotency_key]
            existing = self._drafts[draft_id]
            if (
                existing.conversation_id != conversation_id
                or existing.subject != subject
                or existing.body != body
            ):
                raise ValueError("idempotency_key was already used for a different draft")
            return existing

        draft_id = self._stable_id("draft", idempotency_key)
        draft = EmailDraft(
            draft_id=draft_id,
            conversation_id=conversation_id,
            subject=subject,
            body=body,
        )
        self._drafts[draft_id] = draft
        self._draft_keys[idempotency_key] = draft_id
        return draft

    @staticmethod
    def _stable_id(kind: str, idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]
        return f"{kind}-{digest}"
