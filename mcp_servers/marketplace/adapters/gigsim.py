"""HTTP adapter for GigSim (the local stand-in or a compatible simulator)."""

import os
from typing import Any

import httpx

from agent.marketplace_port import (
    JobNotFoundError,
    MarketplaceRateLimitedError,
    MarketplaceRejectedError,
    MarketplaceUnavailableError,
)


class _NotFoundError(MarketplaceRejectedError):
    """Internal: the marketplace returned 404."""


class GigSimMarketplace:
    supports_remote_drafts = True

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("GIGSIM_BASE_URL", "http://127.0.0.1:8100")).rstrip(
            "/"
        )
        self._token = token if token is not None else os.environ.get("GIGSIM_API_TOKEN")
        self._client = client
        self._timeout = timeout

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        if not self._token:
            raise MarketplaceUnavailableError("GIGSIM_API_TOKEN is not configured")
        headers = {"Authorization": f"Bearer {self._token}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            if self._client is not None:
                response = await self._client.request(
                    method, path, params=params, json=body, headers=headers
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as http:
                    response = await http.request(
                        method, f"{self.base_url}{path}", params=params, json=body, headers=headers
                    )
        except httpx.HTTPError as error:
            raise MarketplaceUnavailableError("GigSim is unreachable or timed out") from error
        return self._check(response)

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        return detail if isinstance(detail, str) else f"HTTP {response.status_code}"

    def _check(self, response: httpx.Response) -> Any:
        status = response.status_code
        if status < 300:
            try:
                return response.json()
            except ValueError as error:
                raise MarketplaceUnavailableError("GigSim returned invalid JSON") from error
        if status in (401, 403):
            raise MarketplaceUnavailableError("GigSim authentication failed")
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            raise MarketplaceRateLimitedError(
                "GigSim rate limit exceeded",
                float(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if status >= 500:
            raise MarketplaceUnavailableError(f"GigSim server error ({status})")
        if status == 404:
            raise _NotFoundError(self._detail(response))
        raise MarketplaceRejectedError(self._detail(response))

    async def search_jobs(self, query: str) -> list[dict[str, Any]]:
        return await self._request("GET", "/jobs", params={"query": query, "limit": 50})

    async def get_job(self, job_id: str) -> dict[str, Any]:
        try:
            return await self._request("GET", f"/jobs/{job_id}")
        except _NotFoundError as error:
            raise JobNotFoundError(f"job not found: {job_id}") from error

    async def get_client_history(self, client_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/clients/{client_id}/history")

    async def get_connects_balance(self) -> dict[str, Any]:
        return await self._request("GET", "/account/connects")

    async def list_proposals(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/proposals")

    async def create_proposal_draft(
        self, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST", "/proposals", body=payload, idempotency_key=idempotency_key
        )

    async def submit_proposal(self, proposal_id: str, idempotency_key: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/proposals/{proposal_id}/confirm",
            idempotency_key=idempotency_key,
        )

    async def list_messages(self, proposal_id: str | None = None) -> list[dict[str, Any]]:
        params = {"proposal_id": proposal_id} if proposal_id else None
        return await self._request("GET", "/messages", params=params)

    async def send_message(
        self, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST", "/messages", body=payload, idempotency_key=idempotency_key
        )

    async def get_policy(self) -> dict[str, Any]:
        return await self._request("GET", "/policy")
