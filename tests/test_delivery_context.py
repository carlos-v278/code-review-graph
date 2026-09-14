"""Regression coverage for the compact delivery evidence snapshot."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from code_review_graph import cli
from code_review_graph.tools.build import build_or_update_graph


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git", "-c", "user.name=Test", "-c",
            "user.email=test@example.com", "-c",
            "commit.gpgsign=false", *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )


def _repo_with_change(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    app = repo / "app.py"
    app.write_text(
        "class CreateAccountUseCase:\n"
        "    def execute(self):\n"
        "        return 1\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    build_or_update_graph(
        full_rebuild=True, repo_root=str(repo), postprocess="none",
    )
    app.write_text(
        "class CreateAccountUseCase:\n"
        "    def execute(self):\n"
        "        return 2\n",
        encoding="utf-8",
    )
    build_or_update_graph(
        full_rebuild=False, repo_root=str(repo), base=None, postprocess="none",
    )
    return repo


def test_delivery_context_is_compact_complete_and_stable(tmp_path):
    from code_review_graph.tools.delivery import get_delivery_context

    repo = _repo_with_change(tmp_path)
    first = get_delivery_context(repo_root=str(repo), base="HEAD", max_results=5)
    second = get_delivery_context(repo_root=str(repo), base="HEAD", max_results=5)

    assert first["status"] == "ok"
    assert first["freshness"]["state"] == "current"
    assert first["changes"]["total"] == 1
    assert set(first) >= {
        "freshness", "changes", "impact", "journeys", "tests",
        "unattached_files", "fingerprint",
    }
    assert len(first["fingerprint"]) == 64
    assert first["fingerprint"] == second["fingerprint"]
    assert len(json.dumps(first).encode("utf-8")) < 8_000


def test_delivery_context_cli_supports_text_and_json(tmp_path, capsys):
    repo = _repo_with_change(tmp_path)
    with patch.object(
        sys,
        "argv",
        [
            "code-review-graph", "delivery-context", "--repo", str(repo),
            "--base", "HEAD", "--format", "json",
        ],
    ):
        cli.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["fingerprint"]

    with patch.object(
        sys,
        "argv",
        [
            "code-review-graph", "delivery-context", "--repo", str(repo),
            "--base", "HEAD", "--format", "text",
        ],
    ):
        cli.main()
    output = capsys.readouterr().out
    assert "Delivery context" in output
    assert "Fingerprint:" in output
