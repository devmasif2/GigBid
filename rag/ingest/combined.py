"""Build or preview one portfolio index from local and GitHub manifests."""

import argparse
import os
from pathlib import Path

import anyio
from pydantic import TypeAdapter

from mcp_servers.portfolio.service import EvidenceItem
from rag.ingest.github import GitHubManifest, fetch_index
from rag.ingest.portfolio import Manifest, build_local_index, write_index


def build_combined_index(
    local_path: Path | None, github_path: Path | None, output_path: Path
) -> list[EvidenceItem]:
    if local_path is None and github_path is None:
        raise ValueError("provide at least one local or GitHub manifest")
    output = output_path.resolve()
    local_resolved = local_path.resolve(strict=True) if local_path else None
    github_resolved = github_path.resolve(strict=True) if github_path else None
    paths = [path for path in (local_resolved, github_resolved) if path is not None]
    if output in paths:
        raise ValueError("output must differ from every manifest")

    local = Manifest.model_validate_json(local_resolved.read_bytes()) if local_resolved else None
    github = GitHubManifest.model_validate_json(github_resolved.read_bytes()) if github_resolved else None
    documents = [*(local.documents if local else []), *(github.documents if github else [])]
    keys = [(document.freelancer_id, document.source_id) for document in documents]
    if len(set(keys)) != len(keys):
        raise ValueError("source IDs must be unique per freelancer across manifests")

    items = (
        build_local_index(local, local_resolved.parent, output_path=output_path)
        if local is not None and local_resolved is not None
        else []
    )
    if github is not None:
        token = os.environ.get("GIGBID_GITHUB_TOKEN", "").strip()
        if not token:
            raise ValueError("GIGBID_GITHUB_TOKEN is required for GitHub sources")
        items.extend(anyio.run(fetch_index, github, token))
    ids = [item.id for item in items]
    if len(set(ids)) != len(ids):
        raise ValueError("generated evidence IDs are not unique")
    return items


def compare_indexes(old: list[EvidenceItem], new: list[EvidenceItem]) -> dict[str, int]:
    previous = {item.id: item for item in old}
    current = {item.id: item for item in new}
    if len(previous) != len(old) or len(current) != len(new):
        raise ValueError("portfolio evidence IDs must be unique")
    shared = previous.keys() & current.keys()
    changed = sum(previous[key] != current[key] for key in shared)
    return {
        "added": len(current.keys() - previous.keys()),
        "removed": len(previous.keys() - current.keys()),
        "updated": changed,
        "unchanged": len(shared) - changed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", type=Path, help="Local document manifest.")
    parser.add_argument("--github", type=Path, help="GitHub file manifest.")
    parser.add_argument("--output", type=Path, default=Path("data/local/portfolio.json"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replace", action="store_true", help="Replace the complete index.")
    mode.add_argument("--preview", action="store_true", help="Compare without writing.")
    args = parser.parse_args()
    if not args.preview and not args.replace and args.output.exists():
        raise FileExistsError(f"output already exists: {args.output}; use --replace")
    items = build_combined_index(args.local, args.github, args.output)
    if args.preview:
        old = (
            TypeAdapter(list[EvidenceItem]).validate_json(args.output.read_bytes())
            if args.output.exists()
            else []
        )
        changes = compare_indexes(old, items)
        print(
            "Preview: "
            + ", ".join(f"{count} {name}" for name, count in changes.items())
            + f"; {len(items)} total chunks. No index written."
        )
    else:
        write_index(items, args.output, replace=args.replace)
        print(f"Wrote {len(items)} portfolio chunks to {args.output}")


if __name__ == "__main__":
    main()
