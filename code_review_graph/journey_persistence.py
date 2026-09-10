"""TypeORM persistence analyzer for detailed journeys."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from .graph import GraphEdge, GraphNode
from .journey_source import read_node_source, relative_path

_TYPEORM_ENTITY = re.compile(r"^Entity\(\s*['\"]([^'\"]+)['\"]")
_INJECTED_REPOSITORY = re.compile(
    r"@InjectRepository\(\s*([A-Za-z_$][\w$]*)\s*\)\s*"
    r"(?:(?:private|protected|public)\s+)?(?:readonly\s+)?([A-Za-z_$][\w$]*)",
)
_REPOSITORY_CALL = re.compile(
    r"this\.([A-Za-z_$][\w$]*)\s*\.\s*([A-Za-z_$][\w$]*)",
)
_GET_REPOSITORY = re.compile(r"getRepository\(\s*([A-Za-z_$][\w$]*)\s*\)")
_REPOSITORY_GETTER = re.compile(
    r"\bget\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::[^\{]+)?\{"
    r"[\s\S]{0,300}?\bthis\.([A-Za-z_$][\w$]*)",
)
_SQL_WRITE = re.compile(r"\b(?:DELETE|INSERT|UPDATE)\b", re.IGNORECASE)
_WRITE_METHODS = frozenset({
    "decrement", "delete", "increment", "insert", "recover", "remove",
    "restore", "save", "softDelete", "softRemove", "update", "upsert",
})
_QUERY_BUILDER_WRITE = re.compile(r"\.\s*(?:delete|insert|update)\s*\(")


def typeorm_entities(nodes: list[GraphNode]) -> dict[str, tuple[GraphNode, str]]:
    entities = {}
    for node in nodes:
        if node.kind != "Class":
            continue
        for decorator in node.extra.get("decorators", []):
            match = _TYPEORM_ENTITY.match(str(decorator))
            if match:
                entities[node.name] = (node, match.group(1))
                break
    return entities


def typeorm_persistence(
    method_qn: str, *, outgoing: dict[str, list[tuple[str, GraphEdge]]],
    nodes_by_qn: dict[str, GraphNode],
    entities: dict[str, tuple[GraphNode, str]], root: Path,
    source_cache: dict[str, list[str]],
) -> list[dict[str, Any]]:
    method = nodes_by_qn.get(method_qn)
    if method is None or not method.parent_name:
        return []
    class_qn = method_qn.rpartition(".")[0]
    constructor = nodes_by_qn.get(f"{class_qn}.constructor")
    injected = {
        property_name: entity_name
        for entity_name, property_name in _INJECTED_REPOSITORY.findall(
            constructor.params or "" if constructor is not None else "",
        )
    }
    class_node = nodes_by_qn.get(class_qn)
    if class_node is not None:
        class_source = read_node_source(class_node, source_cache)
        for alias, source_property in _REPOSITORY_GETTER.findall(class_source):
            if source_property in injected:
                injected[alias] = injected[source_property]

    reachable = _reachable(method_qn, outgoing)
    methods = [
        node for qn in reachable if qn in nodes_by_qn
        for node in [nodes_by_qn[qn]]
        if node.kind == "Function" and node.parent_name == method.parent_name
    ]
    accesses: dict[str, set[str]] = defaultdict(set)
    evidence: dict[str, GraphNode] = {}
    for reachable_method in methods:
        source = read_node_source(reachable_method, source_cache)
        for property_name, operation in _REPOSITORY_CALL.findall(source):
            entity_name = injected.get(property_name)
            if entity_name not in entities:
                continue
            accesses[entity_name].add(
                "write" if operation in _WRITE_METHODS
                or operation == "query" and _SQL_WRITE.search(source)
                or operation == "createQueryBuilder"
                and _QUERY_BUILDER_WRITE.search(source) else "read",
            )
            evidence.setdefault(entity_name, reachable_method)
        for entity_name in _GET_REPOSITORY.findall(source):
            if entity_name in entities:
                accesses[entity_name].add("read")
                evidence.setdefault(entity_name, reachable_method)
        for entity_name in entities:
            operators = re.findall(
                rf"\.\s*(from|innerJoin|innerJoinAndSelect|leftJoin|"
                rf"leftJoinAndSelect|update)\s*\(\s*{re.escape(entity_name)}\b",
                source,
                re.IGNORECASE,
            )
            for operator in operators:
                reference_access = (
                    "write" if operator.casefold() == "update"
                    or operator.casefold() == "from"
                    and _QUERY_BUILDER_WRITE.search(source) else "read"
                )
                accesses[entity_name].add(reference_access)
                evidence.setdefault(entity_name, reachable_method)

    result = []
    for entity_name in sorted(accesses):
        entity, table = entities[entity_name]
        access = accesses[entity_name]
        mode = "read_write" if len(access) > 1 else next(iter(access))
        source_node = evidence[entity_name]
        result.append({
            "entity": entity_name, "table": table, "access": mode,
            "relation": {
                "read": "reads_from", "write": "writes_to",
                "read_write": "reads_writes",
            }[mode],
            "evidence": {
                "file": relative_path(source_node.file_path, root),
                "symbol": source_node.qualified_name, "line": source_node.line_start,
            },
            "entity_evidence": {
                "file": relative_path(entity.file_path, root),
                "symbol": entity.qualified_name, "line": entity.line_start,
            },
        })
    return result


def _reachable(
    start: str, outgoing: dict[str, list[tuple[str, GraphEdge]]], max_depth: int = 12,
) -> set[str]:
    found = {start}
    queue = deque([(start, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for target, _edge in outgoing.get(current, []):
            if target not in found:
                found.add(target)
                queue.append((target, depth + 1))
    return found
