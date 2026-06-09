from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Any
import hashlib
import re
import zipfile

from inkline.canonical.schema import make_block, make_document, make_toc_entry


def import_epub(path: str | Path, *, doc_id: str | None = None, title: str | None = None) -> dict[str, Any]:
    epub_path = Path(path)
    if not epub_path.exists():
        raise FileNotFoundError(epub_path)

    book_id = doc_id or _safe_doc_id(epub_path)
    metadata = _read_package_metadata(epub_path)
    book_title = title or metadata.get("title") or epub_path.stem
    language = metadata.get("language") or "und"
    author = metadata.get("creator")

    blocks: list[dict[str, Any]] = []
    toc: list[dict[str, Any]] = []
    block_no = 1
    with zipfile.ZipFile(epub_path) as archive:
        for spine_index, name in enumerate(_content_documents(archive), start=1):
            html = archive.read(name).decode("utf-8", errors="replace")
            parsed = _TextHTMLParser()
            parsed.feed(html)
            chapter_title = parsed.title or f"Section {spine_index}"
            heading_id = f"b{block_no:06d}"
            blocks.append(make_block(heading_id, "heading", chapter_title, level=1, attrs={"source_href": name}))
            toc.append(make_toc_entry(chapter_title, level=1, block_id=heading_id))
            block_no += 1
            for paragraph in parsed.paragraphs:
                if paragraph.strip():
                    blocks.append(
                        make_block(
                            f"b{block_no:06d}",
                            "paragraph",
                            paragraph.strip(),
                            attrs={"source_href": name, "spine_order": spine_index},
                        )
                    )
                    block_no += 1

    return make_document(
        doc_id=book_id,
        title=book_title,
        author=author,
        language=language,
        source_file=str(epub_path),
        parser_name="epub_importer",
        parser_mode="standard_library",
        blocks=blocks,
        toc=toc,
    )


def _content_documents(archive: zipfile.ZipFile) -> list[str]:
    names = archive.namelist()
    html_names = [
        name
        for name in names
        if name.lower().endswith((".xhtml", ".html", ".htm"))
        and not name.lower().endswith("nav.xhtml")
        and "cover" not in Path(name).stem.lower()
    ]
    return sorted(html_names)


def _read_package_metadata(epub_path: Path) -> dict[str, str]:
    try:
        with zipfile.ZipFile(epub_path) as archive:
            opf_name = next((name for name in archive.namelist() if name.lower().endswith(".opf")), None)
            if opf_name is None:
                return {}
            opf = archive.read(opf_name).decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        raise ValueError(f"Invalid EPUB file: {epub_path}") from None

    metadata: dict[str, str] = {}
    for key in ("title", "language", "creator"):
        match = re.search(rf"<dc:{key}[^>]*>(.*?)</dc:{key}>", opf, flags=re.IGNORECASE | re.DOTALL)
        if match:
            metadata[key] = _collapse_ws(re.sub("<[^>]+>", "", match.group(1)))
    return metadata


def _safe_doc_id(path: Path) -> str:
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:10]
    stem = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", path.stem).strip("_")
    return f"{stem or 'epub'}_{digest}"


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.paragraphs: list[str] = []
        self._stack: list[str] = []
        self._buffer: list[str] = []
        self._heading_seen = False

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"p", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush()
            self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"p", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}:
            text = self._flush()
            if text and tag.startswith("h") and not self._heading_seen:
                self.title = text
                self._heading_seen = True
            elif text:
                self.paragraphs.append(text)
            if self._stack:
                self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._stack:
            self._buffer.append(data)

    def _flush(self) -> str:
        text = _collapse_ws("".join(self._buffer))
        self._buffer = []
        return text
