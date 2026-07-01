from __future__ import annotations

from copy import deepcopy
from typing import Any

from inkline.canonical.bookgraph import validate_bookgraph


def bookgraph_to_blocks(graph: dict[str, Any]) -> list[dict[str, Any]]:
    validate_bookgraph(graph)
    nodes_by_id = {node["node_id"]: node for node in graph["nodes"]}
    evidence_by_id = {record["evidence_id"]: record for record in graph["evidence"]}

    blocks: list[dict[str, Any]] = []
    for node_id in graph["projections"]["reading_order"]:
        node = nodes_by_id[node_id]
        attrs = _project_attrs(node)
        block: dict[str, Any] = {
            "block_id": node["attrs"].get("source_block_id") or node_id,
            "type": node["node_type"],
            "text": node["text"],
            "attrs": attrs,
            "source": _project_source(node, evidence_by_id),
        }
        if node.get("level") is not None:
            block["level"] = node["level"]
        blocks.append(block)
    return blocks


def _project_attrs(node: dict[str, Any]) -> dict[str, Any]:
    attrs = {
        key: deepcopy(value)
        for key, value in node.get("attrs", {}).items()
        if key != "source_block_id"
    }
    if "inline_runs" in node:
        attrs["inline_runs"] = deepcopy(node["inline_runs"])
    return attrs


def _project_source(
    node: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    evidence_ids = node.get("evidence_ids") or []
    if not evidence_ids:
        return {}
    evidence = evidence_by_id[evidence_ids[0]]
    source: dict[str, Any] = {}
    for key in ("page", "bbox", "pages", "spans"):
        value = evidence.get(key)
        if key == "spans" and value == []:
            continue
        if value is not None:
            source[key] = deepcopy(value)
    return source
