Implemented retrieval components:

- `v0_naive.py`: cosine top-k over precomputed dense vectors; the index supplies
  `embed_query()` and item vectors.
- `v1_decomposition.py`: retrieve once per structured requirement and merge results using
  reciprocal rank.
- `v2_hybrid.py`: BM25 plus dense retrieval combined with reciprocal-rank fusion.
- `v3_rerank.py`: reranks a candidate set with an injected pair scorer. The scorer must be backed
  by an evaluated cross-encoder before this is described as the required model-based V3.
- `v8_corrective.py`: bounded LangGraph retrieve/grade/rewrite loop with injected retriever,
  grader, and query rewriter.

These are algorithm components, not measured RAG results. No embedding model, corpus ingestion,
model-backed cross-encoder, or full evaluation runner is connected yet. V1, V2, V3, and V8 cover
the required algorithm groups, but the measured, model-backed RAG comparison remains pending.
