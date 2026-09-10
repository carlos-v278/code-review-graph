"""Consumer, route, and manifest detection for journeys."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

import yaml  # type: ignore[import-untyped]

from .graph import GraphNode
from .journey_source import relative_path

CONSUMER_TYPES = frozenset({
    "bot", "cron", "event", "frontend", "http", "queue", "webhook",
})
CONFIDENCE_LEVELS = frozenset({"confirmed", "probable", "unknown"})
_PLACEHOLDER = re.compile(r"^(?::[^/]+|\{[^/]+\}|\$\{[^/]+\}|:param)$")
_TEMPLATE = re.compile(r"\$\{[^}]+\}")


def normalize_http_path(raw: str, api_prefixes: Iterable[str] = ()) -> str:
    value = raw.strip()
    if "://" in value:
        value = urlsplit(value).path
    else:
        value = value.split("#", 1)[0].split("?", 1)[0]
    value = _TEMPLATE.sub(":param", value)
    value = re.sub(r"\{[^/{}]+\}", ":param", value)
    value = re.sub(r":([A-Za-z_$][\w$]*)", ":param", value)
    value = "/" + "/".join(part for part in value.split("/") if part)
    value = value.rstrip("/") or "/"
    prefixes = [normalize_http_path(item) for item in api_prefixes if item]
    for prefix in sorted(prefixes, key=len, reverse=True):
        if prefix != "/" and (value == prefix or value.startswith(prefix + "/")):
            value = value[len(prefix):] or "/"
            break
    return value


def paths_match(left: str, right: str) -> bool:
    left_parts = left.strip("/").split("/") if left != "/" else []
    right_parts = right.strip("/").split("/") if right != "/" else []
    return len(left_parts) == len(right_parts) and all(
        a == b or _PLACEHOLDER.match(a) or _PLACEHOLDER.match(b)
        for a, b in zip(left_parts, right_parts)
    )


def entry_type(node: GraphNode) -> str | None:
    relative = node.file_path.replace("\\", "/").casefold()
    if (
        node.is_test
        or node.kind not in ("Class", "Function")
        or node.name == "constructor"
        or re.search(
            r"(?:^|/)(?:test|tests|__tests__)(?:/|$)|\.(?:spec|test)\.",
            relative,
        )
    ):
        return None
    decorator_names = " ".join(
        str(value).split("(", 1)[0]
        for value in node.extra.get("decorators", [])
    )
    local_path = Path(node.file_path).name
    haystack = " ".join((
        node.name, node.parent_name or "", local_path, decorator_names,
    )).casefold()
    if "cron" in haystack or "scheduler" in haystack:
        return "cron"
    if "webhook" in haystack:
        return "webhook"
    if any(token in haystack for token in ("processor", "queue", "consumer", "worker")):
        return "queue"
    if any(token in haystack for token in ("onevent", "eventpattern", "listener", "subscriber")):
        return "event"
    return None


def is_frontend_request(node: GraphNode, root: Path) -> bool:
    relative = relative_path(node.file_path, root).casefold()
    if re.search(r"(?:^|/)(?:test|tests|__tests__)(?:/|$)|\.(?:spec|test)\.", relative):
        return False
    parts = set(relative.split("/"))
    return bool(parts & {"client", "frontend", "ui", "web"}) or relative.endswith(
        (".jsx", ".tsx", ".vue"),
    )


def load_manifest(path: str | None) -> list[dict[str, str]]:
    if not path:
        return []
    try:
        payload = yaml.safe_load(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read consumer manifest: {exc}") from exc
    if payload is None:
        return []
    if not isinstance(payload, dict) or not isinstance(payload.get("consumers"), list):
        raise ValueError("consumer manifest must contain a 'consumers' list")
    consumers: list[dict[str, str]] = []
    for index, item in enumerate(payload["consumers"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"consumer manifest item {index} must be a mapping")
        consumer_type = item.get("type")
        if consumer_type not in CONSUMER_TYPES:
            raise ValueError(
                f"consumer manifest item {index} has unsupported type {consumer_type!r}",
            )
        if not isinstance(item.get("use_case"), str) and not (
            isinstance(item.get("route"), str) and isinstance(item.get("method"), str)
        ):
            raise ValueError(
                f"consumer manifest item {index} needs use_case or method + route",
            )
        consumers.append({
            key: str(value) for key, value in item.items()
            if value is not None
            and key in {"method", "name", "route", "type", "use_case"}
        })
    return consumers
