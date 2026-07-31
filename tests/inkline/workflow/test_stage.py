from __future__ import annotations

from pathlib import Path

import pytest

from inkline.workflow import Stage, run_stages

ROOT = Path(__file__).resolve().parents[3]


def test_stages_are_enumerable_without_execution() -> None:
    calls = []
    stage = Stage(
        name="derive",
        inputs=("source",),
        output="derived",
        run=lambda source: calls.append(source) or source + 1,
        validate=lambda value: None,
    )

    assert stage.name == "derive"
    assert stage.inputs == ("source",)
    assert stage.output == "derived"
    assert calls == []


def test_runner_resolves_explicit_inputs_and_validates_output() -> None:
    validated = []
    stage = Stage(
        name="derive",
        inputs=("source",),
        output="derived",
        run=lambda source: source + 1,
        validate=validated.append,
    )

    artifacts = run_stages({"source": 1}, [stage])

    assert artifacts == {"source": 1, "derived": 2}
    assert validated == [2]


def test_runner_uses_validated_artifact_store_value_without_executing_stage() -> None:
    class MemoryStore:
        def __init__(self):
            self.values = {"derived": 7}

        def has(self, name):
            return name in self.values

        def load(self, name):
            return self.values[name]

        def save(self, name, artifact):
            self.values[name] = artifact

    calls = []
    validated = []
    stage = Stage(
        name="derive",
        inputs=("source",),
        output="derived",
        run=lambda source: calls.append(source),
        validate=validated.append,
    )

    artifacts = run_stages({"source": 1}, [stage], artifact_store=MemoryStore())

    assert artifacts["derived"] == 7
    assert calls == []
    assert validated == [7]


def test_runner_rejects_builder_mutation_of_upstream_artifact() -> None:
    source = {"items": [1]}

    def mutating_builder(source):
        source["items"].append(2)
        return {"derived": True}

    stage = Stage(
        name="derive",
        inputs=("source",),
        output="derived",
        run=mutating_builder,
        validate=lambda value: None,
    )

    with pytest.raises(ValueError, match="mutated upstream artifact source"):
        run_stages({"source": source}, [stage])


def test_workflow_package_has_no_parser_or_agent_framework_dependency() -> None:
    sources = list((ROOT / "packages/inkline-workflow/src/inkline/workflow").glob("*.py"))
    forbidden = ("inkline.parse", "inkline.parsers", "langchain", "langgraph")

    leaks = {
        path.name: [term for term in forbidden if term in path.read_text(encoding="utf-8")]
        for path in sources
    }

    assert leaks == {path.name: [] for path in sources}
