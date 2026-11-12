from typing import Any, Protocol


class MarketplacePort(Protocol):
    async def search_jobs(self, query: str) -> list[dict[str, Any]]: ...

    async def get_job(self, job_id: str) -> dict[str, Any]: ...

    async def get_client_history(self, client_id: str) -> dict[str, Any]: ...

    async def get_connects_balance(self) -> dict[str, Any]: ...

    async def list_proposals(self) -> list[dict[str, Any]]: ...

    async def create_proposal_draft(
        self, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]: ...

    async def list_messages(self, proposal_id: str | None = None) -> list[dict[str, Any]]: ...

    async def get_policy(self) -> dict[str, Any]: ...


class JobNotFoundError(LookupError):
    """Raised when a marketplace adapter cannot find the requested job."""


class MarketplaceUnavailableError(RuntimeError):
    """Raised when the selected marketplace adapter cannot serve a capability."""


class MarketplaceRateLimitedError(MarketplaceUnavailableError):
    """The marketplace asked the caller to slow down; retry after ``retry_after`` seconds."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MarketplaceRejectedError(ValueError):
    """The marketplace refused a request as invalid or conflicting; retrying will not help."""
