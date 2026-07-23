"""LLM request construction for bounded semantic page review."""

from __future__ import annotations

import json
from typing import Any

PAGE_REVIEW_PROMPT_VERSION = "4.2-genealogy-chart"

_PROMPT_PROFILES = {
    "front_special",
    "front_visual_identity",
    "after_front_exterior",
    "after_back_exterior",
    "after_dust_jacket_spread",
    "after_decorative_preliminary",
    "after_title_page",
    "front_residual_unknown",
    "body_section_start",
    "visual_sparse_text",
    "mixed_visual_body",
    "textual_table",
    "general",
}

def page_review_prompt_profile(page_record: dict[str, Any]) -> str:
    """Select one focused visual-review instruction profile from structural evidence."""

    context = page_record.get("skeleton_context") or {}
    signals = set(page_record.get("signals") or [])
    visual_kinds = set(page_record.get("visual_kinds") or [])
    if context.get("matter") == "pre_body":
        has_visual_evidence = bool(visual_kinds) or "raster_dark_visual_layout" in signals
        return "front_visual_identity" if has_visual_evidence else "front_special"
    if "table_region" in visual_kinds:
        return "textual_table"
    if "image_region" in visual_kinds:
        return "mixed_visual_body" if "body_profile" in signals else "visual_sparse_text"
    if context.get("is_body_section_start") is True:
        return "body_section_start"
    if "visual_sparse_text" in signals:
        return "visual_sparse_text"
    if "visual_verifier_candidate" in signals:
        return "mixed_visual_body"
    return "general"

def page_review_llm_prompt(input_data: dict[str, Any], *, profile: str = "general") -> str:
    """Compose a short common contract with one focused visual-review profile."""

    if profile not in _PROMPT_PROFILES:
        raise ValueError(f"unknown page review prompt profile: {profile}")
    return (
        "Classify selected book pages. The input is structural evidence, not a prior decision.\n"
        "Only classify the supplied candidate pages. Do not add, omit, or reorder pages. "
        "Do not change the front/body/back boundary.\n"
        "Return strict JSON only:\n"
        "{\n"
        '  "page_reviews": [\n'
        "    {\n"
        '      "page": 1,\n'
        '      "page_role": "visual_page",\n'
        '      "book_block_position": "unknown",\n'
        '      "special_page_kind": null,\n'
        '      "text_flow_action": "exclude",\n'
        '      "visual_asset_action": "retain",\n'
        '      "confidence": "high"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "page_role must be one of: text_flow_page, visual_page.\n"
        "book_block_position must be one of: external_wrap, front_matter, body, back_matter, unknown. "
        "Use external_wrap only for a cover, back cover, or cover flap that belongs to the outer "
        "binding rather than the book block. Use front_matter for a book-internal preliminary page. "
        "Required pairs: front_exterior_page/back_exterior_page/cover_flap/dust_jacket_spread -> external_wrap; "
        "half_title_page/title_page/decorative_preliminary_page/decorative_title_page/epigraph_page/dedication_page/acknowledgments_page/copyright_page/toc_page/blank_page -> front_matter.\n"
        "For copyright_page, use visual_page, front_matter, metadata_only, and retain.\n"
        "special_page_kind must be one of: front_exterior_page, back_exterior_page, cover_flap, dust_jacket_spread, half_title_page, "
        "title_page, decorative_preliminary_page, decorative_title_page, epigraph_page, dedication_page, acknowledgments_page, copyright_page, toc_page, blank_page, plate_page, chronology_chart_page, genealogy_chart_page, or null. It describes a special "
        "page identity and must not be used for ordinary body pages. When it is absent, emit the JSON "
        "literal null without quotes, never the string \\\"null\\\".\n"
        "text_flow_action must be one of: include, exclude, metadata_only, needs_review.\n"
        "visual_asset_action must be one of: retain, not_needed, needs_review.\n"
        "confidence must be one of: high, medium, low.\n\n"
        f"Review profile: {profile}.\n"
        f"Profile instruction: {_profile_instruction(profile)}\n"
        "- text_flow_action=include: the page OCR text remains eligible for reading-flow nodes.\n"
        "- text_flow_action=exclude: do not turn page OCR text into reading-flow nodes.\n"
        "- visual_page must use text_flow_action=exclude. Captions and labels alone are not "
        "independent body paragraphs.\n"
        "- text_flow_action=metadata_only: retain page evidence only for later metadata extraction.\n"
        "- visual_asset_action=retain: preserve a rendered page image as a v2 asset, independently "
        "of whether text remains in reading flow.\n"
        "- visual_asset_action=not_needed: no rendered full-page visual asset is needed.\n"
        "- needs_review: visual evidence remains insufficient.\n\n"
        "Every page_reviews item must contain exactly these keys and no others: page, page_role, "
        "book_block_position, special_page_kind, text_flow_action, visual_asset_action, confidence. In particular, use page rather than "
        "page_number; do not emit image quality scores, descriptions, explanations, or analyses.\n\n"
        "Use the page image and structural signals as evidence. Each request carries one physical page image. "
        "The optional preceding_page_decision supplies only its resolved structural identity; it never justifies "
        "dust_jacket_spread, which must be visible within the one page image. Do not infer a page role from the "
        "meaning of OCR text alone.\n\n"
        f"Input JSON:\n{json.dumps(input_data, ensure_ascii=False, indent=2)}"
    )


