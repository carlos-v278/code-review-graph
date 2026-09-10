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
    load_manifest,
    normalize_http_path,
)
from .journey_events import add_event_dispatch_edges
from .journey_formatting import format_journeys_text
from .journey_paths import (
    downstream_path,
    frontend_prefixes,
    hidden_beyond_depth,
    link_metadata,
    relation,
    upstream_path,
    walk,
)
from .journey_paths import (
    path as build_path,
)
from .journey_persistence import typeorm_entities
from .journey_repositories import collect_repositories
from .journey_results import (
    graph_selection_matches,
    index_candidate_tests,
    payload_selection_matches,
    route_selection_matches,
    shape_journey_links,
)
from .journey_routes import match_frontend_routes
from .journey_source import relative_path
from .tools._common import graph_provenance

__all__ = ["build_journeys", "format_journeys_text", "normalize_http_path"]

_TRAVERSAL_EDGES = frozenset({"CALLS", "REFERENCES"})


def _relative(file_path: str, root: Path) -> str:
    return relative_path(file_path, root)


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
    max_depth: int = 4, max_consumers: int = 10, max_tests: int = 20,
    source_file: str | None = None, source_component: str | None = None,
    source_route: str | None = None,
    changed_files: Iterable[str] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    api_prefixes = tuple(api_prefixes)
    selected_types, selected_confidences = set(consumer_types), set(confidences)
    if selected_types - CONSUMER_TYPES or selected_confidences - CONFIDENCE_LEVELS:
        raise ValueError("unsupported consumer type or confidence")
    manifest = load_manifest(consumer_manifest)
    changed_files = tuple(changed_files or ())
    selection_requested = bool(
        source_file or source_component or source_route or changed_files
    )
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
    endpoint_requests, endpoint_ambiguities = match_frontend_routes(
        nodes,
        root,
        api_prefixes=api_prefixes,
        candidate_limit=max_consumers if details else min(3, max_consumers),
    )

    entities_by_name = typeorm_entities(nodes)
    candidate_tests = (
        index_candidate_tests(nodes, (item.name for item in use_cases), root)
        if details else {}
    )
    journeys: list[dict[str, Any]] = []
    for use_case in use_cases:
        roots = {use_case.qualified_name} | {
            node.qualified_name for node in nodes
            if node.qualified_name.startswith(use_case.qualified_name + ".")
        }
        upstream, upstream_edges = walk(roots, incoming, max_depth=max_depth)
        downstream, downstream_edges = walk(roots, outgoing, max_depth=max_depth)
        depth_hidden = hidden_beyond_depth(roots, incoming, max_depth)
        depth_hidden += hidden_beyond_depth(roots, outgoing, max_depth)
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
                "link": link_metadata(
                    handler_qn, roots, downstream_edges,
                    direction="downstream", distance=downstream[handler_qn],
                ),
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
                link = link_metadata(
                    handler_qn, roots, upstream_edges,
                    direction="upstream", distance=distance,
                )
                confidence = (
                    "unknown" if endpoint.extra.get("dynamic")
                    else "probable" if link["conditional"]
                    else "confirmed"
                )
                consumer: dict[str, Any] = {
                    "type": "http", "name": endpoint.parent_name or endpoint.name,
                    "method": endpoint.extra.get("http_method"),
                    "route": endpoint.extra.get("route"),
                    "confidence": confidence,
                    "link": link,
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
                        request_edge = next(iter(request_edges.get(
                            request.qualified_name, [],
                        )), None)
                        prefixes = (
                            frontend_prefixes(
                                request_edge.source_qualified, incoming,
                                nodes_by_qn=nodes_by_qn, root=root,
                            )
                            if request_edge is not None else []
                        )
                        source_steps = [
                            step for prefix in prefixes for step in prefix
                        ]
                        if request_edge is not None:
                            source_steps.extend(build_path(
                                [request_edge.source_qualified], [],
                                nodes_by_qn=nodes_by_qn, root=root,
                            ))
                        sources_by_file: dict[str, dict[str, Any]] = {}
                        for step in source_steps:
                            file_path = str(step.get("file", ""))
                            if not file_path:
                                continue
                            source = sources_by_file.setdefault(file_path, {
                                "name": (
                                    Path(file_path).name
                                    if file_path.endswith(".vue")
                                    else step.get("name", Path(file_path).name)
                                ),
                                "file": file_path,
                                "line": step.get("line"),
                                "symbol_count": 0,
                            })
                            source["symbol_count"] += 1
                        def source_order(item: dict[str, Any]) -> tuple[int, str]:
                            file_path = str(item["file"])
                            priority = (
                                0 if "/views/" in file_path
                                else 1 if "/services/" in file_path
                                else 2 if file_path.endswith(".vue")
                                else 3
                            )
                            return priority, file_path
                        sources = sorted(sources_by_file.values(), key=source_order)
                        source_limit = max_consumers if details else min(3, max_consumers)
                        frontend_request["sources"] = sources[:source_limit]
                        frontend_request["sources_hidden"] = max(
                            0, len(sources) - source_limit,
                        )
                        if details or selection_requested:
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
                            frontend_request["paths"] = (
                                [[*prefix, *base_path[1:]] for prefix in prefixes]
                                or [base_path]
                            )
                        frontend_requests.append(frontend_request)
                    consumer["frontend_requests"] = frontend_requests
                elif details or selection_requested:
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
                ambiguities.extend(
                    endpoint_ambiguities.get(endpoint.qualified_name, []),
                )
                consumers.append(consumer)

        seen_entries: set[tuple[str, str]] = set()
        for qn, distance in sorted(
            upstream.items(), key=lambda item: (item[1], item[0]),
        ):
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
            link = link_metadata(
                qn, roots, upstream_edges,
                direction="upstream", distance=distance,
            )
            if consumer_type == "event":
                link.update({
                    "scope": "indirect",
                    "conditional": True,
                    "reason": (
                        "event-handler invocation depends on runtime dispatch and guards"
                    ),
                })
                confidence = "probable"
            consumer = {
                "type": consumer_type, "name": node.parent_name or node.name,
                "confidence": confidence, "link": link,
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
                    "link": {
                        "scope": "direct", "depth": 0, "conditional": False,
                        "reason": "consumer manifest declaration", "edge_kinds": [],
                    },
                    "evidence": [{
                        "relation": "declared", "confidence": "probable",
                        "file": str(Path(consumer_manifest or "")),
                        "reason": "consumer manifest declaration",
                    }],
                })

        repositories, repository_incomplete = collect_repositories(
            downstream=downstream,
            downstream_edges=downstream_edges,
            roots=roots,
            nodes_by_qn=nodes_by_qn,
            implementations=implementations,
            outgoing=outgoing,
            entities_by_name=entities_by_name,
            root=root,
            source_cache=source_cache,
            details=details,
        )
        incomplete_paths.extend(repository_incomplete)
        tests: list[dict[str, Any]] = []
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
        represented_test_files = {
            item.get("evidence", {}).get("file") for item in tests
        }
        tests.extend(
            item for item in candidate_tests.get(use_case.name, [])
            if item.get("evidence", {}).get("file") not in represented_test_files
        )
        if selected_types and not any(c["type"] in selected_types for c in consumers):
            continue
        if selected_confidences and not any(
            c["confidence"] in selected_confidences for c in consumers
        ):
            continue
        selection = graph_selection_matches(
            nodes_by_qn=nodes_by_qn,
            upstream=upstream,
            downstream=downstream,
            root=root,
            source_file=source_file,
            source_component=source_component,
            changed_files=changed_files,
        ) if selection_requested else []
        selection.extend(payload_selection_matches(
            consumers,
            source_file=source_file,
            source_component=source_component,
            source_files=changed_files,
        ))
        selection.extend(route_selection_matches(consumers, source_route))
        if selection_requested and not selection:
            continue
        journey = {
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
        }
        if selection:
            journey["selection"] = selection
        journeys.append(shape_journey_links(
            journey,
            details=details,
            max_consumers=max_consumers,
            max_tests=max_tests,
            max_depth=max_depth,
            depth_hidden=depth_hidden,
        ))

    total = len(journeys)
    shown = journeys[:limit]
    provenance = _provenance(store, root)
    stale = provenance.get("freshness") != "current"
    incomplete = any(
        journey["analysis_status"] == "incomplete" for journey in journeys
    )
    return {
        "status": "ok", "schema_version": 1, "provenance": provenance,
        "query": {
            "file": source_file,
            "component": source_component,
            "route": source_route,
            "changed_files": list(changed_files[:min(3, max_consumers)]),
            "changed_files_hidden": max(
                0, len(changed_files) - min(3, max_consumers),
            ),
            "max_depth": max_depth,
            "max_consumers": max_consumers,
            "max_tests": max_tests,
            "details": details,
        },
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
