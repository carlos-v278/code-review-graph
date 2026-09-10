"""Graph traversal and evidence path construction for journeys."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from .graph import GraphEdge, GraphNode
from .journey_consumers import is_frontend_request
from .journey_source import relative_path

_CONDITIONAL_EDGES = frozenset({"PUBLISHES", "HANDLED_BY"})


def walk(
    starts: set[str], adjacency: dict[str, list[tuple[str, GraphEdge]]],
    max_depth: int = 12,
) -> tuple[dict[str, int], dict[str, GraphEdge]]:
    distances = {start: 0 for start in starts}
    evidence: dict[str, GraphEdge] = {}
    queue = deque(starts)
    while queue:
        current = queue.popleft()
        if distances[current] >= max_depth:
            continue
        for target, edge in adjacency.get(current, []):
            if target in distances:
                continue
            distances[target] = distances[current] + 1
            evidence[target] = edge
            queue.append(target)
    return distances, evidence


def link_metadata(
    target: str, roots: set[str], evidence: dict[str, GraphEdge], *,
    direction: str, distance: int,
) -> dict[str, Any]:
    """Describe why a reachable node belongs to a journey."""
    current = target
    edge_kinds: list[str] = []
    conditional = False
    while current not in roots:
        edge = evidence.get(current)
        if edge is None:
            break
        edge_kinds.append(edge.kind)
        conditional = conditional or edge.kind in _CONDITIONAL_EDGES
        current = (
            edge.target_qualified if direction == "upstream"
            else edge.source_qualified
        )
    scope = "direct" if distance <= 1 and not conditional else "indirect"
    relation_names = " → ".join(kind.casefold() for kind in edge_kinds)
    return {
        "scope": scope,
        "depth": distance,
        "conditional": conditional,
        "reason": relation_names or "same symbol",
        "edge_kinds": edge_kinds,
    }


def hidden_beyond_depth(
    starts: set[str], adjacency: dict[str, list[tuple[str, GraphEdge]]],
    max_depth: int,
) -> int:
    visible, _ = walk(starts, adjacency, max_depth=max_depth)
    extended, _ = walk(starts, adjacency, max_depth=max_depth + 1)
    return sum(distance > max_depth for distance in extended.values())


def relation(
    edge: GraphEdge | None, *, root: Path, name: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "relation": name or (edge.kind.casefold() if edge is not None else "unknown"),
    }
    if edge is not None:
        result.update({
            "file": relative_path(edge.file_path, root),
            "line": edge.line,
        })
        if edge.kind in _CONDITIONAL_EDGES:
            result["conditional"] = True
    if reason:
        result["reason"] = reason
    return result


def path(
    qualified_names: list[str], relations: list[dict[str, Any]], *,
    nodes_by_qn: dict[str, GraphNode], root: Path,
) -> list[dict[str, Any]]:
    steps = []
    for index, qualified_name in enumerate(qualified_names):
        node = nodes_by_qn.get(qualified_name)
        step: dict[str, Any] = {
            "kind": node.kind if node is not None else "Unresolved",
            "name": (
                f"{node.parent_name}.{node.name}"
                if node is not None and node.parent_name
                else node.name if node is not None
                else qualified_name.rsplit("::", 1)[-1]
            ),
            "symbol": qualified_name,
        }
        if node is not None:
            step.update({
                "file": relative_path(node.file_path, root),
                "line": node.line_start,
            })
        if index:
            step["via"] = relations[index - 1]
        steps.append(step)
    return steps


def upstream_path(
    start: str, roots: set[str], evidence: dict[str, GraphEdge], *,
    nodes_by_qn: dict[str, GraphNode], root: Path,
) -> list[dict[str, Any]]:
    qualified_names = [start]
    relations = []
    current = start
    while current not in roots:
        edge = evidence.get(current)
        if edge is None or edge.target_qualified in qualified_names:
            break
        relations.append(relation(edge, root=root))
        current = edge.target_qualified
        qualified_names.append(current)
    return path(qualified_names, relations, nodes_by_qn=nodes_by_qn, root=root)


def downstream_path(
    target: str, roots: set[str], evidence: dict[str, GraphEdge], *,
    nodes_by_qn: dict[str, GraphNode], root: Path,
) -> list[dict[str, Any]]:
    qualified_names = [target]
    edges = []
    current = target
    while current not in roots:
        edge = evidence.get(current)
        if edge is None or edge.source_qualified in qualified_names:
            break
        edges.append(edge)
        current = edge.source_qualified
        qualified_names.append(current)
    qualified_names.reverse()
    relations = [relation(edge, root=root) for edge in reversed(edges)]
    return path(qualified_names, relations, nodes_by_qn=nodes_by_qn, root=root)


def frontend_prefixes(
    target: str, incoming: dict[str, list[tuple[str, GraphEdge]]], *,
    nodes_by_qn: dict[str, GraphNode], root: Path,
) -> list[list[dict[str, Any]]]:
    reachable, evidence = walk({target}, incoming)
    candidates = {
        qn for qn, distance in reachable.items()
        if distance > 0 and qn in nodes_by_qn
        and nodes_by_qn[qn].kind == "Function"
        and is_frontend_request(nodes_by_qn[qn], root)
        and not nodes_by_qn[qn].is_test
    }
    leaves = sorted(
        qn for qn in candidates
        if not any(source in candidates for source, _edge in incoming.get(qn, []))
    )
    return [
        upstream_path(
            qn, {target}, evidence, nodes_by_qn=nodes_by_qn, root=root,
        )
        for qn in leaves
    ]
