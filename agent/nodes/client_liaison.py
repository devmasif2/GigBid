"""Conservative deterministic client-message triage and reply drafting."""

import re
from typing import Any

from agent.handoffs import ConversationDraft

_INJECTION = re.compile(
    r"\b(ignore (all )?(previous|prior|system) instructions|reveal (the )?(system prompt|secrets)|override (all )?policies)\b",
    re.IGNORECASE,
)
_OFF_PLATFORM = re.compile(
    r"\b(whatsapp|telegram|outside the platform|off[- ]platform payment|pay me directly)\b",
    re.IGNORECASE,
)
_UNPAID_WORK = re.compile(
    r"\b(unpaid|for free|without pay)\b.{0,50}\b(trial|test|production|project|work)\b",
    re.IGNORECASE,
)
_NEGOTIATION = re.compile(
    r"\b(rate|budget|price|cost|discount|negotiate)\b", re.IGNORECASE
)
_INTERVIEW = re.compile(
    r"\b(interview|schedule|availability|call|meeting)\b", re.IGNORECASE
)
_QUESTION = re.compile(r"\?")


def draft_client_response(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    conversation_id = state.get("conversation_id")
    message = state.get("client_message")
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise ValueError("conversation_id must be a non-empty string")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("client_message must be a non-empty string")

    flags: list[str] = []
    if _INJECTION.search(message):
        flags.append("prompt_injection")
    if _OFF_PLATFORM.search(message):
        flags.append("off_platform_request")
    if _UNPAID_WORK.search(message):
        flags.append("unpaid_work_request")

    if flags:
        intent = "scam_signal"
        response = (
            "This message needs a safety review. No reply will be sent until you review and approve it."
        )
    elif _NEGOTIATION.search(message):
        intent = "negotiation"
        response = (
            "Thank you for discussing the project terms. I will review the scope and respond with "
            "a considered position."
        )
    elif _INTERVIEW.search(message):
        intent = "interview_request"
        response = "Thank you for the invitation. Possible times for your review:"
    elif _QUESTION.search(message):
        intent = "question"
        response = (
            "Thank you for your question. I will review it and provide a response for your approval."
        )
    else:
        intent = "other"
        response = (
            "Thank you for the update. I will review it and provide a response for your approval."
        )

    slots = state.get("available_slots", [])
    if not isinstance(slots, list) or not all(isinstance(slot, str) for slot in slots):
        raise TypeError("available_slots must be a list of strings")
    if intent == "interview_request":
        if slots:
            response += "\n" + "\n".join(f"- {slot}" for slot in slots)
        else:
            response = "Thank you for the invitation. Please suggest a few convenient times."

    draft = ConversationDraft(
        conversation_id=conversation_id,
        intent=intent,
        risk_flags=flags,
        message=response,
        interview_slots=slots if intent == "interview_request" else [],
    )
    return {"conversation_draft": draft.model_dump(mode="json")}
