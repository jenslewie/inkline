from book_canonical import validate_document
from book_epub import export_epub
from book_ingest import import_epub


def test_import_epub_returns_canonical_document(tmp_path):
    from book_canonical import sample_document

    epub_path = tmp_path / "sample.epub"
    export_epub(sample_document(), epub_path)

    document = import_epub(epub_path, doc_id="imported")

    validate_document(document)
    assert document["metadata"]["doc_id"] == "imported"
    assert document["metadata"]["parser_name"] == "epub_importer"
    assert any(block["type"] == "paragraph" for block in document["blocks"])
