from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from inkline.workflow.artifact_store import ArtifactStore


@dataclass(frozen=True)
class Stage:
    """One framework-neutral artifact transformation in the canonical DAG."""

    name: str
    inputs: tuple[str, ...]
    output: str
    run: Callable[..., Any]
    validate: Callable[[Any], None]


def run_stages(
    initial_artifacts: Mapping[str, Any],
    stages: Iterable[Stage],
    *,
    artifact_store: ArtifactStore | None = None,
    on_stage_complete: Callable[[str, Any], None] | None = None,
) -> dict[str, Any]:
    """Resolve declared dependencies, validate outputs, and optionally persist them."""

    artifacts = dict(initial_artifacts)
    pending = list(stages)
    while pending:
        progressed = False
        for stage in list(pending):
            if not all(name in artifacts for name in stage.inputs):
                continue
            artifact = _load_or_run(stage, artifacts, artifact_store)
            stage.validate(artifact)
            artifacts[stage.output] = artifact
            if artifact_store is not None and not artifact_store.has(stage.output):
                artifact_store.save(stage.output, artifact)
            if on_stage_complete is not None:
                on_stage_complete(stage.output, artifact)
            pending.remove(stage)
            progressed = True
        if not progressed:
            missing = {stage.name: sorted(set(stage.inputs) - set(artifacts)) for stage in pending}
            raise ValueError(f"canonical artifact DAG has unresolved inputs: {missing}")
    return artifacts


def _load_or_run(
    stage: Stage,
    artifacts: dict[str, Any],
    artifact_store: ArtifactStore | None,
) -> Any:
    if artifact_store is not None and artifact_store.has(stage.output):
        return artifact_store.load(stage.output)
    inputs = {name: artifacts[name] for name in stage.inputs}
    snapshots = {name: deepcopy(value) for name, value in inputs.items()}
    output = stage.run(**inputs)
    for name, snapshot in snapshots.items():
        if inputs[name] != snapshot:
            raise ValueError(f"stage {stage.name} mutated upstream artifact {name}")
    return output
