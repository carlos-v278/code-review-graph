from pathlib import Path

import pytest

from code_review_graph.graph import GraphStore
from code_review_graph.journey_results import route_selection_matches
from code_review_graph.journeys import (
    build_journeys,
    format_journeys_text,
    normalize_http_path,
)
from code_review_graph.parser import EdgeInfo, NodeInfo


def _node(kind, name, path, parent=None, params=None, **extra):
    return NodeInfo(
        kind=kind, name=name, file_path=str(path), line_start=10,
        line_end=20, language="typescript", parent_name=parent,
        params=params, is_test=kind == "Test", extra=extra,
    )


def _qn(path: Path, symbol: str) -> str:
    return f"{path.as_posix()}::{symbol}"


def _fixture(
    tmp_path: Path, *, with_implementation: bool = True,
    repository_operation: str = "findOne", repository_getter: bool = False,
    repository_source: str | None = None,
):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    graph_dir = root / ".code-review-graph"
    graph_dir.mkdir()
    store = GraphStore(graph_dir / "graph.db")
    uc = root / "backend/src/application/use-cases/accounts/get.use-case.ts"
    ctrl = root / "backend/src/controllers/support.controller.ts"
    front = root / "frontend/src/useAccount.ts"
    component = root / "frontend/src/components/AccountPanel.vue"
    repo = root / "backend/src/domain/IAccountRepository.ts"
    repo_impl = root / "backend/src/infrastructure/TypeOrmAccountRepository.ts"
    mapper = root / "backend/src/infrastructure/mappers/account.mapper.ts"
    entity = root / "backend/src/infrastructure/entities/account.orm-entity.ts"
    test = root / "backend/src/get.use-case.spec.ts"
    cron = root / "backend/src/materialize.cron.ts"
    endpoint_name = "detail@Get[0] GET /support/accounts/:id"
    request_name = "request@L10:0 GET /api/support/accounts/:param"
    nodes = [
        _node("Class", "GetAccountUseCase", uc),
        _node("Function", "execute", uc, "GetAccountUseCase"),
        _node("Function", "detail", ctrl, "SupportController"),
        _node(
            "Endpoint", endpoint_name, ctrl, "SupportController",
            http_method="GET", route="/support/accounts/:id", dynamic=False,
        ),
        _node("Function", "load", front),
        _node("Function", "openAccount", component),
        _node(
            "HttpRequest", request_name, front,
            http_method="GET", route="/api/support/accounts/:param",
            dynamic=False,
        ),
        _node("Function", "findById", repo, "IAccountRepository"),
        _node("Class", "IAccountRepository", repo),
        _node("Class", "TypeOrmAccountRepository", repo_impl),
        _node(
            "Function", "constructor", repo_impl, "TypeOrmAccountRepository",
            params=(
                "(@InjectRepository(AccountOrmEntity) "
                f"private readonly {'fallbackRepository' if repository_getter else 'repository'}: "
                "Repository<AccountOrmEntity>)"
            ),
        ),
        _node("Function", "findById", repo_impl, "TypeOrmAccountRepository"),
        _node("Function", "toDomain", mapper, "AccountMapper"),
        _node("Class", "AccountOrmEntity", entity, decorators=["Entity('accounts')"]),
        _node("Test", "it:loads@L10", test),
        _node("Function", "runCycle", cron, "MaterializeSessionsCron"),
    ]
    for node in nodes:
        store.upsert_node(node)
    repo_impl.parent.mkdir(parents=True, exist_ok=True)
    source = repository_source
    if source is None:
        getter = (
            "private get repository(): Repository<AccountOrmEntity> {\n"
            "  return txRepository(this.fallbackRepository);\n}\n"
            if repository_getter else ""
        )
        source = f"{getter}this.repository.{repository_operation}();"
    repo_impl.write_text("\n" * 9 + source + "\n", encoding="utf-8")
    handler = _qn(ctrl, "SupportController.detail")
    execute = _qn(uc, "GetAccountUseCase.execute")
    edges = [
        EdgeInfo("CALLS", handler, execute, str(ctrl), 14),
        EdgeInfo(
            "HANDLES", handler,
            _qn(ctrl, f"SupportController.{endpoint_name}"), str(ctrl), 9,
        ),
        EdgeInfo("REQUESTS", _qn(front, "load"), _qn(front, request_name), str(front), 10),
        EdgeInfo(
            "CALLS", _qn(component, "openAccount"), _qn(front, "load"),
            str(component), 12,
        ),
        EdgeInfo(
            "CALLS", execute, _qn(repo, "IAccountRepository.findById"), str(uc), 30,
        ),
        EdgeInfo("CALLS", _qn(test, "it:loads@L10"), execute, str(test), 12),
        EdgeInfo(
            "CALLS", _qn(cron, "MaterializeSessionsCron.runCycle"),
            execute, str(cron), 50,
        ),
    ]
    if with_implementation:
        edges.extend([
            EdgeInfo(
                "IMPLEMENTS", _qn(repo_impl, "TypeOrmAccountRepository"),
                _qn(repo, "IAccountRepository"), str(repo_impl), 8,
            ),
            EdgeInfo(
                "CALLS", _qn(repo_impl, "TypeOrmAccountRepository.findById"),
                _qn(mapper, "AccountMapper.toDomain"), str(repo_impl), 25,
            ),
        ])
    for edge in edges:
        store.upsert_edge(edge)
    return store, root


