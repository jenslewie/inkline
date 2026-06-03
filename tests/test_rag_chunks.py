import json

from book_canonical import sample_document
from book_rag import export_chunks


def test_export_chunks_writes_valid_jsonl(tmp_path):
    output = tmp_path / "chunks.jsonl"

    count = export_chunks(sample_document(), output)

    assert count == 1
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    chunk = json.loads(lines[0])
    assert chunk["doc_id"] == "sample"
    assert chunk["book_id"] == "sample"
    assert chunk["parser"] == "sample"
    assert chunk["text"]
    assert chunk["heading_path"] == ["第一章"]
    assert chunk["block_ids"] == ["b000002"]


def test_export_chunks_keeps_traceability_fields(tmp_path):
    document = sample_document()
    document["blocks"] = [
        {
            "block_id": "b000010",
            "type": "paragraph",
            "text": "带来源坐标的段落。",
            "source": {"page": 7, "bbox": [1, 2, 3, 4]},
            "attrs": {},
        }
    ]
    output = tmp_path / "chunks.jsonl"

    export_chunks(document, output)

    chunk = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
    assert chunk["page_start"] == 7
    assert chunk["page_end"] == 7
    assert chunk["bbox_refs"] == [{"page": 7, "bbox": [1, 2, 3, 4]}]
