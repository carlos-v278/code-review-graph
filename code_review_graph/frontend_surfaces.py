"""Evidence-backed frontend surfaces related to changed business contracts."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

from .graph import GraphEdge

_SOURCE_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx"})
_SURFACE_SUFFIXES = frozenset({".jsx", ".tsx", ".vue"})
_DYNAMIC_SEGMENT = re.compile(r"^(?::|\{|\$\{|\[)")
_CONSTANT = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*:\s*['\"]([^'\"]+)['\"]")
_ROUTE_VALUE = re.compile(r"\b(path|name)\s*:\s*([^,\n]+)")
_CONTRACT_FILE = re.compile(
    r"(?:^|[.\-_])(dto|enum|interface|model|request|response|types?)(?:[.\-_]|$)",
)
_TEST_FILE = re.compile(r"(?:^|/)(?:test|tests|__tests__)(?:/|$)|\.(?:spec|test)\.")
_STOP_WORDS = frozenset({
    "admin", "api", "command", "contract", "create", "delete", "detail",
    "details", "domain", "dto", "entity", "enum", "get", "input",
    "interface", "item", "list", "model", "output", "request", "response",
    "state", "status", "type", "types", "update", "value", "values",
})


def _relative(root: Path, value: str) -> str | None:
    try:
        return Path(value).resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


def _singular(value: str) -> str:
    lowered = value.casefold()
    if lowered.endswith("ies") and len(lowered) > 3:
        return lowered[:-3] + "y"
    if lowered.endswith("s") and not lowered.endswith("ss") and len(lowered) > 3:
        return lowered[:-1]
    return lowered


def _trigger_kind(file_path: str) -> str | None:
    lowered = file_path.casefold().replace("\\", "/")
    if _TEST_FILE.search(lowered):
        return None
    if any(
        marker in lowered
        for marker in (
            "/domain/models/",
            "/domain/enums/",
            "/domain/value-objects/",
        )
    ):
        return "business_state"
    name = Path(lowered).name
    if "/dto/" in lowered or "/types/" in lowered or _CONTRACT_FILE.search(name):
        return "contract"
    return None


def _entity_tokens(file_path: str) -> set[str]:
    normalized = file_path.replace("\\", "/")
    lowered = normalized.casefold()
    tokens: set[str] = set()
    parts = lowered.split("/")
    for marker in ("models", "enums", "value-objects"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts) - 1:
                tokens.add(_singular(parts[index + 1]))
    filename = Path(lowered).name.split(".", 1)[0]
    for token in re.findall(r"[a-z][a-z0-9]*", filename):
        singular = _singular(token)
        if len(singular) >= 3 and singular not in _STOP_WORDS:
            tokens.add(singular)
    return tokens


def _router_file(path: Path) -> bool:
    lowered_parts = {part.casefold() for part in path.parts}
    return path.suffix.casefold() in _SOURCE_SUFFIXES and bool(
        lowered_parts & {"router", "routes", "routing"}
        or "route" in path.stem.casefold()
    )


def _constant_values(root: Path) -> dict[str, list[str]]:
    values: dict[str, list[str]] = defaultdict(list)
    for path in root.rglob("*"):
        if not path.is_file() or not _router_file(path):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            match = _CONSTANT.match(line)
            if match and match.group(2) not in values[match.group(1)]:
                values[match.group(1)].append(match.group(2))
    return dict(values)


def _binding(lines: list[str], line_number: int, key: str) -> tuple[str | None, int]:
    start = min(max(line_number - 1, 0), len(lines) - 1)
    for index in range(start, max(-1, start - 30), -1):
        for match in _ROUTE_VALUE.finditer(lines[index]):
            if match.group(1) == key:
                return match.group(2).strip(), index + 1
    return None, 0


def _constant_key(expression: str | None) -> str | None:
    if not expression:
        return None
    match = re.search(r"\.([A-Z][A-Z0-9_]*)\s*$", expression)
    return match.group(1) if match else None


def _literal(expression: str | None) -> str | None:
    if not expression:
        return None
    match = re.fullmatch(r"['\"]([^'\"]+)['\"]", expression.strip())
    return match.group(1) if match else None


def _resolved_route(
    path_expression: str | None,
    name_expression: str | None,
    constants: dict[str, list[str]],
) -> str | None:
    literal = _literal(path_expression)
    if literal and literal.startswith("/"):
        return literal
    for key in (_constant_key(name_expression), _constant_key(path_expression)):
        candidates = constants.get(key or "", [])
        absolute = next((value for value in candidates if value.startswith("/")), None)
        if absolute:
            return absolute
    if literal:
        return "/" + literal.strip("/")
    return None


def _surface_kind(route: str, entity: str) -> str | None:
    segments = [segment for segment in route.split("/") if segment]
    for index, segment in enumerate(segments):
        if _singular(segment) != entity:
            continue
        remainder = segments[index + 1:]
        if not remainder:
            return "list"
        if len(remainder) == 1 and _DYNAMIC_SEGMENT.match(remainder[0]):
            return "detail"
    return None


def _import_adjacency(
    root: Path,
    edges: Iterable[GraphEdge],
) -> tuple[dict[str, list[str]], list[GraphEdge]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    imports: list[GraphEdge] = []
    for edge in edges:
        if edge.kind != "IMPORTS_FROM":
            continue
        source = _relative(root, edge.source_qualified)
        target = _relative(root, edge.target_qualified)
        if source is None or target is None:
            continue
        imports.append(edge)
        if target not in adjacency[source]:
            adjacency[source].append(target)
    return dict(adjacency), imports


def _supporting_files(
    surface_file: str,
    adjacency: dict[str, list[str]],
    *,
    entity: str,
    max_depth: int = 4,
    limit: int = 10,
) -> tuple[list[dict[str, Any]], int]:
    queue = deque([(surface_file, 0)])
    seen = {surface_file}
    result: list[dict[str, Any]] = []
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for target in sorted(adjacency.get(current, [])):
            if target in seen:
                continue
            seen.add(target)
            queue.append((target, depth + 1))
            lowered = target.casefold()
            if (
                any(marker in lowered for marker in ("/services/", "/composables/"))
                or "/components/" in lowered and entity in lowered
                or any(
                    marker in Path(lowered).name for marker in ("column", "config", "table")
                )
            ):
                result.append({
                    "file": target,
                    "relation": "imports",
                    "depth": depth + 1,
                })

    def order(item: dict[str, Any]) -> tuple[int, int, str]:
        lowered = str(item["file"]).casefold()
        name = Path(lowered).name
        priority = (
            0 if any(marker in name for marker in ("column", "config", "table"))
            else 1 if entity in lowered
            else 2
        )
        return priority, int(item["depth"]), lowered

    ordered = sorted(result, key=order)
    return ordered[:limit], max(0, len(ordered) - limit)


def discover_frontend_surface_candidates(
    root: Path,
    edges: Iterable[GraphEdge],
    changed_files: Iterable[str],
    *,
    limit: int,
) -> dict[str, Any]:
    """Return unchanged list/detail surfaces requiring an explicit review decision."""
    root = root.resolve()
    changed = {Path(value).as_posix().removeprefix("./") for value in changed_files}
    triggers: dict[str, list[dict[str, str]]] = defaultdict(list)
    for file_path in sorted(changed):
        kind = _trigger_kind(file_path)
        if kind is None:
            continue
        for entity in sorted(_entity_tokens(file_path)):
            triggers[entity].append({"file": file_path, "kind": kind})
    if not triggers:
        return {
            "total": 0,
            "candidates": [],
            "candidates_hidden": 0,
            "supporting_files_hidden": 0,
            "required_checks": [],
            "checks_hidden": 0,
            "truncated": False,
        }

    constants = _constant_values(root)
    adjacency, imports = _import_adjacency(root, edges)
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in imports:
        route_file = _relative(root, edge.source_qualified)
        surface_file = _relative(root, edge.target_qualified)
        if route_file is None or surface_file is None or surface_file in changed:
            continue
        surface_path = root / surface_file
        if surface_path.suffix.casefold() not in _SURFACE_SUFFIXES:
            continue
        if not _router_file(root / route_file):
            continue
        try:
            lines = (root / route_file).read_text(
                encoding="utf-8", errors="replace",
            ).splitlines()
        except OSError:
            continue
        path_expression, path_line = _binding(lines, edge.line, "path")
        name_expression, _name_line = _binding(lines, edge.line, "name")
        route = _resolved_route(path_expression, name_expression, constants)
        if not route:
            continue
        for entity, entity_triggers in sorted(triggers.items()):
            kind = _surface_kind(route, entity)
            if kind is None:
                continue
            key = (route, surface_file)
            supporting_files, supporting_files_hidden = _supporting_files(
                surface_file,
                adjacency,
                entity=entity,
                limit=min(limit, 10),
            )
            candidates[key] = {
                "id": f"frontend-surface:{route}",
                "entity": entity,
                "kind": kind,
                "route": route,
                "file": surface_file,
                "decision": {
                    "required": True,
                    "status": "pending",
                    "allowed": ["adapted", "inspected_no_change", "blocked"],
                    "justification_required_for": [
                        "inspected_no_change", "blocked",
                    ],
                },
                "evidence": {
                    "triggers": entity_triggers,
                    "route": {"file": route_file, "line": path_line},
                    "supporting_files": supporting_files,
                    "supporting_files_hidden": supporting_files_hidden,
                },
            }

    ordered = sorted(
        candidates.values(),
        key=lambda item: (item["entity"], item["kind"] != "list", item["route"]),
    )
    visible = ordered[:limit]
    supporting_files_hidden = sum(
        int(item.get("evidence", {}).get("supporting_files_hidden", 0))
        for item in visible
    )
    checks: list[dict[str, Any]] = [
        {
            "id": item["id"],
            "kind": "frontend_surface",
            "target": item["route"],
            "file": item["file"],
            "status": "pending",
            "allowed_statuses": item["decision"]["allowed"],
        }
        for item in ordered
    ]
    by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in ordered:
        by_entity[item["entity"]].append(item)
    for entity, surfaces in sorted(by_entity.items()):
        kinds = {surface["kind"] for surface in surfaces}
        targets = [surface["route"] for surface in surfaces]
        if {"list", "detail"} <= kinds:
            checks.append({
                "id": f"frontend-consistency:{entity}",
                "kind": "list_detail_consistency",
                "entity": entity,
                "targets": targets,
                "status": "pending",
                "allowed_statuses": ["verified", "blocked"],
            })
        if any(
            trigger["kind"] == "business_state"
            for trigger in triggers.get(entity, [])
        ):
            checks.append({
                "id": f"frontend-refresh:{entity}",
                "kind": "refresh_after_mutation",
                "entity": entity,
                "targets": targets,
                "status": "pending",
                "allowed_statuses": ["verified", "blocked"],
            })
    visible_checks = checks[:limit]
    candidates_hidden = max(0, len(ordered) - len(visible))
    checks_hidden = max(0, len(checks) - len(visible_checks))
    return {
        "total": len(ordered),
        "candidates": visible,
        "candidates_hidden": candidates_hidden,
        "supporting_files_hidden": supporting_files_hidden,
        "required_checks": visible_checks,
        "checks_hidden": checks_hidden,
        "truncated": bool(candidates_hidden or supporting_files_hidden or checks_hidden),
    }
