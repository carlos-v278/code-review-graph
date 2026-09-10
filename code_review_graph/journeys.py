"""Evidence-backed full-stack journeys built from the code graph."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .graph import GraphEdge, GraphNode, GraphStore
from .journey_consumers import (
    CONFIDENCE_LEVELS,
    CONSUMER_TYPES,
    entry_type,
    is_frontend_request,
    load_manifest,
    normalize_http_path,
    paths_match,
)
from .journey_events import add_event_dispatch_edges
from .journey_formatting import format_journeys_text
from .journey_paths import (
    downstream_path,
    frontend_prefixes,
    relation,
    upstream_path,
    walk,
)
from .journey_paths import (
    path as build_path,
)
from .journey_persistence import typeorm_entities, typeorm_persistence
from .tools._common import graph_provenance

__all__ = ["build_journeys", "format_journeys_text", "normalize_http_path"]

_TRAVERSAL_EDGES = frozenset({"CALLS", "REFERENCES"})


def _relative(file_path: str, root: Path) -> str:
    try:
        return Path(file_path).resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return file_path.replace("\\", "/")


def _evidence(
    node: GraphNode | None, relation: str, confidence: str, *, root: Path,
    edge: GraphEdge | None = None, reason: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"relation": relation, "confidence": confidence}
    if node is not None:
        result.update({
            "file": _relative(node.file_path, root),
            "symbol": node.qualified_name,
            "line": node.line_start,
        })
    if edge is not None:
        result["line"] = edge.line or result.get("line", 0)
    if reason:
        result["reason"] = reason
    return result


def _domain(node: GraphNode, root: Path) -> str:
    parts = _relative(node.file_path, root).split("/")
    if "use-cases" in parts:
        tail = parts[parts.index("use-cases") + 1:-1]
        return "/".join(tail) or "use-cases"
    return "/".join(parts[:-1]) or "."


def _repository_contract(
    qualified_name: str, node: GraphNode | None,
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


def _repository_implementation_paths(
    repository_qn: str, base_path: list[dict[str, Any]], *,
    implementations: dict[str, list[GraphNode]],
    outgoing: dict[str, list[tuple[str, GraphEdge]]],
    nodes_by_qn: dict[str, GraphNode], root: Path,
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
        for key in contract_keys for node in implementations.get(key, [])
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
                nodes_by_qn[qn] for qn, distance in reachable.items()
                if distance > 0 and qn in nodes_by_qn
                and nodes_by_qn[qn].kind == "Function"
                and (
                    "/mappers/" in _relative(nodes_by_qn[qn].file_path, root).casefold()
                    or "mapper" in " ".join((
                        nodes_by_qn[qn].name,
                        nodes_by_qn[qn].parent_name or "",
                    )).casefold()
                )
            ),
            key=lambda node: (reachable[node.qualified_name], node.qualified_name),
        )
        if not mappers:
            paths.append(prefix)
            continue
        for mapper in mappers:
            mapper_path = downstream_path(
                mapper.qualified_name, {method_qn}, evidence,
                nodes_by_qn=nodes_by_qn, root=root,
            )
            paths.append([*prefix, *mapper_path[1:]])
    signatures = [tuple(step["symbol"] for step in path) for path in paths]
    maximal_paths = []
    for index, path in enumerate(paths):
        signature = signatures[index]
        if any(
            len(signature) < len(other) and other[:len(signature)] == signature
            for other_index, other in enumerate(signatures) if other_index != index
        ):
            continue
        maximal_paths.append(path)
    return maximal_paths


def _provenance(store: GraphStore, root: Path) -> dict[str, Any]:
    result = graph_provenance(str(root)) or {}
    for field, key in (
        ("built_at_sha", "git_head_sha"),
        ("built_on_branch", "git_branch"),
        ("updated_at", "last_updated"),
    ):
        value = store.get_metadata(key)
        if field not in result and value:
            result[field] = value
    current = result.get("head_matches_build")
    result["freshness"] = (
        "current" if current is True else "stale" if current is False
        else "unknown"
    )
    return result


def build_journeys(
    store: GraphStore, repo_root: str | Path, *,
    api_prefixes: Iterable[str] = (), consumer_manifest: str | None = None,
    consumer_types: Iterable[str] = (), confidences: Iterable[str] = (),
    limit: int = 50, target: str | None = None, details: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    api_prefixes = tuple(api_prefixes)
    selected_types, selected_confidences = set(consumer_types), set(confidences)
    if selected_types - CONSUMER_TYPES or selected_confidences - CONFIDENCE_LEVELS:
        raise ValueError("unsupported consumer type or confidence")
    manifest = load_manifest(consumer_manifest)
    nodes = store.get_all_nodes(exclude_files=False)
    edges = store.get_all_edges()
    nodes_by_qn = {node.qualified_name: node for node in nodes}
    use_cases = sorted(
        (node for node in nodes
         if node.kind == "Class" and node.name.endswith("UseCase")),
        key=lambda item: (item.name.casefold(), item.qualified_name),
    )
    if target:
        exact = [n for n in use_cases if target in (n.name, n.qualified_name)]
        matches = exact or [
            n for n in use_cases
            if target.casefold() in n.name.casefold()
            or target.casefold() in n.qualified_name.casefold()
        ]
        if not matches:
            return {"status": "not_found", "target": target, "candidates": []}
        if len(matches) > 1:
            return {
                "status": "ambiguous", "target": target,
                "candidates": [n.qualified_name for n in matches[:limit]],
                "candidate_count": len(matches),
            }
        use_cases = matches

    incoming: dict[str, list[tuple[str, GraphEdge]]] = defaultdict(list)
    outgoing: dict[str, list[tuple[str, GraphEdge]]] = defaultdict(list)
    handles: dict[str, list[tuple[GraphNode, GraphEdge]]] = defaultdict(list)
    request_edges: dict[str, list[GraphEdge]] = defaultdict(list)
    implementations: dict[str, list[GraphNode]] = defaultdict(list)
    for edge in edges:
        if edge.kind in _TRAVERSAL_EDGES:
            incoming[edge.target_qualified].append((edge.source_qualified, edge))
            outgoing[edge.source_qualified].append((edge.target_qualified, edge))
        if edge.kind == "HANDLES" and edge.target_qualified in nodes_by_qn:
            handles[edge.source_qualified].append(
                (nodes_by_qn[edge.target_qualified], edge),
            )
        if edge.kind == "REQUESTS":
            request_edges[edge.target_qualified].append(edge)
        if edge.kind in {"IMPLEMENTS", "INHERITS"}:
            implementation = nodes_by_qn.get(edge.source_qualified)
            if implementation is not None and implementation.kind == "Class":
                implementations[edge.target_qualified].append(implementation)
                implementations[
                    edge.target_qualified.rsplit("::", 1)[-1]
                ].append(implementation)
    source_cache: dict[str, list[str]] = {}
    event_handlers = add_event_dispatch_edges(
        nodes, incoming=incoming, outgoing=outgoing, source_cache=source_cache,
    )
    endpoints = [n for n in nodes if n.kind == "Endpoint"]
    endpoint_requests: dict[str, list[GraphNode]] = defaultdict(list)
    ambiguous_endpoints: set[str] = set()
    for request in (n for n in nodes if n.kind == "HttpRequest"):
        if request.extra.get("dynamic") or not is_frontend_request(request, root):
            continue
        method = str(request.extra.get("http_method", "")).upper()
        path = normalize_http_path(str(request.extra.get("route", "")), api_prefixes)
        matches = [
            endpoint for endpoint in endpoints
            if not endpoint.extra.get("dynamic")
            and str(endpoint.extra.get("http_method", "")).upper() == method
            and paths_match(
                path, normalize_http_path(
                    str(endpoint.extra.get("route", "")), api_prefixes,
                ),
            )
        ]
        if len(matches) == 1:
            endpoint_requests[matches[0].qualified_name].append(request)
        elif len(matches) > 1:
            ambiguous_endpoints.update(n.qualified_name for n in matches)

    entities_by_name = typeorm_entities(nodes)
    journeys: list[dict[str, Any]] = []
    for use_case in use_cases:
        roots = {use_case.qualified_name} | {
            node.qualified_name for node in nodes
            if node.qualified_name.startswith(use_case.qualified_name + ".")
        }
        upstream, upstream_edges = walk(roots, incoming)
        downstream, downstream_edges = walk(roots, outgoing)
        consumers: list[dict[str, Any]] = []
        ambiguities: list[dict[str, Any]] = []
        incomplete_paths: list[dict[str, Any]] = []
        effects = []
        dispatched_events: set[str] = set()
        for handler_qn, event_name in event_handlers.items():
            if handler_qn not in downstream:
                continue
            handler = nodes_by_qn.get(handler_qn)
            if handler is None:
                continue
            dispatched_events.add(event_name)
            effects.append({
                "type": "event",
                "event": event_name,
                "name": handler.parent_name or handler.name,
                "handler": handler.name,
                "confidence": "probable",
                "path": downstream_path(
                    handler_qn, roots, downstream_edges,
                    nodes_by_qn=nodes_by_qn, root=root,
                ),
                "evidence": _evidence(
                    handler, "handled_by", "probable",
                    edge=downstream_edges.get(handler_qn), root=root,
                    reason="event type matches @OnEvent; runtime guards are not evaluated",
                ),
            })
        for event_name in sorted(dispatched_events):
            incomplete_paths.append({
                "kind": "event_dispatch",
                "symbol": event_name,
                "reason": (
                    "matching handlers are shown, but runtime handler guards "
                    "are not evaluated"
                ),
            })
        for handler_qn, distance in upstream.items():
            for endpoint, handles_edge in handles.get(handler_qn, []):
                confidence = (
                    "unknown" if endpoint.extra.get("dynamic") else "confirmed"
                )
                consumer: dict[str, Any] = {
                    "type": "http", "name": endpoint.parent_name or endpoint.name,
                    "method": endpoint.extra.get("http_method"),
                    "route": endpoint.extra.get("route"),
                    "confidence": confidence,
                    "external_status": (
                        "unknown" if "bot" in (endpoint.parent_name or "").casefold()
                        else "not_applicable"
                    ),
                    "evidence": [
                        _evidence(endpoint, "entry", confidence, root=root),
                        _evidence(
                            nodes_by_qn.get(handler_qn),
                            "call" if distance <= 1 else "reachable",
                            confidence, edge=upstream_edges.get(handler_qn),
                            root=root,
                        ),
                    ],
                }
                requests = endpoint_requests.get(endpoint.qualified_name, [])
                if requests:
                    consumer["type"] = "frontend"
                    frontend_requests = []
                    for request in requests:
                        frontend_request: dict[str, Any] = {
                            "method": request.extra.get("http_method"),
                            "route": request.extra.get("route"),
                            "evidence": _evidence(
                                request, "request", "confirmed", root=root,
                            ),
                        }
                        if details:
                            request_edge = next(iter(request_edges.get(
                                request.qualified_name, [],
                            )), None)
                            handler_path = upstream_path(
                                handler_qn, roots, upstream_edges,
                                nodes_by_qn=nodes_by_qn, root=root,
                            )
                            qualified_names = [request.qualified_name, endpoint.qualified_name]
                            relations = [relation(
                                None, root=root, name="route_match",
                                reason=(
                                    f"{request.extra.get('http_method')} "
                                    f"{request.extra.get('route')} matches "
                                    f"{endpoint.extra.get('route')}"
                                ),
                            )]
                            if request_edge is not None:
                                qualified_names.insert(0, request_edge.source_qualified)
                                relations.insert(0, relation(request_edge, root=root))
                            qualified_names.extend(
                                step["symbol"] for step in handler_path
                            )
                            relations.append(relation(
                                handles_edge, root=root, name="handled_by",
                            ))
                            relations.extend(
                                step["via"] for step in handler_path[1:]
                            )
                            base_path = build_path(
                                qualified_names, relations,
                                nodes_by_qn=nodes_by_qn, root=root,
                            )
                            prefixes = (
                                frontend_prefixes(
                                    request_edge.source_qualified, incoming,
                                    nodes_by_qn=nodes_by_qn, root=root,
                                )
                                if request_edge is not None else []
                            )
                            frontend_request["paths"] = (
                                [[*prefix, *base_path[1:]] for prefix in prefixes]
                                or [base_path]
                            )
                        frontend_requests.append(frontend_request)
                    consumer["frontend_requests"] = frontend_requests
                elif details:
                    handler_path = upstream_path(
                        handler_qn, roots, upstream_edges,
                        nodes_by_qn=nodes_by_qn, root=root,
                    )
                    consumer["path"] = build_path(
                        [endpoint.qualified_name] + [
                            step["symbol"] for step in handler_path
                        ],
                        [relation(handles_edge, root=root, name="handled_by")] + [
                            step["via"] for step in handler_path[1:]
                        ],
                        nodes_by_qn=nodes_by_qn, root=root,
                    )
                if endpoint.qualified_name in ambiguous_endpoints:
                    ambiguities.append({
                        "kind": "route_match",
                        "method": endpoint.extra.get("http_method"),
                        "route": endpoint.extra.get("route"),
                        "reason": "multiple backend endpoints match the same request",
                    })
                consumers.append(consumer)

        seen_entries: set[tuple[str, str]] = set()
        for qn, distance in upstream.items():
            node = nodes_by_qn.get(qn)
            if node is None:
                continue
            consumer_type = entry_type(node)
            if consumer_type is None:
                continue
            key = (consumer_type, node.parent_name or node.name)
            if key in seen_entries:
                continue
            seen_entries.add(key)
            confidence = "confirmed" if distance <= 3 else "probable"
            consumer = {
                "type": consumer_type, "name": node.parent_name or node.name,
                "confidence": confidence,
                "evidence": [_evidence(
                    node, "call" if distance <= 1 else "reachable",
                    confidence, edge=upstream_edges.get(qn), root=root,
                )],
            }
            if details:
                consumer["path"] = upstream_path(
                    qn, roots, upstream_edges, nodes_by_qn=nodes_by_qn, root=root,
                )
            consumers.append(consumer)

        endpoint_pairs = {
            (str(item.get("method", "")).upper(),
             normalize_http_path(str(item.get("route", "")), api_prefixes))
            for item in consumers if item.get("method") and item.get("route")
        }
        for declaration in manifest:
            applies = declaration.get("use_case") in (
                use_case.name, use_case.qualified_name,
            )
            if declaration.get("route") and declaration.get("method"):
                applies = (
                    declaration["method"].upper(),
                    normalize_http_path(declaration["route"], api_prefixes),
                ) in endpoint_pairs
            if applies:
                consumers.append({
                    "type": declaration["type"],
                    "name": declaration.get("name", "declared consumer"),
                    "confidence": "probable", "external_status": "declared",
                    "evidence": [{
                        "relation": "declared", "confidence": "probable",
                        "file": str(Path(consumer_manifest or "")),
                        "reason": "consumer manifest declaration",
                    }],
                })

        repository_groups: dict[str, dict[str, Any]] = {}
        for qn, distance in downstream.items():
            if qn in roots:
                continue
            node = nodes_by_qn.get(qn)
            identity_text = (
                " ".join((node.name, node.parent_name or ""))
                if node is not None else qn.rsplit("::", 1)[-1]
            )
            if "repository" not in identity_text.casefold():
                continue
            contract_qn, contract_name, contract, is_method = _repository_contract(
                qn, node, nodes_by_qn,
            )
            confidence = "confirmed" if node is not None else "probable"
            repository = repository_groups.setdefault(contract_qn, {
                "id": contract_qn,
                "name": contract_name,
                "confidence": "confirmed" if contract is not None else confidence,
                "methods": [],
            })
            if not is_method:
                repository["evidence"] = _evidence(
                    node, "reference", confidence,
                    edge=downstream_edges.get(qn), root=root,
                )
                continue
            if any(item["id"] == qn for item in repository["methods"]):
                continue
            repository_method: dict[str, Any] = {
                "id": qn,
                "name": qn.rsplit(".", 1)[-1],
                "confidence": confidence,
                "resolution": "graph_node" if node is not None else "unresolved",
                "evidence": _evidence(
                    node, "call" if distance <= 1 else "reachable",
                    confidence, edge=downstream_edges.get(qn),
                    reason=(None if node is not None
                            else "repository method target is not indexed"),
                    root=root,
                ),
            }
            if details:
                repository_method["path"] = downstream_path(
                    qn, roots, downstream_edges,
                    nodes_by_qn=nodes_by_qn, root=root,
                )
                repository_method["implementation_paths"] = (
                    _repository_implementation_paths(
                        qn, repository_method["path"], implementations=implementations,
                        outgoing=outgoing, nodes_by_qn=nodes_by_qn, root=root,
                    )
                )
                if repository_method["implementation_paths"]:
                    repository_method["confidence"] = "confirmed"
                    repository_method["resolution"] = "implementation"
                    repository_method["evidence"].pop("reason", None)
                    repository_method["evidence"]["reason"] = (
                        "repository method resolved through its implementation"
                    )
                    for path in [
                        repository_method["path"],
                        *repository_method["implementation_paths"],
                    ]:
                        for step in path:
                            if step["symbol"] != qn:
                                continue
                            step["kind"] = "RepositoryMethod"
                            if contract is not None:
                                step.update({
                                    "file": _relative(contract.file_path, root),
                                    "line": contract.line_start,
                                })
                    persistence = []
                    for path in repository_method["implementation_paths"]:
                        implementation_method = next((
                            step["symbol"] for step in path
                            if step.get("via", {}).get("relation") == "implemented_by"
                        ), None)
                        if implementation_method is not None:
                            persistence.extend(typeorm_persistence(
                                implementation_method, outgoing=outgoing,
                                nodes_by_qn=nodes_by_qn,
                                entities=entities_by_name, root=root,
                                source_cache=source_cache,
                            ))
                    repository_method["persistence"] = list({
                        (item["entity"], item["table"], item["access"]): item
                        for item in persistence
                    }.values())
                    expects_typeorm = any(
                        "typeorm" in " ".join((
                            str(step.get("name", "")),
                            str(step.get("file", "")),
                        )).casefold()
                        for path in repository_method["implementation_paths"]
                        for step in path
                    )
                    if expects_typeorm and not repository_method["persistence"]:
                        repository_method["resolution"] = "implementation_partial"
                        incomplete_paths.append({
                            "kind": "repository_persistence",
                            "symbol": qn,
                            "reason": (
                                "TypeORM implementation found, but no entity "
                                "or table access was resolved"
                            ),
                        })
                elif node is None or contract_name.startswith("I"):
                    repository_method["resolution"] = "unresolved"
                    incomplete_paths.append({
                        "kind": "repository_implementation",
                        "symbol": qn,
                        "reason": "no repository implementation method matched",
                    })
            repository["methods"].append(repository_method)
        repositories = sorted(
            repository_groups.values(), key=lambda item: item["name"].casefold(),
        )
        tests = []
        for qn, distance in upstream.items():
            node = nodes_by_qn.get(qn)
            if node is not None and node.is_test:
                test = {
                    "name": node.name,
                    "coverage": "direct" if distance == 1 else "indirect",
                    "evidence": _evidence(
                        node, "reference" if distance == 1 else "reachable",
                        "confirmed", edge=upstream_edges.get(qn), root=root,
                    ),
                }
                tests.append(test)
        if selected_types and not any(c["type"] in selected_types for c in consumers):
            continue
        if selected_confidences and not any(
            c["confidence"] in selected_confidences for c in consumers
        ):
            continue
        journeys.append({
            "id": use_case.qualified_name, "name": use_case.name,
            "domain": _domain(use_case, root),
            "consumer_status": "identified" if consumers else "unknown",
            "consumers": consumers, "effects": effects,
            "repositories": repositories,
            "tests": tests, "ambiguities": ambiguities,
            "incomplete_paths": incomplete_paths,
            "analysis_status": (
                "incomplete" if incomplete_paths or ambiguities else "complete"
            ),
        })

    total = len(journeys)
    shown = journeys[:limit]
    provenance = _provenance(store, root)
    stale = provenance.get("freshness") != "current"
    incomplete = any(
        journey["analysis_status"] == "incomplete" for journey in journeys
    )
    return {
        "status": "ok", "schema_version": 1, "provenance": provenance,
        "coverage": {
            "complete": not stale and not incomplete,
            "recognized_syntaxes": [
                "NestJS @Controller + HTTP method decorators",
                "fetch(url, options)", "Axios and named API/HTTP clients",
                "typed call and reference graph edges",
                "derived domain event publisher and @OnEvent handler links",
            ],
            "limitations": [
                "dynamic routes remain visible but are not matched",
                "runtime-only dispatch and telemetry are not inferred",
                "external consumers require an explicit YAML declaration",
                *(["graph freshness is not confirmed; output is not complete"]
                  if stale else []),
                *(["one or more detailed paths are incomplete or ambiguous"]
                  if incomplete else []),
            ],
        },
        "total": total, "shown": len(shown), "truncated": total > len(shown),
        "journeys": shown,
    }
