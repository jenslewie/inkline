from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_checker():
    path = Path(__file__).resolve().parents[1] / "tools" / "check_display_block_architecture.py"
    spec = importlib.util.spec_from_file_location("check_display_block_architecture", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def test_display_block_architecture_has_no_text_or_propagation_gates() -> None:
    findings = checker.check_paths(checker.default_paths())

    assert findings == []


def test_display_block_architecture_covers_cleanup_and_normal_flow_files() -> None:
    paths = {path.as_posix() for path in checker.default_paths()}

    assert any(path.endswith("/normalize/builders.py") for path in paths)
    assert any(path.endswith("/normalize/normal_flow.py") for path in paths)
    assert any(path.endswith("/normalize/page_handlers.py") for path in paths)
    assert any(path.endswith("/reconcile/cross_page.py") for path in paths)
    assert any(path.endswith("/reconcile/layout_helpers.py") for path in paths)
    assert any(path.endswith("/display_block/overflow_tail_split.py") for path in paths)


def test_display_block_architecture_covers_every_display_reconcile_module() -> None:
    expected = {
        path.resolve()
        for path in checker.DISPLAY_BLOCK_RECONCILE_DIR.glob("*.py")
        if path.name != "__init__.py"
    }
    actual = {path.resolve() for path in checker.default_paths()}

    assert expected <= actual


def test_display_block_architecture_detects_helper_text_gates(tmp_path: Path) -> None:
    path = tmp_path / "helper_gate.py"
    path.write_text(
        """
def classify(text):
    return _ends_with_terminal(text)
""",
        encoding="utf-8",
    )

    findings = checker.check_paths([path])

    assert [finding.rule for finding in findings] == ["display-no-text-punctuation-helper-gates"]


def test_display_block_architecture_detects_cross_page_display_text_gate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cross_page_display_gate.py"
    path.write_text(
        """
def _set_off_display_before_float_body_resume(left):
    return not _ends_with_terminal(left.get("text", ""))
""",
        encoding="utf-8",
    )

    findings = checker.check_paths([path])

    assert [finding.rule for finding in findings] == ["display-no-text-punctuation-helper-gates"]


def test_display_block_architecture_allows_private_metadata_key_filter(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metadata_filter.py"
    path.write_text(
        """
def clean(item):
    return {k: v for k, v in item.items() if not k.startswith("_")}
""",
        encoding="utf-8",
    )

    findings = checker.check_paths([path])

    assert findings == []
