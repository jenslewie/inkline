from __future__ import annotations

import json
import os
import sys
import types

import inkline.parsers.mineru.bridge as mineru_bridge
from inkline.parsers.mineru.bridge import _model_info_from_path, find_mineru_run_version_info, run_mineru_raw


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

    setattr(common, "read_fn", read_fn)
    setattr(common, "do_parse", do_parse)

    enum_class = types.ModuleType("mineru.utils.enum_class")
    setattr(enum_class, "MakeMode", types.SimpleNamespace(MM_MD="mm_markdown"))

    monkeypatch.setitem(sys.modules, "mineru", types.ModuleType("mineru"))
    monkeypatch.setitem(sys.modules, "mineru.cli", types.ModuleType("mineru.cli"))
    monkeypatch.setitem(sys.modules, "mineru.cli.common", common)
    monkeypatch.setitem(sys.modules, "mineru.utils", types.ModuleType("mineru.utils"))
    monkeypatch.setitem(sys.modules, "mineru.utils.enum_class", enum_class)
    monkeypatch.delenv("MINERU_MODEL_SOURCE", raising=False)
    monkeypatch.delenv("MINERU_TOOLS_CONFIG_JSON", raising=False)
    monkeypatch.setattr(
        mineru_bridge,
        "_resolve_mineru_vlm_model_info",
        lambda: {
            "local_path": "/cache/MinerU2.5-Pro-2605-1.2B",
            "model_name": "MinerU2.5-Pro-2605-1.2B",
            "model_type": "qwen2_vl",
            "architectures": ["Qwen2VLForConditionalGeneration"],
        },
    )

    assert run_mineru_raw(pdf, output_dir) == output_dir.resolve()

    state = json.loads((output_dir / "run_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "succeeded"
    assert state["input_pdf"] == str(pdf.resolve())
    assert state["output_dir"] == str(output_dir.resolve())
    assert state["backend"] == "vlm-auto-engine"
    assert state["method"] == "auto"
    assert state["vlm_model"]["model_name"] == "MinerU2.5-Pro-2605-1.2B"
    assert state["started_at"]
    assert state["finished_at"]
    assert state["duration_seconds"] >= 0
    assert not (output_dir / "mineru_local_config.json").exists()
    assert "MINERU_MODEL_SOURCE" not in os.environ
    assert "MINERU_TOOLS_CONFIG_JSON" not in os.environ


def test_find_mineru_run_version_info_from_nested_raw_file(tmp_path):
    raw_root = tmp_path / "mineru_raw"
    nested = raw_root / "sample" / "vlm" / "sample_middle.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("{}", encoding="utf-8")
    (raw_root / "run_state.json").write_text(
        json.dumps(
            {
                "mineru_version": "3.2.3",
                "mineru_vl_utils_version": "1.0.4",
                "vlm_model": {"model_name": "MinerU2.5-Pro-2605-1.2B"},
            }
        ),
        encoding="utf-8",
    )

    info = find_mineru_run_version_info(nested)

    assert info is not None
    assert info["vlm_model"]["model_name"] == "MinerU2.5-Pro-2605-1.2B"


def test_model_info_uses_huggingface_repository_name(tmp_path):
    model_root = (
        tmp_path
        / "models--opendatalab--MinerU2.5-Pro-2605-1.2B"
        / "snapshots"
        / "revision"
    )
    model_root.mkdir(parents=True)
    (model_root / "config.json").write_text(
        json.dumps(
            {
                "model_type": "qwen2_vl",
                "architectures": ["Qwen2VLForConditionalGeneration"],
            }
        ),
        encoding="utf-8",
    )

    info = _model_info_from_path(model_root)

    assert info["model_name"] == "MinerU2.5-Pro-2605-1.2B"
    assert info["model_type"] == "qwen2_vl"
