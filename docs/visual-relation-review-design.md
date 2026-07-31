# VisualRelationReview Before TextFlow

**Status:** Approved architecture; implementation not started.

## Decision

An image and its caption are one visual group. Inkline must establish that group
before final TextFlow materialization and before SectionMap. SectionMap may assign
an already validated visual group to a section, but it must not discover an
image-caption relation or leave caption text permanently classified as an ordinary
`display_block`.

Every builder returns a new artifact. VisualRelationReview does not modify
ObservedDocument, PageReview, or any later TextFlow. TextFlow consumes the immutable
review artifact and materializes its own caption TextUnits.

## Problem

MinerU can emit an `image_region` and one or more nearby text observations without
proving their semantic relationship. Treating those text observations as ordinary
display blocks creates three defects:

1. TextFlow claims the wrong final text type.
2. Paragraph reconciliation can mistake a caption for an independent display
   interruption without knowing which image it belongs to.
3. A later visual pass would need to reclassify or rewrite TextFlow and SectionMap,
   violating artifact immutability.

The accepted example is physical page 25 of 《丝绸之路新史》: `obs000253` is the
image, while `obs000254` and `obs000255` are the two caption parts. The three
observations must become one visual group before TextFlow assigns final `tu...`
identities.

## Inputs and Output

VisualRelationReview consumes:

- `ObservedIndex`, for parser-neutral observation identity, kind, text, page, bbox,
  and provenance;
- `PageLayoutAnalysis`, for ordered visual and text regions;
- resolved `PageReview`, for page consumption and retained-asset policy; and
- `PageAssets`, for bounded multimodal review of selected physical pages.

It emits immutable visual groups and explicit unresolved endpoints:

```json
{
  "schema_version": "0.1-shadow",
  "visual_groups": [
    {
      "visual_group_id": "vg000001",
      "asset_observation_ids": ["obs000253"],
      "caption_observation_ids": ["obs000254", "obs000255"],
      "relation_type": "caption_of",
      "physical_pages": [25],
      "evidence_ids": ["vre000001"],
      "decision_source": "multimodal_review",
      "confidence": "high"
    }
  ],
  "unpaired_asset_observation_ids": [],
  "unpaired_caption_observation_ids": [],
  "unresolved_candidates": []
}
```

The model may select only supplied observation ids. It must not transcribe or
rewrite caption text, invent an asset, merge unrelated captions, assign a section,
or create a BookGraph node.

## Candidate Selection

VisualRelationReview is not limited to PageReview `visual_page` records. It must
consider both:

- retained visual pages whose OCR is excluded from TextFlow; and
- included text-flow pages containing an `image_region` plus geometrically nearby
  caption candidates.

Deterministic candidate selection uses observation kinds, page order, bbox
adjacency, caption-role hints, and layout corridors. These signals select review
work; they do not prove the relation. Explicit parser-provided parent provenance
may establish a high-confidence relation when it references existing same-page
observations and passes validation.

The first implementation supports same-page groups. A possible cross-page relation
must remain explicit and unresolved until a later contract supports it.

## TextFlow Integration

TextFlow consumes the validated VisualRelationReview:

- caption observations materialize as `caption` TextUnits, not
  `display_block` TextUnits;
- every caption TextUnit records its `visual_group_id` and source observation ids;
- image observations do not become paragraph or display TextUnits;
- paragraph and display reconciliation may treat a validated visual group as an
  interruption, but may not absorb its caption;
- final `tu...` ids are assigned only after this classification.

`caption` therefore becomes an explicit TextFlow text type. This is a deliberate
contract change. It prevents downstream consumers from having to reinterpret an
incorrect `display_block`.

Table captions are owned by TableFlow when their parent is a structured
`table_region`. VisualRelationReview owns image, figure, chart, plate, and other
non-table visual groups. A candidate with ambiguous ownership remains unresolved
rather than appearing in both artifacts.

## SectionMap Integration

SectionMap consumes validated visual groups in addition to TextFlow:

- it may assign a `visual_group_id` and its caption TextUnit ids to a section when
  membership evidence is sufficient;
- it may leave a group standalone or unresolved;
- it must not infer `caption_of`, reclassify a caption, or attach a bare image merely
  because it lies between two section pages.

BookGraph assembly later projects the group into an asset node, caption node or
caption text representation, and a `caption_of` edge. It does not modify
VisualRelationReview, TextFlow, or SectionMap.

## Validation and Acceptance

Validation requires:

- every endpoint exists in ObservedIndex;
- asset endpoints are compatible visual observations;
- caption endpoints are text observations and are not owned by another visual or
  table group;
- every endpoint page is allowed by the supported relation scope;
- every relation has evidence, decision source, and confidence;
- unpaired and unresolved endpoints remain explicit;
- no downstream artifact mutates the review output.

Acceptance includes:

1. `obs000253` plus `obs000254` and `obs000255` on page 25 of
   《丝绸之路新史》 form one visual group and caption TextUnit.
2. Body paragraphs interrupted by that group reconcile only when their own geometry
   proves continuation; the caption remains independent.
3. Multiple images and multiple caption candidates on one page are not paired by
   nearest-distance alone.
4. An unpaired image and an unpaired caption remain visible in the audit.
5. A PageReview-excluded plate can form a visual group without leaking its OCR into
   ordinary TextFlow.
6. No note marker, note definition, or note-reference relation is processed here.

## Non-goals

- Note detection or reference resolution.
- General OCR repair or image description generation.
- Section ownership.
- Table reconstruction or table-caption ownership.
- Cross-page visual relations in the initial contract.
- EPUB, RAG, or public BookGraph projection.