def test_normalizes_http_paths() -> None:
    assert normalize_http_path(
        "https://host/api/accounts/${id}/?x=1", ["/api"],
    ) == "/accounts/:param"
    assert normalize_http_path("/accounts/{id}") == "/accounts/:param"


def test_combines_frontend_cron_repository_and_tests(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path)
    try:
        result = build_journeys(
            store, root, api_prefixes=["/api"], target="GetAccountUseCase",
            details=True,
        )
    finally:
        store.close()
    journey = result["journeys"][0]
    assert {item["type"] for item in journey["consumers"]} == {"cron", "frontend"}
    assert next(
        item for item in journey["consumers"] if item["type"] == "cron"
    )["name"] == "MaterializeSessionsCron"
    assert len(journey["repositories"]) == 1
    assert journey["repositories"][0]["confidence"] == "confirmed"
    assert journey["tests"][0]["coverage"] == "direct"
    frontend = next(item for item in journey["consumers"] if item["type"] == "frontend")
    frontend_path = frontend["frontend_requests"][0]["paths"][0]
    assert [step["kind"] for step in frontend_path] == [
        "Function", "Function", "HttpRequest", "Endpoint", "Function", "Function",
    ]
    assert [step["via"]["relation"] for step in frontend_path[1:]] == [
        "calls", "requests", "route_match", "handled_by", "calls",
    ]
    method = journey["repositories"][0]["methods"][0]
    repository_path = method["path"]
    assert [step["name"] for step in repository_path] == [
        "GetAccountUseCase.execute", "IAccountRepository.findById",
    ]
    assert repository_path[1]["via"]["relation"] == "calls"
    assert repository_path[-1]["kind"] == "RepositoryMethod"
    implementation_path = method["implementation_paths"][0]
    assert [step["name"] for step in implementation_path] == [
        "GetAccountUseCase.execute", "IAccountRepository.findById",
        "TypeOrmAccountRepository.findById", "AccountMapper.toDomain",
    ]
    assert [step["via"]["relation"] for step in implementation_path[1:]] == [
        "calls", "implemented_by", "calls",
    ]
    assert method["persistence"][0]["table"] == "accounts"
    assert method["persistence"][0]["relation"] == "reads_from"
    assert journey["analysis_status"] == "complete"
    assert result["coverage"]["complete"] is False


def test_reports_unresolved_repository_as_incomplete(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path, with_implementation=False)
    try:
        result = build_journeys(
            store, root, target="GetAccountUseCase", details=True,
        )
    finally:
        store.close()
    journey = result["journeys"][0]
    method = journey["repositories"][0]["methods"][0]
    assert method["resolution"] == "unresolved"
    assert journey["analysis_status"] == "incomplete"
    assert journey["incomplete_paths"][0]["kind"] == "repository_implementation"


