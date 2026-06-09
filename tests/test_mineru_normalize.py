from __future__ import annotations

import json

from inkline.canonical import validate_document
from inkline.parsers.mineru import normalize_mineru_outputs


def test_normalize_mineru_outputs_produces_valid_canonical(tmp_path) -> None:
    content_list_v2 = tmp_path / "sample_content_list_v2.json"
    middle = tmp_path / "sample_middle.json"
    output = tmp_path / "canonical.json"
    content_list_v2.write_text(
        json.dumps(
            [
                [
                    {
                        "type": "paragraph",
                        "bbox": [100, 100, 900, 180],
                        "content": {"text": "A minimal MinerU paragraph."},
                    }
                ]
            ]
        ),
        encoding="utf-8",
    )
    middle.write_text(
        json.dumps({"pdf_info": [{"page_size": [1000, 1400]}]}),
        encoding="utf-8",
    )

    document = normalize_mineru_outputs(
        content_list_v2=content_list_v2,
        middle=middle,
        markdown=None,
        source_pdf=None,
        output=output,
        doc_id="sample",
        title="Sample",
        language="en",
    )

    validate_document(document)
    assert document["metadata"]["parser_name"] == "mineru"
    assert document["metadata"]["schema_version"] == "1.0"
    assert output.exists()
