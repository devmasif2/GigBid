"""Build a local portfolio index from an explicitly authored manifest."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    TypeAdapter,
    field_validator,
    model_validator,
)

from mcp_servers.portfolio.service import EvidenceItem, EvidenceType

MAX_FILE_BYTES = 2_000_000
CHUNK_SIZE = 800


class SourceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")
    path: str = Field(min_length=1)
    freelancer_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    type: EvidenceType
    skills: list[str] = Field(min_length=1, max_length=100)
    data_kind: Literal["real", "synthetic", "unverified"]
    rights_attested: StrictBool = False
    project: str | None = None
    date: str | None = None
    client_industry: str | None = None
    outcome: str | None = None

    @field_validator("freelancer_id", "title")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("skills")
    @classmethod
    def valid_skills(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("skills must not contain blank values")
        return value

    @model_validator(mode="after")
    def validate_attestation(self) -> "SourceDocument":
        if self.data_kind == "real" and not self.rights_attested:
            raise ValueError("real evidence requires rights_attested=true")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    documents: list[SourceDocument] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_sources(self) -> "Manifest":
        keys = [(item.freelancer_id, item.source_id) for item in self.documents]
        if len(set(keys)) != len(keys):
            raise ValueError("source IDs must be unique within each freelancer")
        return self


def chunks(text: str, max_chars: int = CHUNK_SIZE) -> list[str]:
    if max_chars < 1:
        raise ValueError("chunk size must be positive")
    output = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= max_chars:
            output.append(remaining)
            break
        boundary = remaining.rfind(" ", 0, max_chars + 1)
        if boundary < max_chars // 2:
            boundary = max_chars
        output.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    return output


def build_index(manifest_path: Path, *, output_path: Path | None = None) -> list[EvidenceItem]:
    manifest_path = manifest_path.resolve(strict=True)
    if output_path is not None and output_path.resolve() == manifest_path:
        raise ValueError("output must differ from manifest")
    root = manifest_path.parent
    manifest = Manifest.model_validate_json(manifest_path.read_bytes())
    items = []
    for document in manifest.documents:
        source = (root / document.path).resolve(strict=True)
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError(f"{document.source_id}: source must be a file inside manifest directory")
        if output_path is not None and output_path.resolve() == source:
            raise ValueError("output must differ from every source document")
        if source.suffix.lower() not in {".md", ".txt"}:
            raise ValueError(f"{document.source_id}: only .md and .txt files are supported")
        with source.open("rb") as file:
            raw = file.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError(f"{document.source_id}: source exceeds size limit")
        text = raw.decode("utf-8")
        parts = chunks(text)
        if not parts:
            raise ValueError(f"{document.source_id}: source is empty")
        source_key = json.dumps(
            [document.freelancer_id, document.source_id], ensure_ascii=True, separators=(",", ":")
        )
        prefix = hashlib.sha256(source_key.encode()).hexdigest()[:24]
        for index, content in enumerate(parts, start=1):
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
            items.append(EvidenceItem.model_validate({
                "id": f"ingest-{prefix}-{index:04d}-{content_hash}",
                "freelancer_id": document.freelancer_id,
                "title": document.title,
                "type": document.type,
                "source": f"local-manifest:{document.source_id}",
                "project": document.project,
                "date": document.date,
                "client_industry": document.client_industry,
                "outcome": document.outcome,
                "skills": document.skills,
                "content": content,
                "data_kind": document.data_kind,
            }))
    ids = [item.id for item in items]
    if len(set(ids)) != len(ids):
        raise ValueError("generated evidence IDs are not unique")
    return items


def write_index(items: list[EvidenceItem], output: Path, *, replace: bool = False) -> None:
    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = TypeAdapter(list[EvidenceItem]).dump_json(items, indent=2) + b"\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".portfolio-", dir=output.parent, delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        if replace:
            os.replace(temporary, output)
            temporary = None
        else:
            os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/local/portfolio.json"))
    parser.add_argument(
        "--replace", action="store_true", help="Replace the existing complete index."
    )
    args = parser.parse_args()
    items = build_index(args.manifest, output_path=args.output)
    write_index(items, args.output, replace=args.replace)
    print(f"Wrote {len(items)} portfolio chunks to {args.output}")


if __name__ == "__main__":
    main()
