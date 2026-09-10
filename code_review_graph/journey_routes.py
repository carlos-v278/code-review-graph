"""Frontend request to backend route matching for journeys."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .graph import GraphNode
from .journey_consumers import (
    is_frontend_request,
    normalize_http_path,
    paths_match,
)
from .journey_source import relative_path


def _evidence(node: GraphNode, root: Path) -> dict[str, Any]:
    return {
        "file": relative_path(node.file_path, root),
        "line": node.line_start,
        "symbol": node.qualified_name,
    }


def match_frontend_routes(
    nodes: list[GraphNode],
    root: Path,
    *,
    api_prefixes: Iterable[str] = (),
    candidate_limit: int = 3,
) -> tuple[
    dict[str, list[GraphNode]],
    dict[str, list[dict[str, Any]]],
]:
    """Return unique route matches and evidence for ambiguous matches."""
    endpoints = [
        node
        for node in nodes
        if node.kind == "Endpoint" and not node.extra.get("dynamic")
    ]
    endpoint_requests: dict[str, list[GraphNode]] = defaultdict(list)
    ambiguities: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for request in (node for node in nodes if node.kind == "HttpRequest"):
        if request.extra.get("dynamic") or not is_frontend_request(request, root):
            continue
        method = str(request.extra.get("http_method", "")).upper()
        request_path = normalize_http_path(
            str(request.extra.get("route", "")), api_prefixes,
        )
        matches = [
            endpoint
            for endpoint in endpoints
            if str(endpoint.extra.get("http_method", "")).upper() == method
            and paths_match(
                request_path,
                normalize_http_path(
                    str(endpoint.extra.get("route", "")), api_prefixes,
                ),
            )
        ]
        if len(matches) == 1:
            endpoint_requests[matches[0].qualified_name].append(request)
            continue
        if len(matches) < 2:
            continue

        ordered = sorted(matches, key=lambda item: item.qualified_name)
        candidates = [
            {
                "name": endpoint.parent_name or endpoint.name,
                "method": endpoint.extra.get("http_method"),
                "route": endpoint.extra.get("route"),
                "evidence": _evidence(endpoint, root),
            }
            for endpoint in ordered[:candidate_limit]
        ]
        ambiguity = {
            "kind": "route_match",
            "method": method,
            "route": request.extra.get("route"),
            "reason": "multiple backend endpoints match the frontend request",
            "request_evidence": _evidence(request, root),
            "candidates": candidates,
            "candidate_count": len(ordered),
            "candidates_hidden": max(0, len(ordered) - len(candidates)),
        }
        for endpoint in ordered:
            ambiguities[endpoint.qualified_name].append(ambiguity)
    return dict(endpoint_requests), dict(ambiguities)

