# BookSkeleton ObservedDocument Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional ObservedDocument persistence to `mineru-to-book-skeleton` and materialize validated workspace artifacts for all 13 accepted books.

**Architecture:** The BookSkeleton CLI serializes the already-built and already-validated in-memory `ObservedDocument` before starting Skeleton construction; it never rebuilds or renumbers observations. Existing books are backfilled without touching accepted Skeleton or golden files by running the rule-only CLI against temporary sibling Skeleton outputs, then validating every persisted ObservedDocument against its accepted workspace Skeleton.

**Tech Stack:** Python 3.11, argparse, JSON, pytest, Inkline canonical validators, Ruff, Pylint, Pyright, uv.

## Global Constraints

- Output path: `data/outputs/workspace/observed/<book>_observed.json`.
- `--observed-output` is optional; existing CLI behavior is unchanged when omitted.
- Serialize UTF-8 JSON with `ensure_ascii=False` and `indent=2`.
- Validate before writing and write the exact object passed to `build_book_skeleton_shadow()`.
- Backfill uses existing `content_list_v2`, `middle.json`, and source PDF.
- Backfill does not invoke the TOC LLM or overwrite accepted Skeleton/golden files.
- Generated `data/` artifacts remain local review data and are not committed.
- Do not fix fuzzy anchors, TextUnits, PageReview, SectionMap, or BookGraph here.

---

## File Structure

- Modify `packages/inkline-parser-mineru/src/inkline/parsers/mineru/app/book_skeleton_cli.py`: parse and write the optional artifact.
- Modify `tests/inkline/parsers/mineru/app/test_mineru_cli_book_skeleton.py`: CLI and write-order coverage.
- Modify `README.md` and `packages/inkline-parser-mineru/README.md`: usage and lookup documentation.
- Create ignored local files under `data/outputs/workspace/observed/`.

### Task 1: Add Optional ObservedDocument Output

**Files:**
- Modify: `packages/inkline-parser-mineru/src/inkline/parsers/mineru/app/book_skeleton_cli.py:20-111`
- Test: `tests/inkline/parsers/mineru/app/test_mineru_cli_book_skeleton.py:1-114`

**Interfaces:**
- Consumes: `build_observed_document_shadow(...) -> dict[str, Any]` and `validate_observed_document(document) -> None`.
- Produces: `--observed-output PATH` and `_write_json(path: Path, payload: dict[str, Any]) -> None`.

- [ ] **Step 1: Add failing parser and persistence tests**

Add `json`, `sys`, `Path`, and `pytest` imports. Add `observed_output=None` to the
existing `SimpleNamespace` fixture. Add this reusable fixture helper and the
three complete tests:

