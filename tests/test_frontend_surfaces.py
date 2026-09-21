"""Frontend surface candidate discovery for delivery reviews."""

from pathlib import Path

from code_review_graph.frontend_surfaces import discover_frontend_surface_candidates
from code_review_graph.graph import GraphEdge


def _edge(kind: str, source: Path, target: Path, line: int) -> GraphEdge:
    return GraphEdge(
        id=line,
        kind=kind,
        source_qualified=source.as_posix(),
        target_qualified=target.as_posix(),
        file_path=source.as_posix(),
        line=line,
        extra={},
    )


def _frontend_fixture(tmp_path: Path) -> tuple[Path, list[GraphEdge]]:
    root = tmp_path / "repo"
    router = root / "frontend/src/router/admin/routes.ts"
    constants = root / "frontend/src/router/admin/constants.ts"
    emails = root / "frontend/src/views/admin/EmailsPage.vue"
    detail = root / "frontend/src/views/admin/EmailDetailPage.vue"
    email_import = root / "frontend/src/views/admin/ImportEmailsPage.vue"
    status_card = root / "frontend/src/components/admin/EmailStatusCard.vue"
    composable = root / "frontend/src/composables/use-admin-emails.ts"
    service = root / "frontend/src/services/admin/admin-email.service.ts"
    columns = root / "frontend/src/components/admin/email-table-columns.ts"
    for path in (
        router,
        constants,
        emails,
        detail,
        email_import,
        status_card,
        composable,
        service,
        columns,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("export {}\n", encoding="utf-8")
    constants.write_text(
        "export const RoutePath = {\n"
        "  ADMIN_EMAILS: '/admin/emails',\n"
        "  ADMIN_EMAIL_DETAIL: '/admin/emails/:id',\n"
        "  ADMIN_IMPORT_EMAILS: '/admin/emails/import',\n"
        "} as const;\n",
        encoding="utf-8",
    )
    router.write_text(
        "export const routes = [\n"
        "  {\n"
        "    path: RouteChildPath.EMAILS,\n"
        "    name: RouteName.ADMIN_EMAILS,\n"
        "    component: () => import('@/views/admin/EmailsPage.vue'),\n"
        "  },\n"
        "  {\n"
        "    path: RouteChildPath.EMAIL_DETAIL,\n"
        "    name: RouteName.ADMIN_EMAIL_DETAIL,\n"
        "    component: () => import('@/views/admin/EmailDetailPage.vue'),\n"
        "  },\n"
        "  {\n"
        "    path: RouteChildPath.EMAIL_IMPORT,\n"
        "    name: RouteName.ADMIN_IMPORT_EMAILS,\n"
        "    component: () => import('@/views/admin/ImportEmailsPage.vue'),\n"
        "  },\n"
        "];\n",
        encoding="utf-8",
    )
    edges = [
        _edge("IMPORTS_FROM", router, emails, 5),
        _edge("IMPORTS_FROM", router, detail, 10),
        _edge("IMPORTS_FROM", router, email_import, 15),
        _edge("IMPORTS_FROM", emails, composable, 1),
        _edge("IMPORTS_FROM", emails, columns, 2),
        _edge("IMPORTS_FROM", composable, service, 1),
        _edge("IMPORTS_FROM", detail, composable, 1),
        _edge("IMPORTS_FROM", detail, status_card, 2),
    ]
    return root, edges


def test_business_state_change_requires_list_and_detail_decisions(tmp_path: Path) -> None:
    root, edges = _frontend_fixture(tmp_path)

    result = discover_frontend_surface_candidates(
        root,
        edges,
        ["backend/src/domain/models/email/email.model.ts"],
        limit=20,
    )

    assert [item["route"] for item in result["candidates"]] == [
        "/admin/emails",
        "/admin/emails/:id",
    ]
    assert all(item["decision"]["status"] == "pending" for item in result["candidates"])
    list_surface = result["candidates"][0]
    assert [item["file"] for item in list_surface["evidence"]["supporting_files"]] == [
        "frontend/src/components/admin/email-table-columns.ts",
        "frontend/src/composables/use-admin-emails.ts",
        "frontend/src/services/admin/admin-email.service.ts",
    ]
    assert list_surface["evidence"]["supporting_files_hidden"] == 0
    assert result["supporting_files_hidden"] == 0
    assert {item["kind"] for item in result["required_checks"]} == {
        "frontend_surface",
        "list_detail_consistency",
        "refresh_after_mutation",
    }
    detail_surface = result["candidates"][1]
    assert "frontend/src/components/admin/EmailStatusCard.vue" in {
        item["file"] for item in detail_surface["evidence"]["supporting_files"]
    }


def test_implementation_only_change_does_not_impose_email_surfaces(tmp_path: Path) -> None:
    root, edges = _frontend_fixture(tmp_path)

    result = discover_frontend_surface_candidates(
        root,
        edges,
        ["backend/src/application/services/email/email-normalizer.service.ts"],
        limit=20,
    )

    assert result["candidates"] == []
    assert result["required_checks"] == []


def test_changed_surface_is_not_reported_as_unchanged_candidate(tmp_path: Path) -> None:
    root, edges = _frontend_fixture(tmp_path)

    result = discover_frontend_surface_candidates(
        root,
        edges,
        [
            "backend/src/application/use-cases/admin/email/get-email/get-admin-email.dto.ts",
            "frontend/src/views/admin/EmailsPage.vue",
        ],
        limit=20,
    )

    assert [item["route"] for item in result["candidates"]] == [
        "/admin/emails/:id",
    ]
    assert {item["kind"] for item in result["required_checks"]} == {
        "frontend_surface",
    }
