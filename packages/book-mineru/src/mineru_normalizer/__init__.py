"""MinerU VLM to canonical normalizer."""

from .canonical.core import build_canonical, infer_doc_id
from .app.cli import main, parse_args

__all__ = ["build_canonical", "infer_doc_id", "main", "parse_args"]
