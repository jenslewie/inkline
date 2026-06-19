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
