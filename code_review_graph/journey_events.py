"""Derived domain-event links for full-stack journey impact analysis."""

from __future__ import annotations

import re
from collections import defaultdict

from .graph import GraphEdge, GraphNode
from .journey_source import read_node_source

_DOMAIN_EVENT_CONSTRUCTION = re.compile(
    r"\bnew\s+([A-Za-z_$][\w$]*(?:DomainEvent|Event))\s*\(",
)
_ON_EVENT = re.compile(r"\bOnEvent\(\s*['\"]([^'\"]+)['\"]")

Adjacency = dict[str, list[tuple[str, GraphEdge]]]


def add_event_dispatch_edges(
    nodes: list[GraphNode], *, incoming: Adjacency, outgoing: Adjacency,
    source_cache: dict[str, list[str]],
) -> dict[str, str]:
    """Add publisher → event → handler links and return handler event names."""
    events = {
        node.name: node for node in nodes
        if node.kind == "Class" and node.name.endswith(("DomainEvent", "Event"))
    }
    handlers: dict[str, list[GraphNode]] = defaultdict(list)
    for node in nodes:
        if node.kind != "Function" or node.is_test:
            continue
        for decorator in node.extra.get("decorators", []):
            match = _ON_EVENT.search(str(decorator))
            if match:
                handlers[match.group(1)].append(node)

    seen: set[tuple[str, str, str]] = set()
    handler_events: dict[str, str] = {}
    for publisher in nodes:
        if publisher.kind != "Function" or publisher.is_test:
            continue
        source = read_node_source(publisher, source_cache)
        for match in _DOMAIN_EVENT_CONSTRUCTION.finditer(source):
            event_name = match.group(1)
            event = events.get(event_name)
            if event is None:
                continue
            publish_edge = GraphEdge(
                id=-1, kind="PUBLISHES",
                source_qualified=publisher.qualified_name,
                target_qualified=event.qualified_name,
                file_path=publisher.file_path,
                line=publisher.line_start + source[:match.start()].count("\n"),
                extra={"event": event_name}, confidence=0.8,
                confidence_tier="INFERRED",
            )
            _append_edge(publish_edge, incoming, outgoing, seen)
            for handler in handlers.get(event_name, []):
                handle_edge = GraphEdge(
                    id=-1, kind="HANDLED_BY",
                    source_qualified=event.qualified_name,
                    target_qualified=handler.qualified_name,
                    file_path=handler.file_path, line=handler.line_start,
                    extra={"event": event_name}, confidence=0.8,
                    confidence_tier="INFERRED",
                )
                _append_edge(handle_edge, incoming, outgoing, seen)
                handler_events[handler.qualified_name] = event_name
    return handler_events


def _append_edge(
    edge: GraphEdge, incoming: Adjacency, outgoing: Adjacency,
    seen: set[tuple[str, str, str]],
) -> None:
    key = (edge.kind, edge.source_qualified, edge.target_qualified)
    if key in seen:
        return
    seen.add(key)
    outgoing[edge.source_qualified].append((edge.target_qualified, edge))
    incoming[edge.target_qualified].append((edge.source_qualified, edge))
