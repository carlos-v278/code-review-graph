"""Repository discovery and implementation paths for journeys."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .graph import GraphEdge, GraphNode
from .journey_paths import downstream_path, link_metadata, walk
from .journey_paths import path as build_path
from .journey_persistence import typeorm_persistence
from .journey_source import relative_path


def repository_contract(
    qualified_name: str,
    node: GraphNode | None,
    nodes_by_qn: dict[str, GraphNode],
) -> tuple[str, str, GraphNode | None, bool]:
    if node is not None and node.kind == "Class":
        return node.qualified_name, node.name, node, False
    contract_qn, separator, method_name = qualified_name.rpartition(".")
    contract = nodes_by_qn.get(contract_qn) if separator else None
    if contract is not None and "repository" in contract.name.casefold():
        return contract_qn, contract.name, contract, True
    if node is not None and node.parent_name:
        candidate_qn = f"{node.file_path}::{node.parent_name}"
        candidate = nodes_by_qn.get(candidate_qn)
        return candidate_qn, node.parent_name, candidate, True
    fallback = qualified_name.rsplit("::", 1)[-1]
    name = fallback.rpartition(".")[0] or fallback
    return contract_qn or qualified_name, name, contract, bool(method_name)


def repository_implementation_paths(
    repository_qn: str,
    base_path: list[dict[str, Any]],
    *,
    implementations: dict[str, list[GraphNode]],
    outgoing: dict[str, list[tuple[str, GraphEdge]]],
    nodes_by_qn: dict[str, GraphNode],
    root: Path,
) -> list[list[dict[str, Any]]]:
    contract_qn, separator, method_name = repository_qn.rpartition(".")
    if not separator or "::" not in contract_qn:
        return []
    contract = nodes_by_qn.get(contract_qn)
    contract_keys = {contract_qn, contract_qn.rsplit("::", 1)[-1]}
    if contract is not None:
        contract_keys.add(contract.name)
    contract_name = contract.name if contract is not None else contract_qn.rsplit("::", 1)[-1]
    implementation_classes = {
        node.qualified_name: node
        for key in contract_keys
        for node in implementations.get(key, [])
    }
    paths = []
    for implementation in sorted(
        implementation_classes.values(), key=lambda node: node.qualified_name,
    ):
        method_qn = f"{implementation.qualified_name}.{method_name}"
        method = nodes_by_qn.get(method_qn)
        if method is None:
            continue
        implementation_step = build_path(
            [method_qn], [], nodes_by_qn=nodes_by_qn, root=root,
        )[0]
        implementation_step["via"] = {
            "relation": "implemented_by",
            "reason": f"{implementation.name} implements {contract_name}",
        }
        prefix = [*base_path, implementation_step]
        reachable, evidence = walk({method_qn}, outgoing)
        mappers = sorted(
            (
                nodes_by_qn[qn]
                for qn, distance in reachable.items()
                if distance > 0
                and qn in nodes_by_qn
                and nodes_by_qn[qn].kind == "Function"
                and (
                    "/mappers/" in relative_path(
                        nodes_by_qn[qn].file_path, root,
                    ).casefold()
                    or "mapper" in " ".join(
                        (nodes_by_qn[qn].name, nodes_by_qn[qn].parent_name or ""),
                    ).casefold()
                )
            ),
            key=lambda item: (reachable[item.qualified_name], item.qualified_name),
        )
        if not mappers:
            paths.append(prefix)
            continue
        for mapper in mappers:
            mapper_path = downstream_path(
                mapper.qualified_name,
                {method_qn},
                evidence,
                nodes_by_qn=nodes_by_qn,
                root=root,
            )
            paths.append([*prefix, *mapper_path[1:]])
    signatures = [tuple(step["symbol"] for step in item) for item in paths]
    return [
        item
        for index, item in enumerate(paths)
        if not any(
            len(signatures[index]) < len(other)
            and other[: len(signatures[index])] == signatures[index]
            for other_index, other in enumerate(signatures)
            if other_index != index
        )
    ]


def _evidence(
    node: GraphNode | None,
    relation_name: str,
    confidence: str,
    *,
    edge: GraphEdge | None,
    root: Path,
    reason: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "relation": relation_name,
        "confidence": confidence,
    }
    if node is not None:
        result.update({
            "file": relative_path(node.file_path, root),
            "symbol": node.qualified_name,
            "line": node.line_start,
        })
    if edge is not None:
        result["line"] = edge.line or result.get("line", 0)
    if reason:
        result["reason"] = reason
    return result


def collect_repositories(
    *,
    downstream: dict[str, int],
    downstream_edges: dict[str, GraphEdge],
    roots: set[str],
    nodes_by_qn: dict[str, GraphNode],
    implementations: dict[str, list[GraphNode]],
    outgoing: dict[str, list[tuple[str, GraphEdge]]],
    entities_by_name: dict[str, Any],
    root: Path,
    source_cache: dict[str, list[str]],
    details: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect repository ports, implementations, mappers, and persistence."""
    groups: dict[str, dict[str, Any]] = {}
    incomplete: list[dict[str, Any]] = []
    for qualified_name, distance in downstream.items():
        if qualified_name in roots:
            continue
        node = nodes_by_qn.get(qualified_name)
        identity = (
            " ".join((node.name, node.parent_name or ""))
            if node is not None else qualified_name.rsplit("::", 1)[-1]
        )
        if "repository" not in identity.casefold():
            continue
        contract_qn, contract_name, contract, is_method = repository_contract(
            qualified_name, node, nodes_by_qn,
        )
        confidence = "confirmed" if node is not None else "probable"
        link = link_metadata(
            qualified_name, roots, downstream_edges,
            direction="downstream", distance=distance,
        )
        repository = groups.setdefault(contract_qn, {
            "id": contract_qn,
            "name": contract_name,
            "confidence": "confirmed" if contract is not None else confidence,
            "link": link,
            "methods": [],
        })
        if link["depth"] < repository["link"]["depth"]:
            repository["link"] = link
        if not is_method:
            repository["evidence"] = _evidence(
                node, "reference", confidence,
                edge=downstream_edges.get(qualified_name), root=root,
            )
            continue
        if any(item["id"] == qualified_name for item in repository["methods"]):
            continue
        method: dict[str, Any] = {
            "id": qualified_name,
            "name": qualified_name.rsplit(".", 1)[-1],
            "confidence": confidence,
            "link": link,
            "resolution": "graph_node" if node is not None else "unresolved",
            "evidence": _evidence(
                node, "call" if distance <= 1 else "reachable", confidence,
                edge=downstream_edges.get(qualified_name), root=root,
                reason=(
                    None if node is not None
                    else "repository method target is not indexed"
                ),
            ),
        }
        if details:
            method["path"] = downstream_path(
                qualified_name, roots, downstream_edges,
                nodes_by_qn=nodes_by_qn, root=root,
            )
            method["implementation_paths"] = repository_implementation_paths(
                qualified_name, method["path"], implementations=implementations,
                outgoing=outgoing, nodes_by_qn=nodes_by_qn, root=root,
            )
            if method["implementation_paths"]:
                method["confidence"] = "confirmed"
                method["resolution"] = "implementation"
                method["evidence"]["reason"] = (
                    "repository method resolved through its implementation"
                )
                for path in [method["path"], *method["implementation_paths"]]:
                    for step in path:
                        if step["symbol"] != qualified_name:
                            continue
                        step["kind"] = "RepositoryMethod"
                        if contract is not None:
                            step.update({
                                "file": relative_path(contract.file_path, root),
                                "line": contract.line_start,
                            })
                persistence = []
                for path in method["implementation_paths"]:
                    implementation_method = next((
                        step["symbol"] for step in path
                        if step.get("via", {}).get("relation") == "implemented_by"
                    ), None)
                    if implementation_method is not None:
                        persistence.extend(typeorm_persistence(
                            implementation_method,
                            outgoing=outgoing,
                            nodes_by_qn=nodes_by_qn,
                            entities=entities_by_name,
                            root=root,
                            source_cache=source_cache,
                        ))
                method["persistence"] = list({
                    (item["entity"], item["table"], item["access"]): item
                    for item in persistence
                }.values())
                expects_typeorm = any(
                    "typeorm" in " ".join((
                        str(step.get("name", "")), str(step.get("file", "")),
                    )).casefold()
                    for path in method["implementation_paths"] for step in path
                )
                if expects_typeorm and not method["persistence"]:
                    method["resolution"] = "implementation_partial"
                    incomplete.append({
                        "kind": "repository_persistence",
                        "symbol": qualified_name,
                        "reason": (
                            "TypeORM implementation found, but no entity "
                            "or table access was resolved"
                        ),
                    })
            elif node is None or contract_name.startswith("I"):
                method["resolution"] = "unresolved"
                incomplete.append({
                    "kind": "repository_implementation",
                    "symbol": qualified_name,
                    "reason": "no repository implementation method matched",
                })
        repository["methods"].append(method)
    return sorted(groups.values(), key=lambda item: item["name"].casefold()), incomplete
