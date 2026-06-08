"""Data classes and constants shared across the Qwen marker locator sub-modules.

Contains the configuration dataclass, evidence dataclass, and the prompt
constants that both depend on.  No imports from other ``qwen_*`` modules —
this is the leaf of the dependency graph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


_PUNCTUATION_BOUNDARY_INSTRUCTION = (
    "这里的标点包括中文和英文的句号、逗号、顿号、分号、冒号、问号、叹号，以及紧邻正文的右括号、右引号、书名号。"
    "不要为了凑2到8个字符而跳过紧邻标点；标点如果紧贴marker，就必须出现在对应的before_text或after_text里。"
)
_BODY_REFS_PROMPT = (
    "/no_think\n"
    "只返回JSON，不要解释。只在脚注分隔横线以上的正文区域识别脚注引用marker，不要识别页底脚注定义。"
    "marker只允许数字或*,**,***。正文marker必须是小号上标或紧贴正文的脚注符号。"
    "before_text必须是marker左侧紧邻的2到8个原文字符，并以marker左边那个字符结尾；"
    "after_text必须是marker右侧紧邻的2到8个原文字符，并以marker右边那个字符开头。"
    "如果marker右边紧邻标点，after_text必须以该标点开头；如果marker左边紧邻标点，before_text必须以该标点结尾。"
    + _PUNCTUATION_BOUNDARY_INSTRUCTION +
    "quote必须等于连续原文片段 before_text + marker + after_text，多个marker相邻时必须保留相对位置。"
    "格式:"
    "{\"body_refs\":[{\"marker\":\"\",\"before_text\":\"\",\"after_text\":\"\",\"quote\":\"\",\"confidence\":\"high|medium|low\"}]}。"
    "看不清或无法确定紧邻字符就省略该项。"
)
_FOOTNOTE_DEFS_PROMPT = (
    "/no_think\n"
    "只返回JSON，不要解释。只识别页底脚注列表，不要识别正文。"
    "请从脚注分隔横线下方开始，逐行列出所有脚注定义开头的marker，包括星号*,**,***和数字1,2,3。"
    "特别注意：数字脚注1之前如果还有一条星号脚注，也必须列出。"
    "输出格式:"
    "{\"footnote_defs\":[{\"marker\":\"\",\"near_text\":\"\",\"confidence\":\"high|medium|low\"}]}。"
    "near_text填写该脚注marker后面的开头文字。"
    "看不清或无法确定紧邻字符就省略该项。"
)
_PROMPT_VERSION = 6
_VALID_MARKER_RE = re.compile(r"^(?:\d{1,3}|\*{1,3})$")
_BODY_REF_BLOCK_TYPES = {"paragraph", "display_block", "blockquote", "caption", "epigraph_group"}
_PARAGRAPH_CROP_PADDING_PDF = 12.0


@dataclass(frozen=True)
class QwenMarkerLocatorConfig:
    source_pdf: Path
    artifact_dir: Path
    model: str = "qwen3.5:9b"
    api_url: str = "http://127.0.0.1:11434/api/chat"
    dpi: int = 200
    page_dpi: int = 300
    block_dpi: int = 200
    max_megapixels: float = 0.0
    body_prompt: str = _BODY_REFS_PROMPT
    footnote_prompt: str = _FOOTNOTE_DEFS_PROMPT
    body_mode: str = "page_then_block"
    reuse_evidence: bool = False
    timeout_seconds: int = 180
    keep_alive: str = "2h"
    timing_log_path: Path | None = None


@dataclass
class QwenMarkerPageEvidence:
    page: int
    image: str
    crop_bbox_pdf: List[float]
    dpi: int
    raw_json: Dict[str, Any]
    body_refs: List[Dict[str, Any]] = field(default_factory=list)
    footnote_defs: List[Dict[str, Any]] = field(default_factory=list)
    prompt_version: int = _PROMPT_VERSION

    @property
    def kind(self) -> str:
        return "full_page"

    def to_json(self) -> Dict[str, Any]:
        return {
            "page": self.page,
            "kind": self.kind,
            "image": self.image,
            "crop_bbox_pdf": self.crop_bbox_pdf,
            "dpi": self.dpi,
            "raw_json": self.raw_json,
            "body_refs": self.body_refs,
            "footnote_defs": self.footnote_defs,
            "prompt_version": self.prompt_version,
        }