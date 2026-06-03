from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from book_canonical.io import write_jsonl


@dataclass(slots=True)
class FaissBuildResult:
    vector_count: int
    dimension: int


def build_faiss_index(
    vectors: list[list[float]],
    docstore_rows: list[dict],
    index_path: str | Path,
    docstore_path: str | Path,
    metadata_path: str | Path,
    index_type: str = "IndexFlatIP",
    metric: str = "inner_product",
) -> FaissBuildResult:
    try:
        import faiss
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("faiss-cpu and numpy are required to build FAISS indexes") from exc

    if not vectors:
        raise ValueError("Cannot build a FAISS index without vectors.")
    if len(vectors) != len(docstore_rows):
        raise ValueError("Vector count must match docstore row count.")
    if index_type != "IndexFlatIP":
        raise ValueError(f"Unsupported FAISS index type: {index_type}")
    if metric != "inner_product":
        raise ValueError(f"Unsupported FAISS metric: {metric}")

    matrix = np.asarray(vectors, dtype="float32")
    if matrix.ndim != 2:
        raise ValueError("FAISS vectors must be a 2D matrix.")

    index = faiss.IndexFlatIP(matrix.shape[1])
    index.add(matrix)

    output_index_path = Path(index_path)
    output_index_path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(output_index_path))

    write_jsonl(docstore_path, ({"vector_id": index, **row} for index, row in enumerate(docstore_rows)))
    metadata = {
        "index_type": index_type,
        "metric": metric,
        "vector_count": int(matrix.shape[0]),
        "dimension": int(matrix.shape[1]),
    }
    output_metadata_path = Path(metadata_path)
    output_metadata_path.parent.mkdir(parents=True, exist_ok=True)
    output_metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    return FaissBuildResult(vector_count=int(matrix.shape[0]), dimension=int(matrix.shape[1]))


def load_faiss_index(index_path: str | Path):
    try:
        import faiss
    except ImportError as exc:
        raise RuntimeError("faiss-cpu is required to load FAISS indexes") from exc
    return faiss.read_index(str(index_path))
