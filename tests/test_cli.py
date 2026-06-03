import json
import zipfile

from book_canonical import sample_document
from book_canonical.io import write_canonical
from inkline_cli.main import main


def test_cli_rag_chunk_and_export_epub(tmp_path):
    canonical = tmp_path / "canonical.json"
    chunks = tmp_path / "chunks.jsonl"
    epub = tmp_path / "book.epub"
    write_canonical(canonical, sample_document())

    assert main(["rag", "chunk", str(canonical), "--output", str(chunks)]) == 0
    assert main(["export", "epub", str(canonical), "--output", str(epub)]) == 0

    chunk = json.loads(chunks.read_text(encoding="utf-8").splitlines()[0])
    assert chunk["chunk_id"] == "sample-sample-000001"
    with zipfile.ZipFile(epub) as zf:
        assert "EPUB/content.opf" in set(zf.namelist())


def test_cli_import_epub(tmp_path):
    canonical = tmp_path / "canonical.json"
    imported = tmp_path / "imported.json"
    epub = tmp_path / "book.epub"
    write_canonical(canonical, sample_document())

    assert main(["export", "epub", str(canonical), "--output", str(epub)]) == 0
    assert main(["import", "epub", str(epub), "--doc-id", "roundtrip", "--output", str(imported)]) == 0

    payload = json.loads(imported.read_text(encoding="utf-8"))
    assert payload["metadata"]["doc_id"] == "roundtrip"
    assert payload["blocks"]