def test_reports_typeorm_write_access(tmp_path: Path) -> None:
    store, root = _fixture(
        tmp_path, repository_source="return this.repository\n  .save(value);",
    )
    try:
        result = build_journeys(
            store, root, target="GetAccountUseCase", details=True,
        )
    finally:
        store.close()
    method = result["journeys"][0]["repositories"][0]["methods"][0]
    assert method["persistence"][0]["relation"] == "writes_to"


def test_ambiguous_use_case_lists_qualified_commands(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path)
    duplicate = root / "backend/src/application/use-cases/other/get.use-case.ts"
    store.upsert_node(_node("Class", "GetAccountUseCase", duplicate))
    try:
        result = build_journeys(store, root, target="GetAccountUseCase")
    finally:
        store.close()
    assert result["status"] == "ambiguous"
    assert result["candidate_count"] == 2
    assert all(
        item["command"].startswith("code-review-graph journey ")
        and item["command"].endswith(" --details")
        for item in result["candidate_commands"]
    )


def test_resolves_multiline_typeorm_calls_and_entity_references(tmp_path: Path) -> None:
    store, root = _fixture(
        tmp_path,
        repository_source=(
            "return this.repository\n"
            "  .createQueryBuilder('account')\n"
            "  .leftJoin(AccountOrmEntity, 'joined', 'joined.id = account.id')\n"
            "  .getMany();"
        ),
    )
    try:
        result = build_journeys(
            store, root, target="GetAccountUseCase", details=True,
        )
    finally:
        store.close()
    method = result["journeys"][0]["repositories"][0]["methods"][0]
    assert method["resolution"] == "implementation"
    assert method["persistence"][0]["table"] == "accounts"


def test_does_not_treat_an_entity_name_as_database_access(tmp_path: Path) -> None:
    store, root = _fixture(
        tmp_path,
        repository_source="const entityType = AccountOrmEntity; return [];",
    )
    try:
        result = build_journeys(
            store, root, target="GetAccountUseCase", details=True,
        )
    finally:
        store.close()
    method = result["journeys"][0]["repositories"][0]["methods"][0]
    assert method["persistence"] == []
    assert method["resolution"] == "implementation_partial"


def test_includes_inline_mapping_method_in_implementation_path(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path)
    repo_impl = root / "backend/src/infrastructure/TypeOrmAccountRepository.ts"
    store.upsert_node(_node(
        "Function", "toListItem", repo_impl, "TypeOrmAccountRepository",
    ))
    store.upsert_edge(EdgeInfo(
        "CALLS", _qn(repo_impl, "TypeOrmAccountRepository.findById"),
        _qn(repo_impl, "TypeOrmAccountRepository.toListItem"), str(repo_impl), 25,
    ))
    try:
        result = build_journeys(
            store, root, target="GetAccountUseCase", details=True,
        )
    finally:
        store.close()
    method = result["journeys"][0]["repositories"][0]["methods"][0]
    assert any(
        path[-1]["name"] == "TypeOrmAccountRepository.toListItem"
        for path in method["implementation_paths"]
    )


def test_resolves_typeorm_repository_getter_alias(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path, repository_getter=True)
    try:
        result = build_journeys(
            store, root, target="GetAccountUseCase", details=True,
        )
    finally:
        store.close()
    method = result["journeys"][0]["repositories"][0]["methods"][0]
    assert method["persistence"][0]["table"] == "accounts"


def test_marks_unresolved_typeorm_persistence_incomplete(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path, repository_source="return undefined;")
    try:
        result = build_journeys(
            store, root, target="GetAccountUseCase", details=True,
        )
    finally:
        store.close()
    journey = result["journeys"][0]
    method = journey["repositories"][0]["methods"][0]
    assert method["resolution"] == "implementation_partial"
    assert journey["analysis_status"] == "incomplete"
    assert journey["incomplete_paths"][0]["kind"] == "repository_persistence"


