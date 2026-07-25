# Visual Caption Anchor Evidence Design

## Goal

Keep visual resources, their captions, and BookSkeleton section-start evidence as separate, traceable facts.

## Decisions

- Every MinerU table/chart caption becomes a separate `text_region` observation with `role_hint: "caption_text"`.
- Existing `table_region` and `image_region` observations remain unchanged. New caption observations are appended after existing observations so existing IDs remain stable.
- Each caption carries `attrs.visual_parent_observation_id`, source kind, and bbox provenance. A precise bbox is required for direct anchor eligibility.
- ObservedDocument does not infer that a caption is a section title.
- BookSkeleton may use a caption observation only when its normalized text is an exact ordered match for the TOC title. Fuzzy text never supplies `title_observation_ids`.
- No SectionMap behavior or contract changes are in scope.

## Acceptance cases

- Exact aggregate matching keeps only the matching ordered evidence IDs.
- `资料来源`, `帝王姓名表`, `古代地中海各文明年代图表`, and `附录三 正统年号与闽国年号对照表` retain visual resources and gain separate caption evidence.
- Ordinary captions remain captions and do not become direct anchors without exact TOC matching.
- Existing raw observation IDs remain unchanged.
