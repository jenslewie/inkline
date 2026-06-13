from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from inkline.canonical.io import read_canonical, read_jsonl, write_canonical, write_jsonl
from inkline.epub import export_epub
from inkline.parse import ParseRequest, import_epub, parse_document
from inkline.rag.chunks import export_chunks
from inkline.rag.embeddings import OpenAIEmbeddingClient
from inkline.rag.faiss_index import build_faiss_index, load_faiss_index
from inkline.rag.search import dense_search, load_docstore
from inkline.rag.types import dataclass_to_dict


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inkline", description="Composable document parsing, export, and RAG pipeline."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Ingest source documents.")
    ingest_sub = ingest.add_subparsers(dest="kind", required=True)
    ingest_pdf = ingest_sub.add_parser("pdf", help="Ingest a PDF using a parser engine.")
    ingest_pdf.add_argument("input")
    ingest_pdf.add_argument("--parser", "--engine", dest="parser_name", default="mineru")
    ingest_pdf.add_argument("--backend", default="vlm-auto-engine", help="Parser backend option.")
    ingest_pdf.add_argument("--method", default="auto", help="Parser method option.")
    ingest_pdf.add_argument(
        "--marker-locator-repair",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use Qwen visual marker repair (disabled by default).",
    )
    ingest_pdf.add_argument(
        "--marker-locator-page-dpi",
        type=int,
        default=150,
        help="DPI for Qwen full-page marker location.",
    )
    ingest_pdf.add_argument("--output", required=True)
    ingest_pdf.set_defaults(handler=_ingest_pdf)

    import_cmd = subparsers.add_parser(
        "import", help="Import an existing document format to canonical."
    )
    import_sub = import_cmd.add_subparsers(dest="kind", required=True)
    import_epub_cmd = import_sub.add_parser("epub", help="Import EPUB to canonical.")
    import_epub_cmd.add_argument("input")
    import_epub_cmd.add_argument("--output", required=True)
    import_epub_cmd.add_argument("--doc-id")
    import_epub_cmd.add_argument("--title")
    import_epub_cmd.set_defaults(handler=_import_epub)

    export = subparsers.add_parser("export", help="Export canonical to another format.")
    export_sub = export.add_subparsers(dest="kind", required=True)
    export_epub_cmd = export_sub.add_parser("epub", help="Export canonical to EPUB.")
    export_epub_cmd.add_argument("canonical")
    export_epub_cmd.add_argument("--output", required=True)
    export_epub_cmd.set_defaults(handler=_export_epub)

    rag = subparsers.add_parser("rag", help="RAG chunking, embedding, indexing, and search.")
    rag_sub = rag.add_subparsers(dest="rag_command", required=True)
    rag_chunk = rag_sub.add_parser("chunk", help="Create chunks from canonical JSON.")
    rag_chunk.add_argument("canonical")
    rag_chunk.add_argument("--output", required=True)
    rag_chunk.set_defaults(handler=_rag_chunk)

    rag_embed = rag_sub.add_parser(
        "embed", help="Embed chunk JSONL with an OpenAI-compatible service."
    )
    rag_embed.add_argument("chunks")
    rag_embed.add_argument("--output", required=True)
    rag_embed.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    rag_embed.add_argument("--model", default="bge-m3-mlx-fp16")
    rag_embed.add_argument("--batch-size", type=int, default=32)
    rag_embed.add_argument("--timeout-seconds", type=int, default=60)
    rag_embed.set_defaults(handler=_rag_embed)

    rag_index = rag_sub.add_parser("index", help="Build a FAISS index from embedding JSONL.")
    rag_index.add_argument("embeddings")
    rag_index.add_argument("--output", required=True)
    rag_index.set_defaults(handler=_rag_index)

    rag_search = rag_sub.add_parser("search", help="Search a FAISS index.")
    rag_search.add_argument("index_dir")
    rag_search.add_argument("query")
    rag_search.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    rag_search.add_argument("--model", default="bge-m3-mlx-fp16")
    rag_search.add_argument("--top-k", type=int, default=3)
    rag_search.add_argument("--jsonl", action="store_true")
    rag_search.set_defaults(handler=_rag_search)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


def _ingest_pdf(args: argparse.Namespace) -> int:
    request = ParseRequest(
        input_path=Path(args.input),
        output_path=Path(args.output),
        options={
            "backend": args.backend,
            "method": args.method,
            "marker_locator_repair": args.marker_locator_repair,
            "marker_locator_page_dpi": args.marker_locator_page_dpi,
        },
    )
    result = parse_document(request, args.parser_name)
    write_canonical(args.output, result.document)
    print(f"Wrote canonical: {args.output}")
    return 0


def _import_epub(args: argparse.Namespace) -> int:
    document = import_epub(args.input, doc_id=args.doc_id, title=args.title)
    write_canonical(args.output, document)
    print(f"Wrote canonical: {args.output}")
    return 0


def _export_epub(args: argparse.Namespace) -> int:
    canonical_path = Path(args.canonical).resolve()
    document = read_canonical(canonical_path)
    export_epub(document, args.output, base_dir=canonical_path.parent)
    print(f"Wrote EPUB: {args.output}")
    return 0


def _rag_chunk(args: argparse.Namespace) -> int:
    document = read_canonical(args.canonical)
    count = export_chunks(document, args.output)
    print(f"Wrote chunks: {args.output} rows={count}")
    return 0


def _rag_embed(args: argparse.Namespace) -> int:
    rows = list(read_jsonl(args.chunks))
    client = OpenAIEmbeddingClient(args.base_url, args.model, timeout_seconds=args.timeout_seconds)
    output_rows: list[dict] = []
    for start in range(0, len(rows), args.batch_size):
        batch = rows[start : start + args.batch_size]
        vectors = client.embed([row["text"] for row in batch])
        output_rows.extend(
            {**row, "embedding": vector, "embedding_model": args.model}
            for row, vector in zip(batch, vectors, strict=True)
        )
    count = write_jsonl(args.output, output_rows)
    print(f"Wrote embeddings: {args.output} rows={count}")
    return 0


def _rag_index(args: argparse.Namespace) -> int:
    rows = list(read_jsonl(args.embeddings))
    vectors = [row["embedding"] for row in rows]
    docstore_rows = [
        {key: value for key, value in row.items() if key != "embedding"} for row in rows
    ]
    output_dir = Path(args.output)
    result = build_faiss_index(
        vectors,
        docstore_rows,
        output_dir / "index.faiss",
        output_dir / "docstore.jsonl",
        output_dir / "metadata.json",
    )
    print(
        f"Wrote FAISS index: {output_dir} vectors={result.vector_count} dimension={result.dimension}"
    )
    return 0


def _rag_search(args: argparse.Namespace) -> int:
    index_dir = Path(args.index_dir)
    index = load_faiss_index(index_dir / "index.faiss")
    docstore = load_docstore(index_dir / "docstore.jsonl")
    client = OpenAIEmbeddingClient(args.base_url, args.model)
    query_embedding = client.embed([args.query])[0]
    results = dense_search(index, docstore, query_embedding, args.top_k)
    if args.jsonl:
        for result in results:
            print(json.dumps(dataclass_to_dict(result), ensure_ascii=False))
    else:
        for result in results:
            print(
                f"[{result.rank}] score={result.score:.4f} {result.title} / {result.chapter_title}"
            )
            print(result.text[:500].strip())
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