def test_reports_domain_event_handlers_as_probable_effects(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path)
    use_case = root / "backend/src/application/use-cases/accounts/get.use-case.ts"
    event_file = root / "backend/src/domain/account-changed.domain-event.ts"
    handler_file = root / "backend/src/application/handlers/on-account-changed.handler.ts"
    use_case.parent.mkdir(parents=True, exist_ok=True)
    use_case.write_text(
        "\n" * 9 + "this.addDomainEvent(new AccountChangedDomainEvent());\n",
        encoding="utf-8",
    )
    event = _node("Class", "AccountChangedDomainEvent", event_file)
    handler = _node(
        "Function", "handle", handler_file, "OnAccountChangedHandler",
        decorators=["OnEvent('AccountChangedDomainEvent')"],
    )
    store.upsert_node(event)
    store.upsert_node(handler)
    try:
        result = build_journeys(
            store, root, target="GetAccountUseCase", details=True,
        )
        compact = build_journeys(store, root, target="GetAccountUseCase")
    finally:
        store.close()
    journey = result["journeys"][0]
    assert journey["effects"][0]["name"] == "OnAccountChangedHandler"
    assert journey["effects"][0]["link"]["conditional"] is True
    assert journey["effects"][0]["confidence"] == "probable"
    assert journey["effects"][0]["path"][1]["via"]["conditional"] is True
    assert not any(
        item["name"] == "OnAccountChangedHandler"
        for item in journey["consumers"]
    )
    assert [step["via"]["relation"] for step in journey["effects"][0]["path"][1:]] == [
        "publishes", "handled_by",
    ]
    assert journey["analysis_status"] == "incomplete"
    assert journey["incomplete_paths"][0]["kind"] == "event_dispatch"
    assert compact["journeys"][0]["effects"] == []
    assert compact["journeys"][0]["hidden"]["effects"] == 1


def test_manifest_declares_bot_but_name_alone_does_not(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path)
    manifest = root / "consumers.yaml"
    manifest.write_text(
        "consumers:\n  - use_case: GetAccountUseCase\n    type: bot\n    name: Bobby\n",
        encoding="utf-8",
    )
    try:
        plain = build_journeys(store, root, target="GetAccountUseCase")
        declared = build_journeys(
            store, root, target="GetAccountUseCase",
            consumer_manifest=str(manifest),
        )
    finally:
        store.close()
    assert "bot" not in {item["type"] for item in plain["journeys"][0]["consumers"]}
    bot = next(
        item for item in declared["journeys"][0]["consumers"]
        if item["type"] == "bot"
    )
    assert bot["external_status"] == "declared"


def test_invalid_manifest_is_explicit(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path)
    manifest = root / "bad.yaml"
    manifest.write_text("consumers:\n  - type: satellite\n", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="unsupported type"):
            build_journeys(store, root, consumer_manifest=str(manifest))
    finally:
        store.close()


def test_groups_tests_and_does_not_claim_behavior_coverage(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path)
    indirect_file = root / "backend/src/get.integration.spec.ts"
    candidate_file = root / "backend/src/get.candidate.spec.ts"
    indirect = _node("Test", "it:integrates@L10", indirect_file)
    store.upsert_node(indirect)
    direct_qn = _qn(root / "backend/src/get.use-case.spec.ts", "it:loads@L10")
    store.upsert_edge(EdgeInfo(
        "CALLS", _qn(indirect_file, "it:integrates@L10"), direct_qn,
        str(indirect_file), 12,
    ))
    candidate_file.parent.mkdir(parents=True, exist_ok=True)
    candidate_file.write_text(
        "describe('candidate', () => GetAccountUseCase);\n", encoding="utf-8",
    )
    store.upsert_node(_node("Test", "it:candidate@L10", candidate_file))
    try:
        result = build_journeys(
            store, root, target="GetAccountUseCase", details=True,
        )
    finally:
        store.close()
    groups = result["journeys"][0]["test_files"]
    assert {group["classification"] for group in groups} == {
        "direct", "indirect", "candidate",
    }
    assert all("not proven" in group["coverage_claim"] for group in groups)


