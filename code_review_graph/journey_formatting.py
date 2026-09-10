"""Text rendering for bounded journey reports."""

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
            conditional = " [conditional]" if via.get("conditional") else ""
            lines.append(
                f"      -> {str(via.get('relation', 'unknown')).upper()}"
                f"{conditional}{reason}"
            )
        location = f" — {step['file']}:{step['line']}" if step.get("file") else ""
        lines.append(f"      {step['kind']} {step['name']}{location}")


def _format_consumer(
    lines: list[str], consumer: dict[str, Any], *, indirect: bool = False,
) -> None:
    route = (
        f" {consumer['method']} {consumer.get('route', '')}"
        if consumer.get("method") else ""
    )
    link = consumer.get("link", {})
    prefix = "indirect consumer" if indirect else "consumer"
    depth = f"; depth {link['depth']}" if indirect and link.get("depth") is not None else ""
    reason = f"; {link['reason']}" if indirect and link.get("reason") else ""
    conditional = "; conditional" if link.get("conditional") else ""
    lines.append(
        f"  {prefix}: {consumer['type']} / {consumer['confidence']}"
        f"{route} — {consumer['name']}{depth}{conditional}{reason}"
    )
    for request in consumer.get("frontend_requests", []):
        for source in request.get("sources", []):
            lines.append(
                f"    frontend source: {source.get('name', '?')} — "
                f"{source.get('file', '?')}:{source.get('line', '?')}"
            )
        if request.get("sources_hidden"):
            lines.append(
                f"    +{request['sources_hidden']} frontend sources hidden"
            )
        for path in request.get("paths", [request.get("path", [])]):
            _format_path(lines, "frontend path", path)
        if request.get("paths_hidden"):
            lines.append(f"    +{request['paths_hidden']} frontend paths hidden")
    _format_path(lines, "consumer path", consumer.get("path", []))


def format_journeys_text(result: dict[str, Any]) -> str:
    if result.get("status") != "ok":
        candidates = result.get("candidates", [])
        suffix = "\nCandidates:\n  " + "\n  ".join(candidates) if candidates else ""
        commands = result.get("candidate_commands", [])
        if commands:
            suffix += "\nCommands:\n  " + "\n  ".join(
                item["command"] for item in commands
            )
        if result.get("candidates_hidden"):
            suffix += f"\n  +{result['candidates_hidden']} candidates hidden"
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
    if result.get("query", {}).get("details_notice"):
        lines.append(result["query"]["details_notice"])
    coverage = result.get("changed_file_coverage", {})
    if coverage.get("unmatched"):
        lines.append(
            f"Unmatched changed files: {coverage['unmatched']} "
            "(manual review required)"
        )
        for file_path in coverage.get("unmatched_files", []):
            lines.append(f"  - {file_path}")
        if coverage.get("unmatched_files_hidden"):
            lines.append(
                f"  +{coverage['unmatched_files_hidden']} unmatched files hidden"
            )

    for journey in result.get("journeys", []):
        lines.append(f"\n{journey['name']} [{journey['domain']}]")
        if not journey.get("consumers"):
            lines.append("  consumers: unknown")
        for consumer in journey.get("consumers", []):
            _format_consumer(lines, consumer)
        indirect = journey.get("indirect", {})
        for consumer in indirect.get("consumers", []):
            _format_consumer(lines, consumer, indirect=True)

        lines.append(
            f"  direct: {len(journey.get('consumers', []))} consumers; "
            f"{len(journey.get('repositories', []))} repositories; "
            f"{len(journey.get('tests', []))} tests"
        )
        if indirect:
            lines.append(
                f"  indirect: {len(indirect.get('consumers', []))} consumers; "
                f"{len(indirect.get('repositories', []))} repositories; "
                f"{len(indirect.get('tests', []))} tests; "
                f"{len(indirect.get('test_candidates', []))} test candidates"
            )

        for repository in [
            *journey.get("repositories", []),
            *indirect.get("repositories", []),
        ]:
            for method in repository.get("methods", []):
                if not isinstance(method, dict):
                    continue
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
                        f"{evidence['file']}:{evidence['line']}"
                    )

        for group in journey.get("test_files", []):
            lines.append(
                f"  test file: {group['classification']} / {group['count']} — "
                f"{group['file']} (behavior coverage not proven)"
            )
        for ambiguity in journey.get("ambiguities", []):
            lines.append(
                f"  ambiguous route: {ambiguity.get('method', '')} "
                f"{ambiguity.get('route', '')} — {ambiguity['reason']}"
            )
            for candidate in ambiguity.get("candidates", []):
                evidence = candidate.get("evidence", {})
                lines.append(
                    f"    candidate: {candidate.get('method', '')} "
                    f"{candidate.get('route', '')} — {candidate.get('name', '')} "
                    f"({evidence.get('file', '?')}:{evidence.get('line', '?')})"
                )
            if ambiguity.get("candidates_hidden"):
                lines.append(
                    f"    +{ambiguity['candidates_hidden']} route candidates hidden"
                )
        hidden = {
            key: value
            for key, value in journey.get("hidden", {}).items()
            if value
        }
        if hidden:
            lines.append(
                "  hidden: " + "; ".join(
                    f"{value} {key}" for key, value in hidden.items()
                )
            )
        for incomplete in journey.get("incomplete_paths", []):
            subject = incomplete.get("symbol") or incomplete.get("kind") or "unknown"
            lines.append(
                f"  incomplete: {subject} — {incomplete.get('reason', 'unknown reason')}"
            )
    return "\n".join(lines)
