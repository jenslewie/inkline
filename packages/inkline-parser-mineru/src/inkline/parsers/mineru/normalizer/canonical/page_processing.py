"""Page processing re-export hub. The canonical pipeline imports process_page, build_toc_from_blocks, and extend_table_source_pages from here. Actual implementations live in page_handlers and normal_flow."""

from __future__ import annotations

from .page_handlers import build_toc_from_blocks, extend_table_source_pages, process_page

__all__ = ["build_toc_from_blocks", "extend_table_source_pages", "process_page"]