def test_filters_journeys_from_component_file_and_route(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path)
    component = "frontend/src/components/AccountPanel.vue"
    try:
        by_component = build_journeys(
            store, root, api_prefixes=["/api"], source_component="AccountPanel",
        )
        by_file = build_journeys(
            store, root, api_prefixes=["/api"], source_file=component,
        )
        by_diff = build_journeys(
            store, root, api_prefixes=["/api"], changed_files=[component],
        )
        by_route = build_journeys(
            store, root, api_prefixes=["/api"],
            source_route="/support/accounts",
        )
    finally:
        store.close()
    assert [item["name"] for item in by_component["journeys"]] == [
        "GetAccountUseCase",
    ]
    assert by_file["total"] == by_diff["total"] == by_route["total"] == 1
    assert by_diff["journeys"][0]["selection"][0]["reason"] in {
        "upstream graph dependency", "frontend route path",
    }


def test_qualified_route_requires_exact_method_and_path() -> None:
    get_consumer = {"method": "GET", "route": "/api/admin/organizations"}
    post_consumer = {"method": "POST", "route": "/api/admin/organizations"}
    assert route_selection_matches(
        [get_consumer], "GET /admin/organizations", ["/api"],
    )
    parametrized_get = {
        "method": "GET", "route": "/api/admin/organizations/:id",
    }
    assert route_selection_matches(
        [parametrized_get], "GET /admin/organizations/123", ["/api"],
    )
    assert not route_selection_matches(
        [post_consumer], "GET /admin/organizations", ["/api"],
    )
    assert not route_selection_matches(
        [parametrized_get], "POST /admin/organizations/123", ["/api"],
    )
    assert route_selection_matches(
        [post_consumer], "/admin/organizations", ["/api"],
    )


def test_frontend_paths_respect_depth_and_consumer_limits(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path)
    request_source = _qn(root / "frontend/src/useAccount.ts", "load")
    for index in range(3):
        view = root / f"frontend/src/views/Account{index}.vue"
        store.upsert_node(_node("Function", f"open{index}", view))
        store.upsert_edge(EdgeInfo(
            "CALLS", _qn(view, f"open{index}"), request_source, str(view), 12,
        ))
    try:
        result = build_journeys(
            store, root, api_prefixes=["/api"], target="GetAccountUseCase",
            details=True, max_depth=2, max_consumers=1,
        )
    finally:
        store.close()
    frontend = next(
        item for item in result["journeys"][0]["consumers"]
        if item["type"] == "frontend"
    )
    request = frontend["frontend_requests"][0]
    assert len(request["paths"]) == 1
    assert request["paths_hidden"] == 3
    assert request["sources_hidden"] == 4


def test_ambiguous_route_lists_candidates_with_evidence(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path)
    other = root / "backend/src/controllers/other.controller.ts"
    endpoint_name = "detail@Get[0] GET /support/accounts/:accountId"
    store.upsert_node(_node(
        "Endpoint", endpoint_name, other, "OtherController",
        http_method="GET", route="/support/accounts/:accountId", dynamic=False,
    ))
    try:
        result = build_journeys(
            store, root, api_prefixes=["/api"],
            target="GetAccountUseCase", details=True,
        )
        compact = build_journeys(
            store, root, api_prefixes=["/api"], target="GetAccountUseCase",
        )
    finally:
        store.close()
    ambiguity = result["journeys"][0]["ambiguities"][0]
    assert ambiguity["candidate_count"] == 2
    assert {item["name"] for item in ambiguity["candidates"]} == {
        "SupportController", "OtherController",
    }
    assert all(item["evidence"]["file"] for item in ambiguity["candidates"])
    assert compact["journeys"][0]["ambiguities"][0]["candidates"][0][
        "evidence"
    ]["file"]
    rendered = format_journeys_text(result)
    assert "ambiguous route" in rendered
    assert "candidate: GET /support/accounts" in rendered


def test_compact_output_is_bounded_and_reports_hidden_items(tmp_path: Path) -> None:
    store, root = _fixture(tmp_path)
    try:
        result = build_journeys(
            store, root, api_prefixes=["/api"], target="GetAccountUseCase",
            max_consumers=1, max_tests=1,
        )
    finally:
        store.close()
    journey = result["journeys"][0]
    assert len(journey["consumers"]) == 1
    assert journey["hidden"]["consumers"] == 1
    assert "path" not in journey["consumers"][0]
    assert len(journey["tests"]) == 1
