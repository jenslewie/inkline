from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactContract:
    """Frozen responsibility and dependency boundary for one target DAG artifact."""

    artifact: str
    inputs: tuple[str, ...]
    output: str
    owns: tuple[str, ...]
    must_not_own: tuple[str, ...]
    validation: tuple[str, ...]


CANONICAL_ARTIFACT_CONTRACTS = (
    ArtifactContract(
        "VisualRelationReview",
        ("ObservedIndex", "PageLayoutAnalysis", "PageReview", "PageAssets"),
        "visual groups, relation evidence, and explicit unpaired/unresolved endpoints",
        ("same-page non-table visual/caption relations", "visual endpoint audit state"),
        ("caption text", "table captions", "section membership", "OCR repair"),
        ("endpoint identity and kind", "single ownership", "same-page scope", "provenance"),
    ),
    ArtifactContract(
        "NoteSystemReview",
        ("ObservedIndex", "PageLayoutAnalysis", "BookSkeleton", "PageReview", "PageAssets"),
        "separate page-foot, chapter-end, and book-end note systems",
        ("definition ranges", "reference scope", "marker style", "reset policy"),
        ("printed marker recognition", "TextUnits", "section membership", "note targets"),
        ("range and scope consistency", "evidence identity", "mixed-system separation"),
    ),
    ArtifactContract(
        "NoteMarkerReviewPlan",
        ("ObservedIndex", "PageLayoutAnalysis", "NoteSystemReview"),
        "bounded marker-review requests and explicit no-review/unresolved partitions",
        ("review regions", "structural review reasons", "request coverage"),
        ("marker recognition", "note targets", "section membership"),
        ("bounded regions", "known note-system ids", "complete system partition"),
    ),
    ArtifactContract(
        "NoteMarkerReview",
        ("ObservedIndex", "PageAssets", "NoteMarkerReviewPlan"),
        "definition/reference marker evidence and per-request outcome state",
        ("printed marker localization", "model outcome and provenance"),
        ("invented marker text", "TextUnits", "section membership", "note targets"),
        ("request coverage", "planned-region containment", "text anchors", "provenance"),
    ),
    ArtifactContract(
        "TextFlow",
        (
            "ObservedIndex",
            "PageLayoutAnalysis",
            "BookSkeleton",
            "PageReview",
            "VisualRelationReview",
            "NoteSystemReview",
            "NoteMarkerReview",
        ),
        "ordered final TextUnits and unresolved note_ref inline runs",
        ("TextUnit identity", "text classification", "caption units", "inline-run location"),
        ("visual relation discovery", "note targets", "section membership", "tables"),
        ("observation coverage", "protected anchors", "caption ownership", "marker provenance"),
    ),
    ArtifactContract(
        "TableFlow",
        ("ObservedDocument", "ObservedIndex", "PageReview"),
        "logical readable tables and explicit excluded/unresolved table runs",
        ("structured table continuation", "structured table captions", "table serialization"),
        ("non-table visual captions", "section membership", "half-table materialization"),
        ("complete table observation partition", "PageReview consistency", "provenance"),
    ),
    ArtifactContract(
        "NoteInventory",
        ("TextFlow", "NoteSystemReview", "NoteMarkerReviewPlan", "NoteMarkerReview"),
        "definitions, inline references, note groups, and unresolved coverage",
        ("note membership audit", "normalized marker inventory", "coverage state"),
        ("authoritative note targets", "section membership", "TextFlow mutation"),
        ("TextUnit and inline-run identity", "system separation", "marker evidence"),
    ),
    ArtifactContract(
        "SectionMap",
        (
            "BookSkeleton",
            "PageReview",
            "TextFlow",
            "TableFlow",
            "VisualRelationReview",
            "NoteInventory",
        ),
        "section hierarchy, membership, ranges, and standalone/unresolved placements",
        ("section membership", "physical ranges", "standalone and unresolved placement"),
        (
            "text classification",
            "visual relation discovery",
            "table reinterpretation",
            "note targets",
        ),
        ("all upstream ids", "single membership", "evidence-backed ranges", "coverage"),
    ),
    ArtifactContract(
        "NoteResolution",
        ("NoteInventory", "SectionMap"),
        "immutable resolved relations and explicit unresolved references",
        ("scope-constrained note target relations", "resolution decision provenance"),
        ("TextFlow mutation", "NoteInventory mutation", "SectionMap mutation"),
        ("reference and target identity", "scope consistency", "complete reference partition"),
    ),
    ArtifactContract(
        "BookGraph assembler",
        ("CanonicalArtifactBundle",),
        "public BookGraph and internal canonical views",
        ("identity projection", "public/internal views", "resolved edge projection"),
        ("parser repair", "TextUnit rebuilding", "section inference", "upstream mutation"),
        ("bundle completeness", "projection parity", "upstream identity mapping"),
    ),
)


def artifact_contract(artifact: str) -> ArtifactContract:
    """Return the frozen target contract for an artifact."""

    for contract in CANONICAL_ARTIFACT_CONTRACTS:
        if contract.artifact == artifact:
            return contract
    raise KeyError(artifact)
