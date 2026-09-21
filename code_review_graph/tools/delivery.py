"""Compact, deterministic delivery evidence for agent workflows."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .. import __version__
from ..changes import analyze_changes
from ..frontend_surfaces import discover_frontend_surface_candidates
from ..incremental import _SAFE_GIT_REF, get_all_changed_files
from ..parser import normalize_file_path
from ._common import (
    _bounded,
    _get_store,
    _resolve_graph_file_paths,
    _validate_positive_int,
    graph_provenance,
)

_MAX_DELIVERY_RESULTS = 50
_GIT_TIMEOUT_SECONDS = 2.0


def build_journeys(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Import the journey builder lazily to avoid the tools package cycle."""
    from ..journeys import build_journeys as build

    return build(*args, **kwargs)


def _git_commit(root: Path, ref: str) -> str | None:
    if not ref or ref.startswith("-") or not _SAFE_GIT_REF.fullmatch(ref):
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _relative(root: Path, value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def _proof_fingerprint(
    root: Path,
    base: str,
    changed_files: list[str],
    provenance: dict[str, Any],
) -> tuple[str, str | None]:
    base_sha = _git_commit(root, base)
    file_states: list[dict[str, str]] = []
    for relative in sorted(changed_files):
        path = root / relative
        content_digest = hashlib.sha256()
        if path.is_symlink():
            content_digest.update(b"symlink\0")
            content_digest.update(str(path.readlink()).encode("utf-8", errors="surrogateescape"))
        elif path.is_file():
            content_digest.update(b"file\0")
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        content_digest.update(chunk)
            except OSError:
                content_digest = hashlib.sha256(b"unreadable")
        else:
            content_digest.update(b"missing")
        file_states.append(
            {
                "path": Path(relative).as_posix(),
                "sha256": content_digest.hexdigest(),
            }
        )
    material = {
        "schema_version": 1,
        "tool_version": __version__,
        "base_sha": base_sha,
        "head_sha": provenance.get("head_sha"),
        "graph_sha": provenance.get("built_at_sha"),
        "worktree_fingerprint": provenance.get("worktree_fingerprint"),
        "files": file_states,
    }
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), base_sha


def _format_test_item(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item.get("name", ""),
        "classification": item.get("classification", "none"),
        "file": _relative(root, str(item.get("file", ""))),
    }