```python
def _book_skeleton_cli_args(tmp_path, **overrides):
    values = {
        "content_list_v2": "content_list_v2.json",
        "content_list": None,
        "middle": "middle.json",
        "source_pdf": str(tmp_path / "sample.pdf"),
        "allow_missing_pdf_text": False,
        "doc_id": "sample",
        "title": "Sample",
        "language": "zh-CN",
        "output": str(tmp_path / "skeleton" / "sample_skeleton.json"),
        "observed_output": str(tmp_path / "observed" / "sample_observed.json"),
        "llm": False,
        "llm_model": "qwen-test",
        "llm_api_url": "http://example.test/api/chat",
        "llm_timeout_seconds": 300,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_book_skeleton_cli_parses_optional_observed_output(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mineru-to-book-skeleton",
            "--content-list-v2",
            "content_list_v2.json",
            "--output",
            "skeleton.json",
            "--observed-output",
            "observed.json",
        ],
    )

    args = book_skeleton_cli.parse_args()

    assert args.observed_output == "observed.json"


def test_book_skeleton_cli_writes_exact_observed_object_before_skeleton(
    tmp_path, monkeypatch
) -> None:
    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    args = _book_skeleton_cli_args(tmp_path, source_pdf=str(source_pdf))
    observed_output = Path(args.observed_output)
    observed = {"metadata": {"doc_id": "sample"}, "pages": [], "observations": []}
    skeleton = {"metadata": {"doc_id": "sample"}, "toc_entries": []}

    monkeypatch.setattr(book_skeleton_cli, "parse_args", lambda: args)
    monkeypatch.setattr(
        book_skeleton_cli,
        "resolve_source_pdf_path",
        lambda *_, **__: str(source_pdf),
    )
    monkeypatch.setattr(book_skeleton_cli, "load_inputs", lambda _: ({}, {}))
    monkeypatch.setattr(book_skeleton_cli, "load_json", lambda _: None)
    monkeypatch.setattr(
        book_skeleton_cli, "build_observed_document_shadow", lambda **_: observed
    )
    monkeypatch.setattr(book_skeleton_cli, "validate_observed_document", lambda _: None)

    def build_skeleton(value, **_):
        assert value is observed
        assert json.loads(observed_output.read_text(encoding="utf-8")) == observed
        return skeleton

    monkeypatch.setattr(book_skeleton_cli, "build_book_skeleton_shadow", build_skeleton)
    monkeypatch.setattr(book_skeleton_cli, "validate_book_skeleton", lambda _: None)

    book_skeleton_cli.main()

    assert observed_output.parent.is_dir()
    assert json.loads(observed_output.read_text(encoding="utf-8")) == observed


def test_book_skeleton_cli_stops_when_observed_output_cannot_be_written(
    tmp_path, monkeypatch
) -> None:
    args = _book_skeleton_cli_args(tmp_path, source_pdf=None)
    observed = {"metadata": {}, "pages": [], "observations": []}

    monkeypatch.setattr(book_skeleton_cli, "parse_args", lambda: args)
    monkeypatch.setattr(book_skeleton_cli, "resolve_source_pdf_path", lambda *_, **__: None)
    monkeypatch.setattr(book_skeleton_cli, "load_inputs", lambda _: ({}, {}))
    monkeypatch.setattr(book_skeleton_cli, "load_json", lambda _: None)
    monkeypatch.setattr(
        book_skeleton_cli, "build_observed_document_shadow", lambda **_: observed
    )
    monkeypatch.setattr(book_skeleton_cli, "validate_observed_document", lambda _: None)
    monkeypatch.setattr(
        book_skeleton_cli,
        "_write_json",
        lambda *_: (_ for _ in ()).throw(OSError("read-only output")),
    )
    monkeypatch.setattr(
        book_skeleton_cli,
        "build_book_skeleton_shadow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Skeleton construction must not start")
        ),
    )

    with pytest.raises(OSError, match="read-only output"):
        book_skeleton_cli.main()
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```bash
env UV_CACHE_DIR=/private/tmp/inkline-uv-cache uv run pytest -q \
  tests/inkline/parsers/mineru/app/test_mineru_cli_book_skeleton.py
```

Expected: new tests fail because `--observed-output` and `_write_json()` do not exist and no observed file is written.

- [ ] **Step 3: Implement the minimal CLI change**

Add after `--output`:

```python
parser.add_argument(
    "--observed-output",
    help="Optional parser-neutral ObservedDocument JSON output path.",
)
```

Write immediately after validation and before Skeleton construction:

```python
validate_observed_document(observed)
if args.observed_output:
    _write_json(Path(args.observed_output), observed)
skeleton = build_book_skeleton_shadow(
    observed,
    use_llm=args.llm,
    source_pdf=args.source_pdf,
    image_output_dir=(output_path.parent / f"{output_path.stem}_toc_llm_pages"),
    llm_model=args.llm_model,
    llm_api_url=args.llm_api_url,
    llm_timeout_seconds=args.llm_timeout_seconds,
)
```

Replace the inline Skeleton write with `_write_json(output_path, skeleton)` and add:

```python
def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
```

- [ ] **Step 4: Run focused verification**

```bash
env UV_CACHE_DIR=/private/tmp/inkline-uv-cache uv run pytest -q \
  tests/inkline/parsers/mineru/app/test_mineru_cli_book_skeleton.py
env UV_CACHE_DIR=/private/tmp/inkline-uv-cache uv run ruff check \
  packages/inkline-parser-mineru/src/inkline/parsers/mineru/app/book_skeleton_cli.py \
  tests/inkline/parsers/mineru/app/test_mineru_cli_book_skeleton.py
