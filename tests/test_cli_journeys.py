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
        "limit": 7, "target": None, "details": False,
        "max_depth": 4, "max_consumers": 10, "max_tests": 20,
        "source_file": None, "source_component": None, "source_route": None,
        "changed_files": None,
    }
    assert result["query"]["details_notice"].startswith(
        "batch output stays summarized",
    )


def test_journeys_affected_forwards_git_diff(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path, monkeypatch)
    result = {"status": "ok", "journeys": [], "total": 0, "shown": 0}
    argv = [
        "code-review-graph", "journeys-affected", "--base", "origin/dev",
        "--format", "json", "--repo", str(repo),
    ]
    with patch.object(sys, "argv", argv):
        with patch(
            "code_review_graph.incremental.get_all_changed_files",
            return_value=["frontend/src/OrganizationsPage.vue"],
        ) as changed:
            with patch(
                "code_review_graph.journeys.build_journeys", return_value=result,
            ) as build:
                cli.main()
    assert json.loads(capsys.readouterr().out) == result
    changed.assert_called_once_with(repo.resolve(), "origin/dev")
    assert build.call_args.kwargs["changed_files"] == [
        "frontend/src/OrganizationsPage.vue",
    ]


def test_journeys_forwards_component_search(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path, monkeypatch)
    result = {"status": "ok", "journeys": [], "total": 0, "shown": 0}
    argv = [
        "code-review-graph", "journeys", "--from-component",
        "OrganizationsPage", "--format", "json", "--repo", str(repo),
    ]
    with patch.object(sys, "argv", argv):
        with patch(
            "code_review_graph.journeys.build_journeys", return_value=result,
        ) as build:
            cli.main()
    assert json.loads(capsys.readouterr().out) == result
    assert build.call_args.kwargs["source_component"] == "OrganizationsPage"


@pytest.mark.parametrize(
    "selector_args",
    [
        ["--from-component", "LinkedInAccountPage"],
        [
            "--from-file",
            "frontend/src/views/admin/LinkedInAccountPage.vue",
        ],
    ],
)
def test_journeys_text_accepts_incomplete_path_without_symbol(
    tmp_path, monkeypatch, capsys, selector_args,
):
    repo = _repo(tmp_path, monkeypatch)
    result = {
        "status": "ok", "total": 1, "shown": 1, "truncated": False,
        "provenance": {"freshness": "current"}, "query": {},
        "journeys": [{
            "name": "SyncAccountUseCase", "domain": "accounts",
            "consumers": [], "repositories": [], "tests": [],
            "ambiguities": [],
            "incomplete_paths": [{
                "kind": "event_dispatch", "reason": "listener unresolved",
            }],
        }],
    }
    argv = ["code-review-graph", "journeys", *selector_args, "--repo", str(repo)]
    with patch.object(sys, "argv", argv):
        with patch(
            "code_review_graph.journeys.build_journeys", return_value=result,
        ):
            cli.main()
    assert "incomplete: event_dispatch — listener unresolved" in capsys.readouterr().out


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
        with patch(
            "code_review_graph.journeys.build_journeys", return_value=result,
        ) as build:
            cli.main()
    assert "GetAccountUseCase [accounts]" in capsys.readouterr().out
    assert build.call_args.kwargs["target"] == "GetAccountUseCase"


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("OrganizationsPage", {"source_component": "OrganizationsPage"}),
        ("UserLayout.vue", {"source_component": "UserLayout.vue"}),
        (
            "frontend/src/views/admin/OrganizationsPage.vue",
            {"source_file": "frontend/src/views/admin/OrganizationsPage.vue"},
        ),
        ("GET /admin/organizations", {"source_route": "GET /admin/organizations"}),
    ],
)
def test_journey_falls_back_to_component_file_or_route(
    tmp_path, monkeypatch, capsys, selector, expected,
):
    repo = _repo(tmp_path, monkeypatch)
    result = {
        "status": "ok", "total": 1, "shown": 1, "truncated": False,
        "provenance": {"freshness": "current"}, "query": {},
        "journeys": [],
    }
    with patch.object(
        sys, "argv", ["code-review-graph", "journey", selector, "--format", "json",
                       "--repo", str(repo)],
    ):
        with patch(
            "code_review_graph.journeys.build_journeys",
            return_value=result,
        ) as build:
            cli.main()
    assert json.loads(capsys.readouterr().out)["query"]["lookup"]["value"] == selector
    assert build.call_count == 1
    for key, value in expected.items():
        assert build.call_args.kwargs[key] == value
    assert build.call_args.kwargs["target"] is None


def test_ambiguous_journey_exits_nonzero(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path, monkeypatch)
    result = {
        "status": "ambiguous", "target": "AccountUseCase",
        "candidates": ["a::GetAccountUseCase", "b::UpdateAccountUseCase"],
        "candidate_commands": [{
            "qualified_name": "a::GetAccountUseCase",
            "command": "code-review-graph journey a::GetAccountUseCase --details",
        }],
    }
    with patch.object(
        sys, "argv",
        ["code-review-graph", "journey", "AccountUseCase", "--repo", str(repo)],
    ):
        with patch("code_review_graph.journeys.build_journeys", return_value=result):
            with pytest.raises(SystemExit) as exc_info:
                cli.main()
    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "ambiguous" in output
    assert "code-review-graph journey a::GetAccountUseCase --details" in output
