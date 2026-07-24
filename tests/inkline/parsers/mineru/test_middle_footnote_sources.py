from inkline.parsers.mineru.extraction.io import (
    footnote_blocks_from_middle,
    replace_footnote_sources_from_middle,
)
from inkline.parsers.mineru.schema.models import RawBlock


def _line(text: str) -> list[dict]:
    return [
        {
            "spans": [
                {
                    "type": "text",
                    "content": text,
                }
            ]
        }
    ]


def test_middle_ref_text_list_becomes_independent_footnote_blocks() -> None:
    middle = {
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [2000, 2500],
                "para_blocks": [
                    {
                        "type": "paragraph",
                        "lines": [
                            {
                                "spans": [
                                    {"type": "text", "content": "正文"},
                                    {"type": "inline_equation", "content": "^{1}"},
                                    {"type": "inline_equation", "content": "^{*}"},
                                ]
                            }
                        ],
                    },
                    {
                        "type": "list",
                        "sub_type": "ref_text",
                        "blocks": [
                            {
                                "type": "ref_text",
                                "index": 7,
                                "bbox": [200, 1800, 1600, 1900],
                                "lines": _line("1 第一条"),
                            },
                            {
                                "type": "ref_text",
                                "index": 8,
                                "bbox": [200, 1910, 1600, 2000],
                                "lines": _line("星号脚注"),
                            },
                        ],
                    },
                ],
                "discarded_blocks": [],
            }
        ]
    }

    blocks = footnote_blocks_from_middle(middle, {1: (2000.0, 2500.0)})

    assert [block.raw_type for block in blocks[1]] == ["ref_text", "ref_text"]
    assert [block.text for block in blocks[1]] == ["1 第一条", "星号脚注"]
    assert blocks[1][0].bbox == [100.0, 720.0, 800.0, 760.0]
    assert blocks[1][0].raw["_middle_page_inline_markers"] == ["1", "*"]


def test_middle_footnotes_replace_content_list_footnote_sources() -> None:
    pages = {
        1: [
            RawBlock(1, 0, "paragraph", "正文", [100, 100, 900, 600], {}, []),
            RawBlock(1, 1, "page_footnote", "错误脚注", [100, 800, 900, 900], {}, []),
            RawBlock(
                1,
                2,
                "list",
                "错误引用列表",
                [100, 700, 900, 800],
                {"content": {"list_type": "reference_list"}},
                [],
            ),
        ]
    }
    middle = {
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [1000, 1000],
                "para_blocks": [],
                "discarded_blocks": [
                    {
                        "type": "page_footnote",
                        "index": 3,
                        "bbox": [100, 850, 900, 900],
                        "lines": _line("1 正确脚注"),
                    }
                ],
            }
        ]
    }

    replaced = replace_footnote_sources_from_middle(pages, middle, {1: (1000.0, 1000.0)})

    assert [(block.raw_type, block.text) for block in replaced[1]] == [
        ("paragraph", "正文"),
        ("page_footnote", "1 正确脚注"),
    ]