env UV_CACHE_DIR=/private/tmp/inkline-uv-cache uv run ruff format --check \
  packages/inkline-parser-mineru/src/inkline/parsers/mineru/app/book_skeleton_cli.py \
  tests/inkline/parsers/mineru/app/test_mineru_cli_book_skeleton.py
```

Expected: focused tests and both Ruff commands pass.

- [ ] **Step 5: Review and commit**

```bash
git diff --check
git diff -- packages/inkline-parser-mineru/src/inkline/parsers/mineru/app/book_skeleton_cli.py \
  tests/inkline/parsers/mineru/app/test_mineru_cli_book_skeleton.py
git add packages/inkline-parser-mineru/src/inkline/parsers/mineru/app/book_skeleton_cli.py \
  tests/inkline/parsers/mineru/app/test_mineru_cli_book_skeleton.py
git commit -m "feat(mineru): persist observed document with skeleton"
```

### Task 2: Document the Paired Review Artifact

**Files:**
- Modify: `README.md:157-176`
- Modify: `packages/inkline-parser-mineru/README.md:1-30`

**Interfaces:**
- Consumes: `mineru-to-book-skeleton --observed-output PATH`.
- Produces: discoverable generation and lookup instructions.

- [ ] **Step 1: Update the root README command**

Use workspace destinations:

```bash
  --output data/outputs/workspace/skeleton/埃及_skeleton.json \
  --observed-output data/outputs/workspace/observed/埃及_observed.json \
  --llm
```

Document that the option persists the exact validated object consumed by the Skeleton builder. Include:

```bash
rg -n -C 8 '"observation_id": "obs000396"' \
  data/outputs/workspace/observed/女王与苏丹_observed.json
```

- [ ] **Step 2: Update the MinerU package README**

State in the public-role bullet and a short `BookSkeleton Only` section that the dedicated CLI can emit the paired parser-neutral ObservedDocument, that IDs are not reassigned, and that the option remains optional.

- [ ] **Step 3: Verify and commit documentation**

```bash
rg -n "observed-output|workspace/observed|obs000396" \
  README.md packages/inkline-parser-mineru/README.md
