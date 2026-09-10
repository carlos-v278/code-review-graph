"""Source access shared by optional journey analyzers."""

from __future__ import annotations

from pathlib import Path

from .graph import GraphNode


def read_node_source(node: GraphNode, cache: dict[str, list[str]]) -> str:
    lines = cache.get(node.file_path)
    if lines is None:
        try:
            lines = Path(node.file_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            return ""
        cache[node.file_path] = lines
    start = max(node.line_start - 1, 0)
    end = max(node.line_end, start)
    return "\n".join(lines[start:end])


def relative_path(file_path: str, root: Path) -> str:
    try:
        return Path(file_path).relative_to(root).as_posix()
    except (OSError, ValueError):
        try:
            return Path(file_path).resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            return file_path.replace("\\", "/")
