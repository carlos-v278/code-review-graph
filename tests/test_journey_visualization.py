import json
import re
from unittest.mock import patch


def test_generate_journeys_html_embeds_complete_details(tmp_path):
    from code_review_graph.journey_visualization import generate_journeys_html

    result = {
        "status": "ok",
        "journeys": [{
            "id": "src/use-case.ts::GetAccountUseCase",
            "name": "GetAccountUseCase",
            "domain": "account/get",
            "analysis_status": "complete",
            "consumers": [{
                "type": "frontend", "name": "AccountController",
                "confidence": "confirmed", "method": "GET", "route": "/accounts/:id",
                "frontend_requests": [{"paths": [[{
                    "kind": "Function", "name": "AccountCard.open",
                    "file": "frontend/AccountCard.vue", "line": 20,
                }]]}],
            }],
            "repositories": [{
                "name": "IAccountRepository", "confidence": "confirmed",
                "methods": [{
                    "name": "findById", "resolution": "implementation",
                    "implementation_paths": [],
                    "persistence": [{
                        "table": "accounts", "entity": "AccountOrmEntity", "access": "read",
                    }],
                }],
            }],
            "tests": [], "ambiguities": [], "incomplete_paths": [],
        }],
    }
    output = tmp_path / "journeys.html"
    store = object()
    with patch(
        "code_review_graph.journey_visualization.build_journeys", return_value=result,
    ) as build:
        generate_journeys_html(store, tmp_path, output)

    content = output.read_text(encoding="utf-8")
    assert "<h1>Parcours</h1>" in content
    assert "Composant, use case, route" in content
    assert "[['essential','Essentiel'],['complete','Complet']]" in content
    assert "function graphForJourney(journey)" in content
    assert "function fullGraphForJourney(journey)" in content
    assert "includeIndirect = false" in content
    assert ".canvas-edge.conditional" in content
    assert "journey.indirect?.consumers" in content
    assert "Glisser · molette" in content
    assert "['Vue / UI', 'Client API / HTTP', 'Controllers', 'Use case'" in content
    assert "viewMode = 'essential'; renderDetail" in content
    embedded = re.search(r"const payload = (.*);\nconst journeys", content).group(1)
    assert json.loads(embedded) == result
    build.assert_called_once_with(store, tmp_path, limit=100_000, details=True)


def test_generate_journeys_html_escapes_script_closer(tmp_path):
    from code_review_graph.journey_visualization import generate_journeys_html

    result = {"status": "ok", "journeys": [{"name": "</script><script>alert(1)</script>"}]}
    output = tmp_path / "journeys.html"
    with patch("code_review_graph.journey_visualization.build_journeys", return_value=result):
        generate_journeys_html(object(), tmp_path, output)

    content = output.read_text(encoding="utf-8")
    assert "</script><script>alert(1)</script>" not in content
    assert "<\\/script>" in content
