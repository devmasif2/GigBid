import json
import subprocess
import sys

import pytest
from pydantic import ValidationError

from agent.nodes.writer import write_proposal
from mcp_servers.portfolio.service import Portfolio
from rag.ingest.portfolio import CHUNK_SIZE, MAX_FILE_BYTES, build_index, chunks, write_index
from rag.verify import verify_claims


@pytest.fixture
def source(tmp_path):
    (tmp_path / "case.md").write_text(
        "Python analytics dashboard for a fictional client. " * 40, encoding="utf-8"
    )
    manifest = {
        "version": 1,
        "documents": [{
            "source_id": "case-1", "path": "case.md", "freelancer_id": "demo",
            "title": "Analytics dashboard", "type": "case_study", "skills": ["Python"],
            "data_kind": "synthetic", "client_industry": "retail", "project": "Example",
            "date": "2026-01-15",
        }],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, manifest


def test_ingestion_retrieves_exact_quotes_and_synthetic_provenance(source, tmp_path):
    manifest_path, _ = source
    result = build_index(manifest_path)
    assert len(result) > 1
    assert all(len(item.content) <= CHUNK_SIZE for item in result)
    assert all(item.data_kind == "synthetic" and item.client_industry == "retail" for item in result)
    assert [item.id for item in result] == [item.id for item in build_index(manifest_path)]
    output = tmp_path / "local" / "portfolio.json"
    write_index(result, output)
    evidence = Portfolio(output).search_evidence("Python")
    assert evidence
    draft = write_proposal({
        "job_spec": {"job_id": "job", "title": "Dashboard", "screening_questions": []},
        "evidence": [evidence[0].model_dump(mode="json")],
    })["proposal_draft"]
    checks = verify_claims(draft["cover_letter"], [evidence[0].model_dump(mode="json")])
    assert checks and all(check["status"] == "supported" for check in checks)
    assert output.stat().st_mode & 0o077 == 0


def test_ingestion_replace_is_explicit_and_atomic_on_validation_error(source, tmp_path):
    manifest_path, manifest = source
    output = tmp_path / "portfolio.json"
    first = build_index(manifest_path)
    write_index(first, output)
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        write_index(first, output)
    assert output.read_bytes() == before
    manifest["documents"][0]["date"] = "not-a-date"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValidationError):
        build_index(manifest_path)
    assert output.read_bytes() == before
    manifest["documents"][0]["date"] = None
    manifest_path.write_text(json.dumps(manifest))
    (manifest_path.parent / "case.md").write_text("New Python text.")
    updated = build_index(manifest_path)
    assert updated[0].id != first[0].id
    write_index(updated, output, replace=True)
    assert Portfolio(output).search_evidence("Python")[0].content == "New Python text."
    assert not list(tmp_path.glob(".portfolio-*"))


def test_real_evidence_requires_explicit_attestation(source):
    path, manifest = source
    manifest["documents"][0]["data_kind"] = "real"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValidationError, match="rights_attested"):
        build_index(path)
    manifest["documents"][0]["rights_attested"] = "true"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValidationError):
        build_index(path)
    manifest["documents"][0]["rights_attested"] = True
    path.write_text(json.dumps(manifest))
    assert all(item.data_kind == "real" for item in build_index(path))


def test_explicit_unverified_label_is_not_overridden_by_source_name(source):
    path, manifest = source
    manifest["documents"][0]["source_id"] = "synthetic-example"
    manifest["documents"][0]["data_kind"] = "unverified"
    path.write_text(json.dumps(manifest))
    assert all(item.data_kind == "unverified" for item in build_index(path))


def test_cli_builds_retrievable_index(source, tmp_path):
    path, _ = source
    output = tmp_path / "index.json"
    run = subprocess.run(
        [sys.executable, "-m", "rag.ingest.portfolio", str(path), "--output", str(output)],
        capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    assert "portfolio chunks" in run.stdout
    assert Portfolio(output).search_evidence("Python")


def test_manifest_rejects_duplicate_sources_and_extra_fields(source):
    path, manifest = source
    manifest["documents"].append(manifest["documents"][0].copy())
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValidationError, match="unique"):
        build_index(path)
    manifest["documents"].pop()
    manifest["documents"][0]["unknown"] = True
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValidationError):
        build_index(path)


@pytest.mark.parametrize("filename,content", [
    ("empty.md", b"  "), ("binary.md", b"\xff"), ("large.txt", b"x" * (MAX_FILE_BYTES + 1)),
    ("not-supported.pdf", b"dummy"),
])
def test_invalid_files_fail_explicitly(source, filename, content):
    path, manifest = source
    (path.parent / filename).write_bytes(content)
    manifest["documents"][0]["path"] = filename
    path.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, UnicodeDecodeError)):
        build_index(path)


def test_manifest_cannot_escape_source_directory(source, tmp_path):
    path, manifest = source
    external = tmp_path.parent / f"{tmp_path.name}-external.txt"
    external.write_text("external")
    try:
        manifest["documents"][0]["path"] = str(external)
        path.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="inside manifest directory"):
            build_index(path)
        (tmp_path / "link.txt").symlink_to(external)
        manifest["documents"][0]["path"] = "link.txt"
        path.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="inside manifest directory"):
            build_index(path)
    finally:
        external.unlink()


def test_chunk_long_unbroken_tokens():
    parts = chunks("x" * 1700)
    assert "".join(parts) == "x" * 1700
    assert [len(part) for part in parts] == [800, 800, 100]


def test_cli_rejects_replacing_source(source):
    path, _ = source
    original = (path.parent / "case.md").read_bytes()
    run = subprocess.run(
        [sys.executable, "-m", "rag.ingest.portfolio", str(path),
         "--output", str(path.parent / "case.md"), "--replace"],
        capture_output=True, text=True, check=False,
    )
    assert run.returncode != 0
    assert "output must differ from every source" in run.stderr
    assert (path.parent / "case.md").read_bytes() == original
