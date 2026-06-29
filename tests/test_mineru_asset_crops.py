from __future__ import annotations


def test_expand_rect_continues_when_visible_content_touches_search_edge() -> None:
    import fitz  # type: ignore

    from inkline.parsers.mineru.normalize.assets import _expand_rect_to_visible_content

    doc = fitz.open()
    page = doc.new_page(width=220, height=240)
    try:
        page.draw_rect(fitz.Rect(20, 170, 180, 188), color=(0, 0, 0), fill=(0, 0, 0))
        rect = fitz.Rect(20, 20, 180, 150)

        expanded = _expand_rect_to_visible_content(page, rect)

        assert expanded.y1 >= 188
    finally:
        doc.close()


def test_expand_rect_stops_before_large_unrelated_content() -> None:
    import fitz  # type: ignore

    from inkline.parsers.mineru.normalize.assets import _expand_rect_to_visible_content

    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    try:
        page.draw_rect(fitz.Rect(0, 0, 400, 400), color=(0, 0, 0), fill=(0, 0, 0))
        rect = fitz.Rect(100, 100, 200, 200)

        expanded = _expand_rect_to_visible_content(page, rect)

        assert expanded == rect
    finally:
        doc.close()


def test_repaired_figure_asset_overwrites_stale_crop(tmp_path) -> None:
    import fitz  # type: ignore

    from inkline.parsers.mineru.normalize.assets import materialize_repaired_figure_image_assets

    pdf_path = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=220, height=240)
    page.draw_rect(fitz.Rect(20, 170, 180, 188), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf_path)
    doc.close()

    stale_path = tmp_path / "images" / "repaired" / "fig_page_0001.png"
    stale_path.parent.mkdir(parents=True)
    stale_path.write_bytes(b"stale")
    canonical = {
        "blocks": [
            {
                "block_id": "fig",
                "type": "figure",
                "source": {"page": 1, "bbox": [20, 20, 180, 150]},
                "attrs": {
                    "sub_type": "text_image",
                    "embedded_text_absorb_reason": "following_visual_legend_strip",
                },
            }
        ]
    }

    materialize_repaired_figure_image_assets(
        canonical,
        str(pdf_path),
        tmp_path,
        page_sizes={1: (220, 240)},
        dpi=72,
    )

    assert stale_path.read_bytes().startswith(b"\x89PNG")
    attrs = canonical["blocks"][0]["attrs"]
    assert attrs["image_render_bbox"][3] >= 188


def test_page_snapshot_asset_uses_relative_path(tmp_path) -> None:
    import fitz  # type: ignore

    from inkline.parsers.mineru.normalize.assets import materialize_page_snapshot_assets

    pdf_path = tmp_path / "source.pdf"
    doc = fitz.open()
    doc.new_page(width=220, height=240)
    doc.save(pdf_path)
    doc.close()
    canonical = {
        "blocks": [],
        "pages": [
            {
                "physical_page": 1,
                "snapshot": {"required": True, "role": "page_snapshot"},
            }
        ],
    }

    materialize_page_snapshot_assets(canonical, str(pdf_path), tmp_path, dpi=72)

    image_asset = canonical["assets"]["images"][0]
    assert image_asset["path"] == "images/pages/page_0001.png"


def test_asset_relative_path_resolves_relative_to_output_dir(tmp_path, monkeypatch) -> None:
    from inkline.parsers.mineru.normalize.assets import _asset_path_relative_to_output_dir

    output_dir = tmp_path / "results"
    output_dir.mkdir()
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    monkeypatch.chdir(work_dir)

    relative = _asset_path_relative_to_output_dir("images/pages/page_0001.png", output_dir)

    assert relative == "images/pages/page_0001.png"


def test_dense_text_image_can_repair_missing_visible_edge(tmp_path) -> None:
    import fitz  # type: ignore

    from inkline.parsers.mineru.normalize.assets import materialize_repaired_figure_image_assets

    pdf_path = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=220, height=240)
    page.draw_rect(fitz.Rect(20, 170, 180, 188), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf_path)
    doc.close()

    canonical = {
        "blocks": [
            {
                "block_id": "fig",
                "type": "figure",
                "source": {"page": 1, "bbox": [20, 20, 180, 150]},
                "attrs": {
                    "sub_type": "text_image",
                    "image_path": "images/original.jpg",
                    "ocr_text_in_image": "\n".join(f"地名{i}" for i in range(20)),
                },
            }
        ]
    }

    materialize_repaired_figure_image_assets(
        canonical,
        str(pdf_path),
        tmp_path,
        page_sizes={1: (220, 240)},
        dpi=72,
    )

    attrs = canonical["blocks"][0]["attrs"]
    assert attrs["image_path"] == "images/repaired/fig_page_0001.png"
    assert attrs["original_image_path"] == "images/original.jpg"
    assert attrs["image_render_bbox"][3] >= 188
    image_asset = canonical["assets"]["images"][0]
    assert image_asset["path"] == "images/repaired/fig_page_0001.png"
    from PIL import Image

    with Image.open(tmp_path / attrs["image_path"]) as repaired:
        assert repaired.mode == "L"


def test_dense_text_image_repair_trims_blank_below_bottom_rule(tmp_path) -> None:
    import fitz  # type: ignore

    from inkline.parsers.mineru.normalize.assets import materialize_repaired_figure_image_assets

    pdf_path = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=1100, height=1100)
    page.draw_line(fitz.Point(160, 100), fitz.Point(160, 795), color=(0, 0, 0), width=1)
    page.draw_line(fitz.Point(998, 100), fitz.Point(998, 950), color=(0, 0, 0), width=1)
    page.draw_rect(fitz.Rect(160, 790, 998, 795), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf_path)
    doc.close()

    canonical = {
        "blocks": [
            {
                "block_id": "fig",
                "type": "figure",
                "source": {"page": 1, "bbox": [160, 100, 998, 700]},
                "attrs": {
                    "sub_type": "text_image",
                    "image_path": "images/original.jpg",
                    "ocr_text_in_image": "\n".join(f"地名{i}" for i in range(20)),
                },
            }
        ]
    }

    materialize_repaired_figure_image_assets(
        canonical,
        str(pdf_path),
        tmp_path,
        page_sizes={1: (1100, 1100)},
        dpi=72,
    )

    attrs = canonical["blocks"][0]["attrs"]
    assert attrs["image_render_bbox"][3] >= 795
    assert attrs["image_render_bbox"][3] <= 805


def test_repaired_figure_asset_preserves_color_when_content_is_color(tmp_path) -> None:
    import fitz  # type: ignore

    from inkline.parsers.mineru.normalize.assets import materialize_repaired_figure_image_assets

    pdf_path = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=220, height=240)
    page.draw_rect(fitz.Rect(20, 20, 180, 188), color=(0.8, 0.1, 0.0), fill=(0.8, 0.1, 0.0))
    doc.save(pdf_path)
    doc.close()

    canonical = {
        "blocks": [
            {
                "block_id": "fig",
                "type": "figure",
                "source": {"page": 1, "bbox": [20, 20, 180, 188]},
                "attrs": {
                    "sub_type": "image",
                    "image_path": "images/original.jpg",
                    "fragment_block_ids": ["caption"],
                },
            }
        ]
    }

    materialize_repaired_figure_image_assets(
        canonical,
        str(pdf_path),
        tmp_path,
        page_sizes={1: (220, 240)},
        dpi=72,
    )

    attrs = canonical["blocks"][0]["attrs"]
    from PIL import Image

    with Image.open(tmp_path / attrs["image_path"]) as repaired:
        assert repaired.mode == "RGB"
