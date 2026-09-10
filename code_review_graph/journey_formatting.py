"""Text rendering for journey reports."""

from __future__ import annotations

from typing import Any


def _format_path(lines: list[str], label: str, path: list[dict[str, Any]]) -> None:
    if not path:
        return
    lines.append(f"    {label}:")
    for index, step in enumerate(path):
        if index:
            via = step.get("via", {})
            reason = f" ({via['reason']})" if via.get("reason") else ""
            lines.append(f"      -> {str(via.get('relation', 'unknown')).upper()}{reason}")
        location = (
            f" — {step['file']}:{step['line']}" if step.get("file") else ""
        )
        lines.append(f"      {step['kind']} {step['name']}{location}")


def format_journeys_text(result: dict[str, Any]) -> str:
    if result.get("status") != "ok":
        candidates = result.get("candidates", [])
        suffix = "\nCandidates:\n  " + "\n  ".join(candidates) if candidates else ""
        return f"Journey {result.get('status')}: {result.get('target', '')}{suffix}"
    provenance = result.get("provenance", {})
    lines = [
        f"Journeys: {result['total']} total; showing {result['shown']}",
        f"Graph: {provenance.get('freshness', 'unknown')} "
        f"({provenance.get('built_on_branch', '?')}@"
        f"{str(provenance.get('built_at_sha', '?'))[:12]})",
    ]
    if result.get("truncated"):
        lines.append("Output truncated; raise --limit to show more.")
    for journey in result.get("journeys", []):
        lines.append(f"\n{journey['name']} [{journey['domain']}]")
        if not journey["consumers"]:
            lines.append("  consumers: unknown")
        for consumer in journey["consumers"]:
            route = (
                f" {consumer['method']} {consumer.get('route', '')}"
                if consumer.get("method") else ""
            )
            external = (
                f" (external: {consumer['external_status']})"
                if consumer.get("external_status") in ("declared", "unknown")
                else ""
            )
            lines.append(
                f"  consumer: {consumer['type']} / {consumer['confidence']}"
                f"{route} — {consumer['name']}{external}",
            )
            for request in consumer.get("frontend_requests", []):
                for path in request.get("paths", [request.get("path", [])]):
                    _format_path(lines, "frontend path", path)
            _format_path(lines, "consumer path", consumer.get("path", []))
        lines.append(
            f"  repositories: {len(journey['repositories'])}; "
            f"tests: {len(journey['tests'])}; "
            f"ambiguities: {len(journey['ambiguities'])}; "
            f"incomplete paths: {len(journey.get('incomplete_paths', []))}",
        )
        for repository in journey["repositories"]:
            for method in repository.get("methods", []):
                _format_path(
                    lines,
                    f"repository path ({repository['name']}.{method['name']})",
                    method.get("path", []),
                )
                for path in method.get("implementation_paths", []):
                    _format_path(lines, "implementation + mapper path", path)
                for persistence in method.get("persistence", []):
                    evidence = persistence["entity_evidence"]
                    lines.append(
                        f"    persistence: {persistence['relation'].upper()} "
                        f"{persistence['table']} ({persistence['entity']}) — "
                        f"{evidence['file']}:{evidence['line']}",
                    )
        for incomplete in journey.get("incomplete_paths", []):
            lines.append(
                f"  incomplete: {incomplete['symbol']} — {incomplete['reason']}",
            )
    return "\n".join(lines)
