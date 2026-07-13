from __future__ import annotations

from inkline.parsers.mineru.normalize import v2_page_assets


def test_materialize_v2_page_assets_renders_all_retained_visual_pages(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "images" / "pages" / "page_0001.png"
    second_image_path = tmp_path / "images" / "pages" / "page_0002.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"page image")
    second_image_path.write_bytes(b"second page image")
    monkeypatch.setattr(
        v2_page_assets,
        "_render_page_assets",
        lambda *_args, **_kwargs: {1: image_path, 2: second_image_path},
    )
    observed = {"assets": {"images": []}}
    page_review = {
        "pages": [
            {
                "page": 1,
                "page_role": "cover_page",
                "text_flow_action": "exclude",
                "visual_asset_action": "retain",
            },
            {
                "page": 2,
                "page_role": "front_text_page",
                "text_flow_action": "include",
                "visual_asset_action": "retain",
            },
        ]
    }

    materialized = v2_page_assets.materialize_v2_page_assets(
        observed,
        page_review,
        source_pdf="sample.pdf",
        output_dir=tmp_path,
    )

    assert observed == {"assets": {"images": []}}
    assert materialized["assets"]["images"] == [
        {
            "image_id": "page-0001-review",
            "path": "images/pages/page_0001.png",
            "media_type": "image/png",
            "role": "cover_page",
            "source": {"page": 1},
        },
        {
            "image_id": "page-0002-review",
            "path": "images/pages/page_0002.png",
            "media_type": "image/png",
            "role": "front_text_page",
            "source": {"page": 2},
        },
    ]