def _format_journey_detail(item: dict[str, Any], limit: int) -> dict[str, Any]:
    """Keep review-relevant journey gaps without copying large path payloads."""
    ambiguities = item.get("ambiguities", [])
    incomplete = item.get("incomplete_paths", [])

    def reasons(values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        unique = dict.fromkeys(
            str(value.get("reason", "unknown")) if isinstance(value, dict) else str(value)
            for value in values
        )
        return list(unique)[:limit]

    hidden = item.get("hidden", {})
    return {
        "id": item.get("id", ""),
        "name": item.get("name", ""),
        "domain": item.get("domain", ""),
        "analysis_status": item.get("analysis_status", "unknown"),
        "ambiguity_reasons": reasons(ambiguities),
        "incomplete_path_reasons": reasons(incomplete),
        "hidden": hidden if isinstance(hidden, dict) else {},
    }


def get_delivery_context(
    *,
    base: str = "HEAD~1",
    changed_files: list[str] | None = None,
    repo_root: str | None = None,
    max_depth: int = 2,
    max_results: int = 20,
    detail_level: str = "minimal",
) -> dict[str, Any]:
    """Return one bounded proof snapshot for delivery and review agents."""
    _validate_positive_int(max_results, "max_results")
    if detail_level not in {"minimal", "standard"}:
        raise ValueError("detail_level must be 'minimal' or 'standard'")

    store, root = _get_store(repo_root)
    try:
        changed_files = sorted(
            changed_files if changed_files is not None else get_all_changed_files(root, base)
        )
        provenance = graph_provenance(str(root)) or {}
        fingerprint, base_sha = _proof_fingerprint(
            root,
            base,
            changed_files,
            provenance,
        )
        files, files_total, files_cut = _bounded(
            changed_files,
            max_results,
            _MAX_DELIVERY_RESULTS,
        )

        if changed_files:
            abs_files = [normalize_file_path(root / path) for path in changed_files]
            analysis = analyze_changes(
                store,
                changed_files=abs_files,
                repo_root=str(root),
                base=base,
            )
            graph_files = _resolve_graph_file_paths(store, root, changed_files)
            impact = store.get_impact_radius(
                graph_files,
                max_depth=max_depth,
                max_nodes=min(max_results, _MAX_DELIVERY_RESULTS),
            )
            journeys = build_journeys(
                store,
                root,
                changed_files=changed_files,
                limit=min(max_results, _MAX_DELIVERY_RESULTS),
                details=False,
                max_depth=max(4, max_depth),
                max_consumers=min(max_results, 10),
                max_tests=min(max_results, 20),
            )
        else:
            analysis = {
                "risk_score": 0.0,
                "changed_functions": [],
                "test_coverage": [],
                "test_gaps": [],
                "review_priorities": [],
            }
            impact = {
                "changed_nodes": [],
                "impacted_nodes": [],
                "impacted_files": [],
                "edges": [],
                "total_impacted": 0,
                "truncated": False,
            }
            journeys = {
                "total": 0,
                "shown": 0,
                "truncated": False,
                "journeys": [],
                "changed_file_coverage": {
                    "total": 0,
                    "matched": 0,
                    "unmatched": 0,
                    "unmatched_files": [],
                    "unmatched_files_hidden": 0,
                },
            }

        journey_items = [
            {
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "domain": item.get("domain", ""),
                "analysis_status": item.get("analysis_status", "unknown"),
            }
            for item in journeys.get("journeys", [])
        ]
        coverage = journeys.get("changed_file_coverage", {})
        unattached = list(coverage.get("unmatched_files", []))
        unattached_total = int(coverage.get("unmatched", len(unattached)))
        unattached, _visible_unattached_total, unattached_cut = _bounded(
            unattached,
            max_results,
            _MAX_DELIVERY_RESULTS,
        )
        unattached_cut = (
            unattached_cut
            or int(coverage.get("unmatched_files_hidden", 0)) > 0
            or unattached_total > len(unattached)
        )

        test_coverage = analysis.get("test_coverage", [])
        test_items, tests_total, tests_cut = _bounded(
            test_coverage,
            max_results,
            _MAX_DELIVERY_RESULTS,
        )
        changed_nodes = impact.get("changed_nodes", [])
        impacted_nodes = impact.get("impacted_nodes", [])
        frontend_surfaces = discover_frontend_surface_candidates(
            root,
            store.get_all_edges(),
            changed_files,
            limit=min(max_results, _MAX_DELIVERY_RESULTS),
        )
        key_entities = [node.name for node in [*changed_nodes, *impacted_nodes]]
        key_entities = list(dict.fromkeys(key_entities))[:5]
        freshness_state = provenance.get("freshness", "unknown")
        result: dict[str, Any] = {
            "status": "ok" if freshness_state == "current" else "stale",
            "schema_version": 1,
            "summary": (
                f"Delivery context: {freshness_state}; {files_total} changed file(s); "
                f"{journeys.get('total', 0)} journey(s); "
                f"{unattached_total} unattached file(s)."
            ),
            "freshness": {
                "state": freshness_state,
                "head_matches_build": provenance.get("head_matches_build"),
                "worktree_matches_build": provenance.get("worktree_matches_build"),
                "worktree_dirty": provenance.get("worktree_dirty"),
            },
            "changes": {
                "total": files_total,
                "files": files,
                "files_hidden": max(0, files_total - len(files)),
            },
            "impact": {
                "risk_score": analysis.get("risk_score", 0.0),
                "changed_nodes": len(changed_nodes),
                "impacted_nodes": int(impact.get("total_impacted", len(impacted_nodes))),
                "impacted_files": len(impact.get("impacted_files", [])),
                "key_entities": key_entities,
            },
            "journeys": {
                "total": int(journeys.get("total", 0)),
                "items": journey_items,
                "items_hidden": max(
                    0,
                    int(journeys.get("total", 0)) - len(journey_items),
                ),
            },
            "tests": {
                "direct": sum(item.get("classification") == "direct" for item in test_coverage),
                "indirect_only": sum(
                    item.get("classification") == "indirect_only" for item in test_coverage
                ),
                "none": sum(item.get("classification") == "none" for item in test_coverage),
                "items": [_format_test_item(root, item) for item in test_items],
                "items_hidden": max(0, tests_total - len(test_items)),
            },
            "unattached_files": {
                "total": unattached_total,
                "files": unattached,
                "files_hidden": max(0, unattached_total - len(unattached)),
            },
            "frontend_surfaces": frontend_surfaces,
            "proof": {
                "base": base,
                "base_sha": base_sha,
                "head_sha": provenance.get("head_sha"),
                "graph_sha": provenance.get("built_at_sha"),
                "worktree_fingerprint": provenance.get("worktree_fingerprint"),
            },
            "fingerprint": fingerprint,
            "truncated": bool(
                files_cut
                or tests_cut
                or unattached_cut
                or frontend_surfaces.get("candidates_hidden", 0)
                or frontend_surfaces.get("supporting_files_hidden", 0)
                or frontend_surfaces.get("checks_hidden", 0)
                or journeys.get("truncated")
                or impact.get("truncated")
            ),
        }
        if detail_level == "standard":
            result["details"] = {
                "review_priorities": analysis.get("review_priorities", [])[
                    : min(max_results, _MAX_DELIVERY_RESULTS)
                ],
                "test_gaps": analysis.get("test_gaps", [])[
                    : min(max_results, _MAX_DELIVERY_RESULTS)
                ],
                "changed_functions": analysis.get("changed_functions", [])[
                    : min(max_results, _MAX_DELIVERY_RESULTS)
                ],
                "journeys": [
                    _format_journey_detail(item, min(max_results, 10))
                    for item in journeys.get("journeys", [])
                    if isinstance(item, dict)
                ],
                "limitations": journeys.get("coverage", {}).get("limitations", [])[
                    : min(max_results, _MAX_DELIVERY_RESULTS)
                ],
            }
        return result
    finally:
        store.close()


def format_delivery_context_text(result: dict[str, Any]) -> str:
    """Render a delivery snapshot in a stable, compact text form."""
    freshness = result.get("freshness", {})
    changes = result.get("changes", {})
    impact = result.get("impact", {})
    journeys = result.get("journeys", {})
    tests = result.get("tests", {})
    unattached = result.get("unattached_files", {})
    frontend_surfaces = result.get("frontend_surfaces", {})
    lines = [
        result.get("summary", "Delivery context unavailable."),
        f"Freshness: {freshness.get('state', 'unknown')}",
        f"Changes: {changes.get('total', 0)}",
        f"Impact: risk {impact.get('risk_score', 0.0):.2f}; "
        f"{impact.get('impacted_nodes', 0)} nodes; "
        f"{impact.get('impacted_files', 0)} files",
        f"Journeys: {journeys.get('total', 0)}",
        f"Tests: {tests.get('direct', 0)} direct; "
        f"{tests.get('indirect_only', 0)} indirect-only; "
        f"{tests.get('none', 0)} untested",
        f"Unattached files: {unattached.get('total', 0)}",
        f"Frontend surface candidates: {frontend_surfaces.get('total', 0)}",
    ]
    for candidate in frontend_surfaces.get("candidates", []):
        lines.append(
            f"  - {candidate.get('route', '?')} "
            f"({candidate.get('kind', 'unknown')}) — {candidate.get('file', '?')}",
        )
    for path in unattached.get("files", []):
        lines.append(f"  - {path}")
    if result.get("truncated"):
        lines.append("Output truncated; raise --max-results for more detail.")
    lines.append(f"Fingerprint: {result.get('fingerprint', '?')}")
    return "\n".join(lines)
