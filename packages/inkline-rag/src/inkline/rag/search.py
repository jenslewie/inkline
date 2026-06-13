from __future__ import annotations

from pathlib import Path

from inkline.canonical.io import read_jsonl
from inkline.rag.types import SearchResult


def load_docstore(path: str | Path) -> list[dict]:
    rows = sorted(read_jsonl(path), key=lambda row: row["vector_id"])
    for expected_vector_id, row in enumerate(rows):
        if row["vector_id"] != expected_vector_id:
            raise ValueError(
                f"Docstore vector_id sequence is not contiguous at {expected_vector_id}: "
                f"found {row['vector_id']}."
            )
    return rows


def dense_search(
    index, docstore: list[dict], query_embedding: list[float], top_k: int
) -> list[SearchResult]:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required for dense search") from exc

    if top_k <= 0:
        raise ValueError("top_k must be positive.")
    if not query_embedding:
        raise ValueError("query_embedding must not be empty.")
    if index.ntotal != len(docstore):
        raise ValueError(
            f"Index/docstore size mismatch: index={index.ntotal}, docstore={len(docstore)}."
        )

    query = np.asarray([query_embedding], dtype="float32")
    if query.ndim != 2:
        raise ValueError("query_embedding must be a 1D vector.")
    if query.shape[1] != index.d:
        raise ValueError(
            f"Query dimension {query.shape[1]} does not match index dimension {index.d}."
        )

    scores, vector_ids = index.search(query, min(top_k, index.ntotal))
    results: list[SearchResult] = []
    for rank, (score, vector_id) in enumerate(zip(scores[0], vector_ids[0], strict=True), start=1):
        if vector_id < 0:
            continue
        row = docstore[int(vector_id)]
        results.append(
            SearchResult(
                rank=rank,
                vector_id=int(vector_id),
                chunk_id=row["chunk_id"],
                book_id=str(row.get("book_id") or row.get("doc_id") or ""),
                score=float(score),
                title=row.get("title", ""),
                chapter_title=row.get("chapter_title", ""),
                source_path=row.get("source_path", ""),
                text=row.get("text", ""),
            )
        )
    return results