def _profile_instruction(profile: str) -> str:
    instructions = {
        "front_special": (
            "This is a pre-body physical range, not a claim that every page is front matter. Identify "
            "external-wrap pages (front exterior, back exterior, or cover flap) separately from book-block pages "
            "(half title, title, dedication, acknowledgments, copyright, TOC, or blank). "
            "A sparse standalone quotation or maxim with an attribution is epigraph_page, not dedication_page; "
            "it uses visual_page/exclude/retain. "
            "A sparse centered page dedicating the book to a person or memory is dedication_page. "
            "A page headed Acknowledgments, Acknowledgements, 致谢, or 鸣谢 is acknowledgments_page, not "
            "dedication_page; it is ordinary front prose and uses text_flow_page/include/not_needed. "
            "A bibliographic title page presents the book title together with one or more publication details such "
            "as author, translator, edition, publisher, or imprint; classify it as title_page with "
            "front_matter/visual_page/exclude/retain. "
            "A back exterior can appear near the PDF beginning, but requires a rear panel such as ISBN, price, barcode, "
            "or a full back-cover blurb. A narrow folded cover panel with author biography, publisher/contact "
            "details, or a QR code is cover_flap rather than back_exterior_page. When a sequence is front exterior, panel, "
            "barcode back cover, panel, both panels are cover_flap. External-wrap pages use "
            "visual_page/exclude/retain. A flattened image showing a whole dust jacket with front cover, "
            "back cover, spine, and one or more flaps is dust_jacket_spread, not cover_flap. "
            "Classify every supplied physical page independently; do not infer a jacket spread from neighboring pages "
            "in the group. Before choosing dust_jacket_spread, verify all four required elements are visibly present "
            "in the same image: front-cover design, back-cover design, book spine, and one or more jacket flaps, with "
            "folds or panel boundaries. If any required element is absent or uncertain, dust_jacket_spread is invalid. "
            "Do not use it merely because a single page has a cover design, ISBN, barcode, QR code, or publisher blurb. "
            "A standalone front exterior design is front_exterior_page; a standalone rear panel with a blurb, barcode, "
            "ISBN, or price is back_exterior_page. Do not guess whether either surface is a paperback cover or a hardcover "
            "board: the PDF image does not establish that material without explicit evidence."
        ),
        "front_visual_identity": (
            "This pre-body page has image-region evidence. First distinguish an outer binding surface from an internal "
            "plate or decorative preliminary leaf. A front-facing external design is front_exterior_page; a rear external panel with a blurb, barcode, "
            "ISBN, price, or publisher mark is back_exterior_page. These use external_wrap/visual_page/exclude/retain. "
            "A designed ornament, patterned sheet, or texture-only preliminary leaf is decorative_preliminary_page. "
            "A decorative title-like leaf that is not the bibliographic title page is decorative_title_page. Both use "
            "front_matter/visual_page/exclude/retain. "
            "A book-internal leaf that shows only the book title, without author, publisher, or bibliographic details, "
            "is half_title_page, not decorative_preliminary_page. "
            "Do not call an exterior surface a plate_page merely because it is visual. Do not guess whether an exterior "
            "surface is a paperback cover or a hardcover board. A plate_page is "
            "a page principally occupied by a photograph, artwork, map, facsimile, or other printed illustration, "
            "with current-page evidence that it is internal: a plate number, caption or labels tied to the image, "
            "or a visibly printed interior plate-series form. Image dominance alone is insufficient. Use "
            "plate_page with visual_page/exclude/retain. Do not require MinerU to have linked a caption to its image. "
            "If independent continuous prose shares the page, do not use plate_page; keep its text in reading flow. "
            "A genealogy or dynastic family tree is genealogy_chart_page, not chronology_chart_page, when named boxes "
            "or labels are connected by parent-child, lineage, or generational branches. Date ranges on people or rulers "
            "do not turn that hierarchy into a chronology. It uses visual_page/exclude/retain pending structured "
            "genealogy extraction. A date-organized timeline, chronology, or historical chart is chronology_chart_page, "
            "not plate_page or genealogy_chart_page, when the page image has a time axis, dated rows, dated events, or chart-like "
            "chronological organization without a parent-child or lineage hierarchy. This remains "
            "visual_page/exclude/retain pending structured chart extraction. "
            "If the page could equally be exterior artwork or an internal plate and neither identity is established "
            "on this page, you MUST use special_page_kind=null and book_block_position=unknown, never front_matter. "
            "Use visual_page/exclude/retain and low confidence."
        ),
        "after_front_exterior": (
            "The immediately preceding physical page was resolved as front_exterior_page. Decide whether this current "
            "page is another front-facing exterior surface, a front cover flap, or a rear exterior. A full-page cover-style composition with "
            "a large display book title integrated into its ornamental design is front_exterior_page, even when it has "
            "no author, publisher, ISBN, or blurb. Do not call that composition decorative_title_page. Use "
            "a book-internal decorative leaf for an interior page after the exterior binding: when its visible purpose "
            "is an ornamental title treatment, use decorative_title_page; when it is only pattern or texture without "
            "a title treatment, use decorative_preliminary_page. "
            "cover_flap for an outer narrow panel with an author biography, publisher details, contact information, "
            "or a QR code. A cover_flap remains external_wrap/visual_page/exclude/retain even when it contains prose. "
            "back_exterior_page only for a rear-facing panel such as a blurb, barcode, ISBN, price, or publisher mark. "
            "Do not infer a dust jacket, hardcover board, or paperback material from this sequence."
        ),
        "after_back_exterior": (
            "The immediately preceding physical page was resolved as back_exterior_page. This current page may be the "
            "rear cover flap rather than a second back exterior. Use cover_flap for an outer narrow panel with publisher "
            "contact information, a QR code, an author biography, or other flap copy. It remains "
            "external_wrap/visual_page/exclude/retain even when it contains prose. Use back_exterior_page only when this "
            "page itself is a full rear-cover panel, not merely because it has a QR code or publisher mark. Do not infer "
            "a dust jacket, hardcover board, or paperback material from this sequence."
        ),
        "after_dust_jacket_spread": (
            "The immediately preceding physical page was resolved as dust_jacket_spread. This current page may be "
            "the book's exposed front exterior after that removable jacket is opened or removed. A full-page "
            "cover-style composition, including one with only a title integrated into its design, is "
            "front_exterior_page with external_wrap/visual_page/exclude/retain, not title_page merely because it "
            "displays the book title. Use title_page only for a bibliographic title page that presents the title "
            "as internal publication information rather than as a cover-style surface. For that cover-style case, "
            "return {\"page_role\": \"visual_page\", \"book_block_position\": \"external_wrap\", "
            "\"special_page_kind\": \"front_exterior_page\", \"text_flow_action\": \"exclude\", "
            "\"visual_asset_action\": \"retain\"}. Do not infer hardcover or "
            "paperback material from this sequence."
        ),
        "after_decorative_preliminary": (
            "The immediately preceding physical page was resolved as decorative_preliminary_page. If this page shows "
            "only the book title, without author, publisher, edition, or bibliographic details, you MUST use "
            "half_title_page with front_matter/visual_page/exclude/retain. Do not call it decorative_preliminary_page "
            "merely because it also has ornamentation. A further patterned, textured, or intentionally blank leaf "
            "without a title treatment remains decorative_preliminary_page with front_matter/visual_page/exclude/retain."
        ),
        "after_title_page": (
            "The immediately preceding physical page was resolved as title_page. A subsequent decorative page that "
            "repeats a title or uses an ornamental title treatment is decorative_title_page, not another title_page. "
            "Use title_page only for the book's bibliographic title page itself."
        ),
        "front_residual_unknown": (
            "This pre-body page was not localized by a TOC section boundary and remains unresolved after "
            "the initial visual review selection. Decide whether it belongs to the external binding or the "
            "internal front matter. A normal reading-flow text page inside the book block is front_matter, "
            "text_flow_page, include, and not_needed. Do not use title_page merely because a page has a "
            "heading. A page containing CIP, ISBN, copyright notice, edition, printing, publisher, or imprint "
            "is copyright_page with visual_page/front_matter/metadata_only/retain, not normal reading flow. "
            "A sparse standalone quotation or maxim with an attribution is epigraph_page and uses "
            "visual_page/exclude/retain. "
            "A sparse centered page, or a page whose only text dedicates or memorializes the book to a person "
            "or memory, is dedication_page and uses visual_page/exclude/retain even when it has several sentences. "
            "Use external_wrap only for an actual front exterior, back exterior, or cover flap."
        ),
        "body_section_start": (
            "Every page is a TOC-confirmed body-section start. Return text_flow_page, "
            "special_page_kind=null, and text_flow_action=include; its heading belongs in reading flow."
        ),
        "visual_sparse_text": (
            "visual_sparse_text means a visual asset has no body-text profile. Return "
            "visual_page/exclude/retain unless the image visibly contains a continuous narrative paragraph. "
            "Labels, legends, place names, and captions are not narrative paragraphs."
        ),
        "mixed_visual_body": (
            "Use an inclusion-first decision. A continuous body paragraph wins over visual area. "
            "Return text_flow_page/include when a map, image, or diagram shares the page with "
            "independent continuous body prose, even when the visual occupies most of the page. "
            "A narrow explanatory block directly attached to an image is a caption, even when it has "
            "multiple lines; it is not body prose. Return visual_page/exclude only when every readable "
            "text region is a caption, legend, place name, or label."
        ),
        "textual_table": (
            "A table_region is presumed to be a readable cell-based table or its continuation. Return "
            "text_flow_page/include, including when the table fills the page. Return visual_page/exclude "
            "only when the apparent table has labels or captions but no readable rows, columns, or cells."
        ),
        "general": (
            "Return text_flow_page/include for independent body prose; otherwise return visual_page/exclude "
            "for a visual with only labels or captions."
        ),
    }
    return instructions[profile]
