import json
import sys
from unittest.mock import patch

import pytest

from code_review_graph import cli


def _repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    data = tmp_path / "data"
    data.mkdir()
    (data / "graph.db").touch()
    monkeypatch.setenv("CRG_DATA_DIR", str(data))
    return repo


def test_journeys_forwards_filters_as_json(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path, monkeypatch)
    result = {"status": "ok", "journeys": [], "total": 0, "shown": 0}
    argv = [
        "code-review-graph", "journeys", "--format", "json",
        "--consumer-type", "frontend", "--confidence", "confirmed",
        "--api-prefix", "/api", "--consumer-manifest", "consumers.yaml",
        "--limit", "7", "--details", "--repo", str(repo),
    ]
    with patch.object(sys, "argv", argv):
        with patch("code_review_graph.journeys.build_journeys", return_value=result) as build:
            cli.main()
    assert json.loads(capsys.readouterr().out) == result
    assert build.call_args.kwargs == {
        "api_prefixes": ["/api"], "consumer_manifest": "consumers.yaml",
        "consumer_types": ["frontend"], "confidences": ["confirmed"],
        "limit": 7, "target": None, "details": True,
    }


def test_journey_outputs_text(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path, monkeypatch)
    result = {
        "status": "ok", "total": 1, "shown": 1, "truncated": False,
        "provenance": {"freshness": "current"},
        "journeys": [{
            "name": "GetAccountUseCase", "domain": "accounts",
            "consumers": [], "repositories": [], "tests": [],
            "ambiguities": [],
        }],
    }
    with patch.object(
        sys, "argv",
        ["code-review-graph", "journey", "GetAccountUseCase", "--repo", str(repo)],
    ):
        with patch("code_review_graph.journeys.build_journeys", return_value=result):
            cli.main()
    assert "GetAccountUseCase [accounts]" in capsys.readouterr().out


def test_ambiguous_journey_exits_nonzero(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path, monkeypatch)
    result = {
        "status": "ambiguous", "target": "AccountUseCase",
        "candidates": ["a::GetAccountUseCase", "b::UpdateAccountUseCase"],
    }
    with patch.object(
        sys, "argv",
        ["code-review-graph", "journey", "AccountUseCase", "--repo", str(repo)],
    ):
        with patch("code_review_graph.journeys.build_journeys", return_value=result):
            with pytest.raises(SystemExit) as exc_info:
                cli.main()
    assert exc_info.value.code == 1
    assert "ambiguous" in capsys.readouterr().out
