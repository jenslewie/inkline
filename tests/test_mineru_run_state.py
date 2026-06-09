from __future__ import annotations

import json
import sys
import types

from inkline.parsers.mineru.bridge import run_mineru_raw


def test_run_mineru_raw_writes_run_state(tmp_path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    output_dir = tmp_path / "mineru_raw"

    common = types.ModuleType("mineru.cli.common")

    def read_fn(path):
        return path.read_bytes()

    def do_parse(**kwargs):
        assert kwargs["output_dir"] == str(output_dir.resolve())
        assert kwargs["pdf_file_names"] == ["sample"]
        assert kwargs["backend"] == "vlm-auto-engine"
        assert kwargs["parse_method"] == "auto"

    common.read_fn = read_fn
    common.do_parse = do_parse

    enum_class = types.ModuleType("mineru.utils.enum_class")
    enum_class.MakeMode = types.SimpleNamespace(MM_MD="mm_markdown")

    monkeypatch.setitem(sys.modules, "mineru", types.ModuleType("mineru"))
    monkeypatch.setitem(sys.modules, "mineru.cli", types.ModuleType("mineru.cli"))
    monkeypatch.setitem(sys.modules, "mineru.cli.common", common)
    monkeypatch.setitem(sys.modules, "mineru.utils", types.ModuleType("mineru.utils"))
    monkeypatch.setitem(sys.modules, "mineru.utils.enum_class", enum_class)

    assert run_mineru_raw(pdf, output_dir) == output_dir.resolve()

    state = json.loads((output_dir / "run_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "succeeded"
    assert state["input_pdf"] == str(pdf.resolve())
    assert state["output_dir"] == str(output_dir.resolve())
    assert state["backend"] == "vlm-auto-engine"
    assert state["method"] == "auto"
    assert state["started_at"]
    assert state["finished_at"]
    assert state["duration_seconds"] >= 0
