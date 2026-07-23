# PageReview Golden Evaluation Gate

## Purpose

Prevent prompt, schema, resolver, candidate-selection, or model changes from
silently regressing a verified PageReview result. The authoritative baseline is
`data/outputs/golden/page-review/`; it currently contains thirteen books.

This gate evaluates actual multimodal model behaviour. It supplements, rather
than replaces, normal unit tests for PageReview contracts and routing.

## Non-Goals

- Automatically changing golden artifacts.
- Treating a new LLM output as correct merely because it is newer.
- Replacing human review of intentional semantic changes.
- Sending non-candidate pages to the LLM.

## Artifact Layout

```text
data/outputs/golden/page-review/<book>/<book>_page_review.json
    Human-approved baseline. Never overwritten by normal evaluation.

data/outputs/staging/page-review/<run-id>/<book>/
    Fresh PageReview, rendered candidate images, checkpoint, and diff report.

data/outputs/workspace/page-review/<book>/
    Last accepted generated PageReview. Replaced only after a passing gate.
```

Every staged result records the model, prompt version, PageReview schema
version, source artifact fingerprints, candidate pages, and image-evidence
version. This makes an evaluation result reproducible and explains why a
particular PageReview was accepted.

## Evaluation Tiers

### Unit and Replay Gate

Every code change runs `pytest`, `ruff`, `pylint`, and `git diff --check`.
Unit tests cover schemas, deterministic policy normalization, prompt-profile
routing, checkpoints, and the golden-diff tool. Replay tests use recorded model
responses and do not claim to assess current model behaviour.

### Focused Multimodal Gate

A profile-specific prompt change runs the approved books/pages that exercise
that profile. For example, a change to `front_residual_unknown` must include
verified copyright, dedication, and ordinary front-prose pages. The staged
output is compared with the matching golden output on all stable page fields.

### Full Multimodal Gate

A change to the common prompt, PageReview schema, resolver, candidate-page
selection, image rendering, model, or model configuration runs every golden
book. Any stable-field difference fails the gate.

The stable fields are `page_role`, `book_block_position`,
`special_page_kind`, `text_flow_action`, and `visual_asset_action`.

## Publish Protocol

1. Generate only into a unique staging directory.
2. Validate the staged PageReview schema and checkpoint completion.
3. Compare each staged artifact to its golden counterpart.
4. If any difference exists, keep staging artifacts and a machine-readable
   report; do not modify workspace output.
5. If every comparison passes, atomically publish each staged book directory to
   `data/outputs/workspace/page-review/<book>/`.

The normal CLI must never delete a previously accepted workspace result before
the new staged result passes. A separate, explicit golden-update command may be
added later, but it must require a human-reviewed input artifact and cannot be
the default path.

## Change-Impact Rules

| Change | Required evaluation |
| --- | --- |
| One profile instruction | Focused corpus for that profile, plus unit/replay gate |
| Prompt common contract | Full golden corpus |
| Model or inference configuration | Full golden corpus |
| Schema or resolver policy | Full golden corpus |
| Candidate selection or image rendering | Full golden corpus |
| New special page kind | Focused examples and full golden corpus before publish |

## Failure Handling

The evaluation command exits nonzero for a schema failure, incomplete
checkpoint, missing artifact, unexpected page, or stable-field diff. It prints
and writes a report grouped by book, page, field, golden value, and staged
value. Human review considers only these reported differences. Intentional
changes require an explicit golden update after review; they are never accepted
by suppressing a diff in code.

## Acceptance Criteria

- The runner discovers all books from `data/outputs/golden/page-review/`.
- Evaluation does not overwrite `workspace/page-review` when it fails.
- A passing run publishes only validated staged artifacts.
- CI/local tests cover failure retention, successful publish, and golden
  discovery.
- README documents focused versus full evaluation commands and the golden-update
  policy.
