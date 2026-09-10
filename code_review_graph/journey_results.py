"""Selection, limits, and compact result shaping for journeys."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .graph import GraphNode
from .journey_consumers import normalize_http_path, paths_match
from .journey_source import relative_path

_HTTP_METHODS = frozenset({
    "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT",
})


def infer_journey_selector(
    value: str, repo_root: Path,
) -> dict[str, str] | None:
    """Interpret an explicit singular lookup without shadowing use-case names."""
    if "::" in value or value.casefold().endswith("usecase"):
        return None
    method_and_route = value.split(maxsplit=1)
    if len(method_and_route) == 2 and method_and_route[0].upper() in _HTTP_METHODS:
        return {"source_route": value}
    if value.startswith("/") and not Path(value).is_file():
        return {"source_route": value}
    if (repo_root / value).is_file() or (
        Path(value).suffix and ("/" in value or "\\" in value)
    ):
        return {"source_file": value}
    if Path(value).suffix or value.casefold().endswith(
        ("component", "controller", "layout", "page", "service", "view"),
    ):
        return {"source_component": value}
    return None


def split_and_limit(
    items: list[dict[str, Any]], limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, int]:
    direct = [item for item in items if item.get("link", {}).get("scope") == "direct"]
    indirect = [item for item in items if item.get("link", {}).get("scope") != "direct"]
    return direct[:limit], indirect[:limit], max(0, len(direct) - limit), max(
        0, len(indirect) - limit,
    )


def group_tests(
    tests: list[dict[str, Any]], *, include_entries: bool = True,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for test in tests:
        evidence = test.get("evidence", {})
        grouped[(str(evidence.get("file", "unknown")), test["coverage"])].append(test)
    result = []
    order = {"direct": 0, "indirect": 1, "candidate": 2}
    for (file_path, classification), entries in sorted(
        grouped.items(), key=lambda item: (
            order.get(item[0][1], 9), item[0][0],
        ),
    ):
        group: dict[str, Any] = {
            "file": file_path,
            "classification": classification,
            "count": len(entries),
            "coverage_claim": (
                "relationship evidence only; behavior coverage is not proven"
            ),
        }
        if include_entries:
            group["tests"] = entries
        result.append(group)
    return result


def index_candidate_tests(
    nodes: list[GraphNode],
    use_case_names: Iterable[str],
    root: Path,
) -> dict[str, list[dict[str, Any]]]:
    known_names = set(use_case_names)
    mention_pattern = re.compile(r"\b[A-Za-z_$][\w$]*UseCase\b")
    files = sorted({
        Path(node.file_path)
        for node in nodes
        if node.is_test or re.search(
            r"(?:^|/)(?:test|tests|__tests__)(?:/|$)|\.(?:spec|test)\.",
            node.file_path.replace("\\", "/").casefold(),
        )
    })
    found: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for file_path in files:
        try:
            source = file_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for name in sorted(set(mention_pattern.findall(source)) & known_names):
            found[name].append({
                    "name": file_path.name,
                    "coverage": "candidate",
                    "evidence": {
                        "relation": "source_mention",
                        "confidence": "unknown",
                        "file": relative_path(str(file_path), root),
                        "reason": (
                            "the file mentions the use case; behavior coverage "
                            "has not been established"
                        ),
                    },
                })
    return dict(found)


def compact_item(value: Any, *, preserve_evidence: bool = False) -> Any:
    if isinstance(value, list):
        return [
            compact_item(item, preserve_evidence=preserve_evidence)
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {"path", "paths", "implementation_paths", "symbol"}:
            continue
        if key == "evidence" and not preserve_evidence:
            continue
        result[key] = compact_item(
            item,
            preserve_evidence=preserve_evidence or key == "ambiguities",
        )
    return result


def shape_journey_links(
    journey: dict[str, Any],
    *,
    details: bool,
    max_consumers: int,
    max_tests: int,
    max_depth: int,
    depth_hidden: int = 0,
) -> dict[str, Any]:
    (
        direct_consumers,
        indirect_consumers,
        hidden_direct_consumers,
        hidden_indirect_consumers,
    ) = split_and_limit(journey.get("consumers", []), max_consumers)
    (
        direct_repositories,
        indirect_repositories,
        hidden_direct_repositories,
        hidden_indirect_repositories,
    ) = split_and_limit(journey.get("repositories", []), max_consumers)
    direct_tests = [
        item for item in journey.get("tests", [])
        if item.get("coverage") == "direct"
    ]
    indirect_tests = [
        item for item in journey.get("tests", [])
        if item.get("coverage") == "indirect"
    ]
    candidate_tests = [
        item for item in journey.get("tests", [])
        if item.get("coverage") == "candidate"
    ]
    shown_direct_tests = direct_tests[:max_tests]
    remaining = max(0, max_tests - len(shown_direct_tests))
    shown_indirect_tests = indirect_tests[:remaining]
    remaining = max(0, remaining - len(shown_indirect_tests))
    shown_candidate_tests = candidate_tests[:remaining]

    result = dict(journey)
    selection = result.get("selection", [])
    selection_limit = max_consumers if details else min(3, max_consumers)
    result["selection"] = selection[:selection_limit]
    result["consumers"] = direct_consumers
    result["repositories"] = direct_repositories
    result["tests"] = shown_direct_tests
    shown_tests = [
        *shown_direct_tests,
        *(shown_indirect_tests if details else []),
        *(shown_candidate_tests if details else []),
    ]
    result["test_files"] = group_tests(shown_tests, include_entries=details)
    if details:
        result["indirect"] = {
            "consumers": indirect_consumers,
            "repositories": indirect_repositories,
            "tests": shown_indirect_tests,
            "test_candidates": shown_candidate_tests,
            "max_depth": max_depth,
        }
    omitted_indirect_consumers = (
        hidden_indirect_consumers
        if details else len(indirect_consumers) + hidden_indirect_consumers
    )
    omitted_indirect_repositories = (
        hidden_indirect_repositories
        if details else len(indirect_repositories) + hidden_indirect_repositories
    )
    effects = result.get("effects", [])
    result["hidden"] = {
        "consumers": hidden_direct_consumers + (
            omitted_indirect_consumers
        ),
        "repositories": hidden_direct_repositories + (
            omitted_indirect_repositories
        ),
        "tests": max(0, len(direct_tests) - len(shown_direct_tests))
        + len(indirect_tests) - (len(shown_indirect_tests) if details else 0)
        + len(candidate_tests) - (len(shown_candidate_tests) if details else 0),
        "depth": depth_hidden,
        "effects": (
            max(0, len(effects) - max_consumers) if details else len(effects)
        ),
        "ambiguities": max(0, len(result.get("ambiguities", [])) - max_consumers),
        "selection": max(0, len(selection) - selection_limit),
    }
    result["effects"] = effects[:max_consumers] if details else []
    result["ambiguities"] = result.get("ambiguities", [])[:max_consumers]
    return result if details else compact_item(result)


def graph_selection_matches(
    *,
    nodes_by_qn: dict[str, GraphNode],
    upstream: dict[str, int],
    downstream: dict[str, int],
    root: Path,
    source_file: str | None = None,
    source_component: str | None = None,
    changed_files: Iterable[str] = (),
) -> list[dict[str, Any]]:
    def normalize(value: str) -> str:
        path = Path(value)
        return (
            relative_path(str(path), root)
            if path.is_absolute()
            else path.as_posix().removeprefix("./")
        )

    wanted_files = {normalize(value) for value in changed_files}
    if source_file:
        wanted_files.add(normalize(source_file))
    component = (source_component or "").casefold()
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for direction, reachable in (("upstream", upstream), ("downstream", downstream)):
        for qualified_name, depth in reachable.items():
            node = nodes_by_qn.get(qualified_name)
            if node is None:
                continue
            file_path = relative_path(node.file_path, root)
            file_match = file_path in wanted_files
            component_match = bool(component) and component in " ".join(
                (
                    node.name,
                    node.parent_name or "",
                    Path(file_path).name,
                    qualified_name,
                ),
            ).casefold()
            if not file_match and not component_match:
                continue
            key = f"{direction}:{qualified_name}"
            if key in seen:
                continue
            seen.add(key)
            matches.append({
                "kind": "component" if component_match else "file",
                "value": source_component if component_match else file_path,
                "file": file_path,
                "symbol": qualified_name,
                "depth": depth,
                "direction": direction,
                "reason": f"{direction} graph dependency",
            })
    return sorted(matches, key=lambda item: (item["depth"], item["file"], item["symbol"]))


def route_selection_matches(
    consumers: list[dict[str, Any]], source_route: str | None,
    api_prefixes: Iterable[str] = (),
) -> list[dict[str, Any]]:
    if not source_route:
        return []
    method_and_route = source_route.split(maxsplit=1)
    exact_method = (
        method_and_route[0].upper()
        if len(method_and_route) == 2
        and method_and_route[0].upper() in _HTTP_METHODS else None
    )
    query_route = method_and_route[1] if exact_method else source_route
    normalized_query = normalize_http_path(query_route, api_prefixes)
    matches = []
    for consumer in consumers:
        routes = [(
            str(consumer.get("method", "")).upper(),
            str(consumer.get("route", "")),
        )]
        routes.extend(
            (
                str(request.get("method", "")).upper(),
                str(request.get("route", "")),
            )
            for request in consumer.get("frontend_requests", [])
        )
        for method, route in routes:
            normalized_route = normalize_http_path(route, api_prefixes)
            matches_query = (
                method == exact_method and paths_match(
                    normalized_route, normalized_query,
                )
                if exact_method else
                normalized_route.startswith(normalized_query)
            )
            if matches_query:
                matches.append({
                    "kind": "route",
                    "value": source_route,
                    "method": method,
                    "route": route,
                    "reason": (
                        "exact method and route match" if exact_method
                        else "route prefix match"
                    ),
                })
                break
    return matches


def payload_selection_matches(
    consumers: list[dict[str, Any]], *,
    source_file: str | None = None,
    source_component: str | None = None,
    source_files: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Find frontend evidence introduced by the synthetic route bridge."""
    wanted_files = {
        Path(item).as_posix().removeprefix("./") for item in source_files
    }
    if source_file:
        wanted_files.add(Path(source_file).as_posix().removeprefix("./"))
    source_file_value = Path(source_file).as_posix() if source_file else ""
    component = (source_component or "").casefold()
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        file_path = str(value.get("file", ""))
        label = " ".join(
            str(value.get(key, "")) for key in ("name", "symbol", "file")
        ).casefold()
        file_match = file_path in wanted_files or bool(source_file_value) and (
            source_file_value.endswith("/" + file_path)
        )
        component_match = bool(component) and component in label
        if file_match or component_match:
            key = (file_path, str(value.get("symbol", value.get("name", ""))))
            if key not in seen:
                seen.add(key)
                matches.append({
                    "kind": "component" if component_match else "file",
                    "value": source_component if component_match else file_path,
                    "file": file_path,
                    "symbol": value.get("symbol"),
                    "reason": "frontend route path",
                })
        for item in value.values():
            visit(item)

    visit(consumers)
    return matches
