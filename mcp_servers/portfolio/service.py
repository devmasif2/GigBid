import json
import os
import re
from collections.abc import Mapping
from datetime import date as Date
from pathlib import Path
from threading import Lock
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

from rag.cross_encoder import get_local_cross_encoder
from rag.ollama_embeddings import OllamaEmbeddings
from rag.variants.v2_hybrid import hybrid_retrieve
from rag.variants.v3_rerank import rerank

EvidenceType = Literal["cv", "case_study", "repo_readme", "code", "review", "proposal"]


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(validation_alias=AliasChoices("id", "evidence_id"))
    freelancer_id: str | None = None
    title: str
    type: EvidenceType
    source: str
    date: Date | None = None
    outcome: str | None = None
    project: str | None = None
    client_industry: str | None = None
    skills: list[str] = Field(default_factory=list)
    content: str = Field(validation_alias=AliasChoices("content", "summary"))
    data_kind: Literal["real", "synthetic", "unverified"] = "unverified"

    @model_validator(mode="after")
    def recognize_labeled_synthetic_source(self) -> "EvidenceItem":
        if "data_kind" not in self.model_fields_set and "synthetic" in self.source.casefold():
            self.data_kind = "synthetic"
        return self


class Portfolio:
    def __init__(self, path: Path | None = None) -> None:
        configured_path = os.environ.get(
            "GIGBID_PORTFOLIO_PATH", "data/sample/portfolio_items.json"
        )
        self.path = path or Path(configured_path)
        self._embedding_lock = Lock()
        self._cached_texts: tuple[str, ...] | None = None
        self._cached_vectors: list[list[float]] | None = None

    def _items(self) -> list[EvidenceItem]:
        with self.path.open(encoding="utf-8") as file:
            data = json.load(file)
        return TypeAdapter(list[EvidenceItem]).validate_python(data)

    def search_evidence(
        self,
        requirement: str,
        k: int = 5,
        filters: Mapping[str, str] | None = None,
    ) -> list[EvidenceItem]:
        if not requirement.strip():
            raise ValueError("requirement must not be empty")
        if not 1 <= k <= 50:
            raise ValueError("k must be between 1 and 50")

        normalized_filters = self._normalize_filters(filters or {})
        items = [item for item in self._items() if self._matches_filters(item, normalized_filters)]
        mode = os.environ.get("GIGBID_PORTFOLIO_SEARCH", "lexical")
        reranker = os.environ.get("GIGBID_PORTFOLIO_RERANK", "none")
        if reranker not in {"none", "cross_encoder"}:
            raise ValueError(f"unsupported portfolio reranker: {reranker}")
        if reranker == "cross_encoder" and mode != "ollama_hybrid":
            raise ValueError("cross_encoder reranking requires ollama_hybrid search")
        if mode == "ollama_hybrid":
            return self._hybrid_search(requirement, k, items, reranker == "cross_encoder")
        if mode != "lexical":
            raise ValueError(f"unsupported portfolio search mode: {mode}")
        query_terms = set(re.findall(r"[\w+#.-]+", requirement.casefold()))
        ranked: list[tuple[int, str, EvidenceItem]] = []

        for item in items:
            searchable_text = " ".join(
                [item.title, item.content, *item.skills, item.project or ""]
            ).casefold()
            item_terms = set(re.findall(r"[\w+#.-]+", searchable_text))
            score = sum(term in item_terms for term in query_terms)
            if score:
                ranked.append((score, item.id, item))

        ranked.sort(key=lambda result: (-result[0], result[1]))
        return [item for _, _, item in ranked[:k]]

    def _hybrid_search(
        self, requirement: str, k: int, items: list[EvidenceItem], use_reranker: bool
    ) -> list[EvidenceItem]:
        if not items:
            return []
        if len({item.id for item in items}) != len(items):
            raise ValueError("portfolio evidence IDs must be unique for hybrid search")
        model = os.environ.get("GIGBID_EMBEDDING_MODEL", "nomic-embed-text")
        base_url = os.environ.get("GIGBID_OLLAMA_URL", "http://127.0.0.1:11434")
        provider = OllamaEmbeddings(base_url, model)
        is_nomic = model.split(":", 1)[0] == "nomic-embed-text"
        document_prefix = "search_document: " if is_nomic else ""
        query_prefix = "search_query: " if is_nomic else ""
        texts = tuple(
            document_prefix + " ".join([item.title, item.content, *item.skills, item.project or ""])
            for item in items
        )
        cache_key = (base_url, model, *texts)
        with self._embedding_lock:
            if self._cached_texts != cache_key or self._cached_vectors is None:
                self._cached_vectors = provider.embed(texts)
                self._cached_texts = cache_key
            vectors = self._cached_vectors
        indexed = [
            {**item.model_dump(mode="json"), "vector": vector}
            for item, vector in zip(items, vectors, strict=True)
        ]

        class Index:
            def __init__(self) -> None:
                self.items = indexed

            def embed_query(self, query: str) -> list[float]:
                return provider.embed([query_prefix + query])[0]

        minimum_score = float(os.environ.get("GIGBID_MIN_DENSE_SCORE", "0.3"))
        candidate_count = k
        if use_reranker:
            configured_count = int(os.environ.get("GIGBID_RERANK_CANDIDATES", "20"))
            if not 1 <= configured_count <= 100:
                raise ValueError("reranker candidate count must be between 1 and 100")
            candidate_count = max(k, configured_count)
        ranked = hybrid_retrieve(
            requirement, Index(), k=candidate_count, min_dense_score=minimum_score
        )
        if use_reranker and ranked:
            model_path = os.environ.get("GIGBID_RERANK_MODEL_PATH", "")
            model = get_local_cross_encoder(model_path)
            texts = [
                " ".join([item["title"], item["content"], *item["skills"], item["project"] or ""])
                for item in ranked
            ]
            scores = model.score(requirement, texts)
            if len(scores) != len(ranked):
                raise ValueError("reranker returned an invalid score count")
            scored = [{**item, "content": text} for item, text in zip(ranked, texts, strict=True)]
            score_by_text = dict(zip(texts, scores, strict=True))
            ranked = rerank(requirement, scored, lambda _, text: score_by_text[text], k=k)
        by_id = {item.id: item for item in items}
        return [by_id[result["id"]] for result in ranked]

    def get_case_study(self, case_id: str) -> EvidenceItem | None:
        return next(
            (
                item
                for item in self._items()
                if item.id == case_id and item.type == "case_study"
            ),
            None,
        )

    def get_proposal(self, proposal_id: str) -> EvidenceItem | None:
        return next(
            (
                item
                for item in self._items()
                if item.id == proposal_id and item.type == "proposal"
            ),
            None,
        )

    def list_skills(self) -> list[str]:
        skills = {skill for item in self._items() for skill in item.skills}
        return sorted(skills, key=str.casefold)

    @staticmethod
    def _normalize_filters(filters: Mapping[str, str]) -> dict[str, str]:
        allowed_filters = {"type", "project", "skill"}
        unknown_filters = set(filters) - allowed_filters
        if unknown_filters:
            names = ", ".join(sorted(unknown_filters))
            raise ValueError(f"unsupported filter(s): {names}")
        return {key: value.casefold() for key, value in filters.items()}

    @staticmethod
    def _matches_filters(
        item: EvidenceItem, filters: Mapping[str, str]
    ) -> bool:
        if "type" in filters and item.type.casefold() != filters["type"]:
            return False
        if "project" in filters and (item.project or "").casefold() != filters["project"]:
            return False
        if "skill" in filters:
            return filters["skill"] in {skill.casefold() for skill in item.skills}
        return True
