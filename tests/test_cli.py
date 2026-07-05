import json
import zipfile
from pathlib import Path

from inkline.canonical import (
    BOOKGRAPH_SCHEMA_NAME,
    BOOKGRAPH_SCHEMA_VERSION,
    make_bookgraph,
    make_evidence,
    make_node,
    sample_document,
)
from inkline.canonical.io import write_canonical
from inkline.cli.main import build_parser, main


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
    assert (
        main(["import", "epub", str(epub), "--doc-id", "roundtrip", "--output", str(imported)]) == 0
    )

    payload = json.loads(imported.read_text(encoding="utf-8"))
    assert payload["metadata"]["doc_id"] == "roundtrip"
    assert payload["blocks"]


def test_cli_accepts_parser_names_not_known_at_build_time():
    args = build_parser().parse_args(
        ["ingest", "pdf", "input.pdf", "--parser", "paddle", "--output", "canonical.json"]
    )

    assert args.parser_name == "paddle"


def test_cli_disables_qwen_marker_repair_at_150_dpi_by_default():
    args = build_parser().parse_args(["ingest", "pdf", "input.pdf", "--output", "canonical.json"])

    assert args.marker_locator_repair is False
    assert args.marker_locator_page_dpi == 150


def test_cli_can_enable_qwen_marker_repair():
    args = build_parser().parse_args(
        [
            "ingest",
            "pdf",
            "input.pdf",
            "--marker-locator-repair",
            "--output",
            "canonical.json",
        ]
    )

    assert args.marker_locator_repair is True


def test_cli_accepts_shadow_output_paths_for_pdf_ingest():
    args = build_parser().parse_args(
        [
            "ingest",
            "pdf",
            "input.pdf",
            "--output",
            "canonical.json",
            "--bookgraph-output",
            "canonical_v2.json",
            "--observed-output",
            "observed_document.json",
            "--bookgraph-from-observed-output",
            "canonical_v2_observed.json",
            "--internal-canonical-output",
            "internal_canonical.json",
        ]
    )

    assert args.bookgraph_output == Path("canonical_v2.json")
    assert args.observed_output == Path("observed_document.json")
    assert args.bookgraph_from_observed_output == Path("canonical_v2_observed.json")
    assert args.internal_canonical_output == Path("internal_canonical.json")


def test_cli_pdf_ingest_passes_shadow_output_paths_to_parser(monkeypatch, tmp_path):
    captured = {}

    def fake_parse_document(request, parser_name):
        captured["parser_name"] = parser_name
        captured["options"] = dict(request.options)
        return type(
            "ParseResult",
            (),
            {
                "document": sample_document(),
                "parser": parser_name,
                "raw_output_dir": Path("/tmp/raw"),
            },
        )()

    monkeypatch.setattr("inkline.cli.main.parse_document", fake_parse_document)

    assert (
        main(
            [
                "ingest",
                "pdf",
                "input.pdf",
                "--output",
                str(tmp_path / "canonical.json"),
                "--bookgraph-output",
                str(tmp_path / "canonical_v2.json"),
                "--observed-output",
                str(tmp_path / "observed_document.json"),
                "--bookgraph-from-observed-output",
                str(tmp_path / "canonical_v2_observed.json"),
                "--internal-canonical-output",
                str(tmp_path / "internal_canonical.json"),
            ]
        )
        == 0
    )

    assert captured["parser_name"] == "mineru"
    assert captured["options"]["bookgraph_output"] == tmp_path / "canonical_v2.json"
    assert captured["options"]["observed_output"] == tmp_path / "observed_document.json"
    assert (
        captured["options"]["bookgraph_from_observed_output"]
        == tmp_path / "canonical_v2_observed.json"
    )
    assert captured["options"]["internal_canonical_output"] == tmp_path / "internal_canonical.json"


def test_cli_audits_bookgraph_shadow(tmp_path):
    canonical = tmp_path / "canonical.json"
    bookgraph = tmp_path / "canonical_v2.json"
    audit = tmp_path / "bookgraph_audit.json"
    graph = make_bookgraph(
        {
            "schema_name": BOOKGRAPH_SCHEMA_NAME,
            "schema_version": BOOKGRAPH_SCHEMA_VERSION,
            "doc_id": "sample",
            "title": "Sample",
            "language": "en",
            "source_file": "sample.pdf",
            "parser_name": "mineru",
            "parser_mode": "vlm",
        },
        [
            make_node(
                "n000001",
                "paragraph",
                "Body",
                attrs={"legacy_block_id": "b000001"},
                evidence_ids=["ev000001"],
            )
        ],
        [],
        [
            make_evidence(
                "ev000001",
                "mineru",
                "b000001",
                page=1,
                source_kind="block",
                parser_payload={"raw_type": "paragraph"},
            )
        ],
        projections={"reading_order": ["n000001"], "epub_flow": ["n000001"], "rag_units": []},
    )
    write_canonical(canonical, sample_document())
    bookgraph.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")

    assert (
        main(
            [
                "canonical",
                "audit-bookgraph",
                str(bookgraph),
                "--legacy-canonical",
                str(canonical),
                "--output",
                str(audit),
            ]
        )
        == 0
    )

    payload = json.loads(audit.read_text(encoding="utf-8"))
    assert payload["node_counts"] == {"paragraph": 1}
    assert payload["projection_diff"]["projected_block_count"] == 1
