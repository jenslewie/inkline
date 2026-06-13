"""Regex patterns for text classification. Defines TOC_LINE_RE, CHAPTER_RE, PART_RE, CN_LIST_ITEM_RE, ATTR_RE (attribution line), and CHINESE_RE. Used by page processing and reconciliation passes for structural text matching."""

from __future__ import annotations

import re

ATTR_RE = re.compile(r"^\s*[—－–-]{1,4}\s*(.+?)\s*$")
PAGE_NUM_RE = re.compile(r"^\s*[.·。]?\s*\d+\s*$")
TRAILING_NOTE_RE = re.compile(r"(?P<body>.*?)(?P<note>\s*(?:\*{1,3}|\d{1,3}|[¹²³⁴⁵⁶⁷⁸⁹⁰]+))\s*$")
EQUATION_NOTE_RE = re.compile(r"\^\{([^}]+)\}")
NOTE_MARKER_RE = re.compile(r"^(?:\d{1,3}[*＊]{0,3}|[*＊]{1,3})$")
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
TOC_LINE_RE = re.compile(r"^(?P<title>.+?)\s*(?:[/／]+|\s+)\s*(?P<page>\d{1,4})\s*$")
PART_RE = re.compile(r"^第[一二三四五六七八九十百]+部分")
CHAPTER_RE = re.compile(
    r"^(?P<num>\d+|[IiVvXxLl]+|[一二三四五六七八九十百]+)[\s、.．]*(?P<title>.+)"
)
CN_LIST_ITEM_RE = re.compile(r"^\s*[一二三四五六七八九十百]+、")
