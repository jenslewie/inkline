from __future__ import annotations

import json
from pathlib import Path

from inkline.parsers.mineru.normalize import v2_page_assets

ROOT = Path(__file__).resolve().parents[5]


def test_materialize_v2_page_assets_renders_retained_and_image_region_pages(
    tmp_path, monkeypatch
) -> None:
    image_path = tmp_path / "images" / "pages" / "page_0001.png"
    second_image_path = tmp_path / "images" / "pages" / "page_0002.png"
    third_image_path = tmp_path / "images" / "pages" / "page_0003.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"page image")
    second_image_path.write_bytes(b"second page image")
    third_image_path.write_bytes(b"third page image")
    rendered_pages = []

    def render_pages(_pdf, pages, _output_dir, **_kwargs):
        rendered_pages.extend(pages)
        return {1: image_path, 2: second_image_path, 3: third_image_path}

    monkeypatch.setattr(
        v2_page_assets,
        "_render_page_assets",
        render_pages,
    )
    observed = {
        "assets": {"images": []},
        "observations": [{"kind": "image_region", "page": 3}],
    }
    page_review = {
        "pages": [
            {
                "page": 1,
                "page_role": "visual_page",
                "special_page_kind": "front_exterior_page",
                "text_flow_action": "exclude",
                "visual_asset_action": "retain",
            },
            {
                "page": 2,
                "page_role": "text_flow_page",
                "special_page_kind": None,
                "text_flow_action": "include",
                "visual_asset_action": "retain",
            },
            {
                "page": 3,
                "page_role": "text_flow_page",
                "special_page_kind": None,
                "text_flow_action": "include",
                "visual_asset_action": "not_needed",
            },
        ]
    }

    materialized = v2_page_assets.materialize_v2_page_assets(
        observed,
        page_review,
        source_pdf="sample.pdf",
        output_dir=tmp_path,
    )

    assert rendered_pages == [1, 2, 3]
    assert observed == {
        "assets": {"images": []},
        "observations": [{"kind": "image_region", "page": 3}],
    }
    assert materialized["assets"]["images"] == [
        {
            "image_id": "page-0001-review",
            "path": "images/pages/page_0001.png",
            "media_type": "image/png",
            "role": "front_exterior_page",
            "source": {"page": 1},
        },
        {
            "image_id": "page-0002-review",
            "path": "images/pages/page_0002.png",
            "media_type": "image/png",
            "role": "text_flow_page",
            "source": {"page": 2},
        },
        {
            "image_id": "page-0003-review",
            "path": "images/pages/page_0003.png",
            "media_type": "image/png",
            "role": "text_flow_page",
            "source": {"page": 3},
        },
    ]

    page_assets = v2_page_assets.materialize_v2_page_assets_value(
        observed,
        page_review,
        source_pdf="sample.pdf",
        output_dir=tmp_path,
    )

    assert page_assets == materialized["assets"]
    assert rendered_pages == [1, 2, 3, 1, 2, 3]
    assert observed == {
        "assets": {"images": []},
        "observations": [{"kind": "image_region", "page": 3}],
    }


def test_body_image_page_is_available_for_visual_relation_review() -> None:
    observed = json.loads(
        (ROOT / "data/outputs/golden/observed/丝绸之路新史_observed.json").read_text(
            encoding="utf-8"
        )
    )
    page_review = json.loads(
        (
            ROOT
            / "data/outputs/golden/page-review/丝绸之路新史/丝绸之路新史_page_review.json"
        ).read_text(encoding="utf-8")
    )
    page_25 = next(record for record in page_review["pages"] if record["page"] == 25)

    assert page_25["visual_asset_action"] == "not_needed"
    assert 25 in v2_page_assets._visual_asset_pages(observed, page_review)