git diff --check
git add README.md packages/inkline-parser-mineru/README.md
git commit -m "docs(mineru): document observed review artifacts"
```

### Task 3: Backfill and Validate 13 ObservedDocuments

**Files:**
- Create locally: `data/outputs/workspace/observed/*_observed.json` (ignored).
- Create temporarily: `data/outputs/workspace/.observed-backfill/*_skeleton.json`.
- Read only: workspace and golden Skeleton files.

**Interfaces:**
- Consumes: Task 1 CLI, `data/outputs/mineru/<book>/vlm/`, and `data/samples/<book>.pdf`.
- Produces: 13 valid ObservedDocuments resolving every accepted anchor evidence id.

- [ ] **Step 1: Record accepted hashes**

```bash
find data/outputs/workspace/skeleton data/outputs/golden/skeleton \
  -maxdepth 1 -type f -name '*_skeleton.json' -exec shasum -a 256 {} + \
  | sort > /private/tmp/inkline-observed-backfill-before.sha256
wc -l /private/tmp/inkline-observed-backfill-before.sha256
```

Expected: `26`.

- [ ] **Step 2: Generate without LLM or accepted-file writes**

```bash
mkdir -p data/outputs/workspace/observed data/outputs/workspace/.observed-backfill

inkline_observed_books=(
  丝绸之路新史 中世纪的英雄与奇观 中日交流两千年 匈人王阿提拉
  四君主 埃及 壬辰战争 女王与苏丹 巴格达 幕末史 追寻千禧年
  闽国 阿金库尔战役
)

for inkline_observed_book in "${inkline_observed_books[@]}"; do
  env UV_CACHE_DIR=/private/tmp/inkline-uv-cache \
    uv run --extra mineru mineru-to-book-skeleton \
      --content-list-v2 "data/outputs/mineru/${inkline_observed_book}/vlm/${inkline_observed_book}_content_list_v2.json" \
      --middle "data/outputs/mineru/${inkline_observed_book}/vlm/${inkline_observed_book}_middle.json" \
      --source-pdf "data/samples/${inkline_observed_book}.pdf" \
      --doc-id "${inkline_observed_book}" \
      --title "${inkline_observed_book}" \
      --output "data/outputs/workspace/.observed-backfill/${inkline_observed_book}_skeleton.json" \
      --observed-output "data/outputs/workspace/observed/${inkline_observed_book}_observed.json" \
      --no-llm
done
```

Expected: 13 observed files and 13 disposable rule-only Skeleton files; no Ollama request.

- [ ] **Step 3: Validate documents, pairs, and referenced ids**

```bash
env UV_CACHE_DIR=/private/tmp/inkline-uv-cache uv run python -c $'from pathlib import Path\nimport json\nfrom inkline.canonical import validate_book_skeleton_against_observed, validate_observed_document\nobserved_dir = Path("data/outputs/workspace/observed")\nskeleton_dir = Path("data/outputs/workspace/skeleton")\npaths = sorted(observed_dir.glob("*_observed.json"))\nassert len(paths) == 13, f"expected 13, found {len(paths)}"\nfor observed_path in paths:\n    book = observed_path.stem.removesuffix("_observed")\n    observed = json.loads(observed_path.read_text(encoding="utf-8"))\n    skeleton = json.loads((skeleton_dir / f"{book}_skeleton.json").read_text(encoding="utf-8"))\n    validate_observed_document(observed)\n    validate_book_skeleton_against_observed(skeleton, observed)\n    known_ids = {item["observation_id"] for item in observed["observations"]}\n    for entry in skeleton["toc_entries"]:\n        anchor = entry["selected_start_anchor"]\n        if anchor is None:\n            continue\n        referenced = set(anchor["title_observation_ids"]) | set(anchor["toc_observation_ids"])\n        assert referenced <= known_ids, (book, entry["entry_index"], sorted(referenced - known_ids))\n    observation_count = len(observed["observations"])\n    print(f"PASS {book}: {observation_count} observations")'
```

Expected: 13 `PASS` lines and exit 0.

- [ ] **Step 4: Verify the requested lookup**

```bash
rg -n -C 8 '"observation_id": "obs000396"' \
  data/outputs/workspace/observed/女王与苏丹_observed.json
```

Expected: `text: "争夺巴巴里"`, `page: 72`, and `role_hint: "title_text"`.

- [ ] **Step 5: Prove accepted files are unchanged and clean temporary output**

```bash
find data/outputs/workspace/skeleton data/outputs/golden/skeleton \
  -maxdepth 1 -type f -name '*_skeleton.json' -exec shasum -a 256 {} + \
  | sort > /private/tmp/inkline-observed-backfill-after.sha256
diff -u /private/tmp/inkline-observed-backfill-before.sha256 \
  /private/tmp/inkline-observed-backfill-after.sha256
find data/outputs/workspace/.observed-backfill -maxdepth 1 -type f -print
rm -rf data/outputs/workspace/.observed-backfill
```

Expected: `diff` is silent; `find` lists only the 13 disposable files before removing the explicitly scoped directory.

### Task 4: Final Repository Verification

**Files:**
- Verify tracked changes and local observed artifacts from Tasks 1-3.

**Interfaces:**
- Consumes: completed CLI, docs, tests, and 13 observed artifacts.
- Produces: completion evidence for the user.

- [ ] **Step 1: Run all repository quality gates**

```bash
env UV_CACHE_DIR=/private/tmp/inkline-uv-cache \
  PYLINTHOME=/private/tmp/inkline-pylint-cache \
  make check
env UV_CACHE_DIR=/private/tmp/inkline-uv-cache make typecheck
```

Expected: Ruff passes; Pylint 10.00/10; format clean; pytest passes; Pyright reports `0 errors, 0 warnings, 0 informations`.

- [ ] **Step 2: Repeat Task 3 Step 3 and inspect repository state**

```bash
git diff --check
git status --short --branch
```

Expected: 13 cross-artifact `PASS` lines; `git diff --check` is silent; tracked changes are committed; ignored observed files remain in `data/outputs/workspace/observed/`.

- [ ] **Step 3: Report exact completion evidence**

Report the two functional/documentation commit ids, focused/full test counts, all quality results, 13/13 schema and pair validation, `obs000396 -> 争夺巴巴里, page 72`, unchanged accepted hashes, and the local artifact directory.
