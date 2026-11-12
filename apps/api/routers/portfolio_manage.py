"""Opt-in local-only portfolio document management."""

import base64
import binascii
import hmac
import ipaddress
import os
from pathlib import Path
from typing import Annotated

import anyio
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rag.ingest.portfolio import MAX_FILE_BYTES, SourceDocument
from rag.ingest.store import PortfolioStore, SourceConflict, SourceNotFound

router = APIRouter(prefix="/portfolio/manage", tags=["portfolio"])
MAX_REQUEST_BYTES = 2_800_000


class UploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: SourceDocument
    content_base64: str = Field(max_length=2_700_000)
    expected_revision: int | None = Field(default=None, ge=1)


class DeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    freelancer_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=1)


def authorize(request: Request, token: str | None) -> PortfolioStore:
    configured = os.environ.get("GIGBID_PORTFOLIO_MANAGE_TOKEN", "")
    path = os.environ.get("GIGBID_PORTFOLIO_PATH", "")
    if len(configured) < 32 or not path or Path(path).suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        raise HTTPException(status_code=404, detail="Local portfolio management is disabled.")
    try:
        local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if not local or token is None or not hmac.compare_digest(token.encode(), configured.encode()):
        raise HTTPException(status_code=403, detail="Local portfolio management access denied.")
    store = PortfolioStore(Path(path))
    store.initialize()
    return store


async def parse_body(request: Request, model: type[UploadRequest] | type[DeleteRequest]):
    body = bytearray()
    async for data in request.stream():
        body.extend(data)
        if len(body) > MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="Document request is too large.")
    try:
        return model.model_validate_json(body)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="Invalid document metadata or request.") from error


@router.get("/sources")
def list_sources(
    request: Request, x_portfolio_token: Annotated[str | None, Header()] = None,
) -> list[dict]:
    return authorize(request, x_portfolio_token).list_sources()


@router.post("/sources")
async def upload_source(
    request: Request, x_portfolio_token: Annotated[str | None, Header()] = None,
) -> dict[str, int]:
    store = await anyio.to_thread.run_sync(authorize, request, x_portfolio_token)
    body = await parse_body(request, UploadRequest)
    assert isinstance(body, UploadRequest)
    if Path(body.document.path).name != body.document.path or "\\" in body.document.path:
        raise HTTPException(status_code=422, detail="Document path must be a filename.")
    try:
        raw = base64.b64decode(body.content_base64, validate=True)
        if len(raw) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="Document exceeds size limit.")
        revision = await anyio.to_thread.run_sync(
            store.put, body.document, raw, body.expected_revision
        )
    except (binascii.Error, UnicodeDecodeError) as error:
        raise HTTPException(status_code=422, detail="Invalid document encoding.") from error
    except SourceConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SourceNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"revision": revision}


@router.post("/sources/delete")
async def delete_source(
    request: Request, x_portfolio_token: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    store = await anyio.to_thread.run_sync(authorize, request, x_portfolio_token)
    body = await parse_body(request, DeleteRequest)
    assert isinstance(body, DeleteRequest)
    try:
        await anyio.to_thread.run_sync(
            store.delete, body.freelancer_id, body.source_id, body.expected_revision
        )
    except SourceConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SourceNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"deleted": True}
