from pathlib import Path

from code_review_graph.parser import CodeParser

SOURCE = b"""
@ApiTags('Support')
@Controller('support/accounts')
// controller documentation
export class SupportController {
  @Get(':id')
  async detail() { return this.details.execute(); }

  @Patch(`:id/${action}`)
  async mutate() { return this.update.execute(); }
}

const BASE_URL = '/api/support/accounts';
export async function loadAccount(id: string) {
  await fetch(`${BASE_URL}/${id}?preview=1`);
  await api.get<Account>(`${BASE_URL}/${id}`);
  await api.get(`/api/${buildPath()}`);
  return apiClient.patch('/api/support/accounts/42', { active: true });
}
"""


def test_nestjs_routes_and_frontend_requests_are_addressable(tmp_path: Path) -> None:
    path = tmp_path / "support.ts"
    nodes, edges = CodeParser().parse_bytes(path, SOURCE)
    endpoints = [node for node in nodes if node.kind == "Endpoint"]
    requests = [node for node in nodes if node.kind == "HttpRequest"]
    assert {
        (node.extra["http_method"], node.extra["route"], node.extra["dynamic"])
        for node in endpoints
    } == {
        ("GET", "/support/accounts/:id", False),
        ("PATCH", "/support/accounts/:id/:param", False),
    }
    assert {
        (node.extra["http_method"], node.extra["route"], node.extra["dynamic"])
        for node in requests
    } == {
        ("GET", "/api/support/accounts/:param?preview=1", False),
        ("GET", "/api/support/accounts/:param", False),
        ("GET", "/api/${buildPath()}", True),
        ("PATCH", "/api/support/accounts/42", False),
    }
    assert len([edge for edge in edges if edge.kind == "HANDLES"]) == 2
    assert len([edge for edge in edges if edge.kind == "REQUESTS"]) == 4


def test_non_http_get_calls_are_not_reported_as_requests(tmp_path: Path) -> None:
    nodes, _ = CodeParser().parse_bytes(
        tmp_path / "map.ts",
        b"export function lookup(cache) { return cache.get('account'); }",
    )
    assert not [node for node in nodes if node.kind == "HttpRequest"]


def test_resolves_local_url_from_static_class_path(tmp_path: Path) -> None:
    source = b"""
export class AdminOrganizationsService {
  private static readonly BASE_PATH = '/admin/organizations';

  static async getOrganizations(filters: URLSearchParams) {
    const url = `${AdminOrganizationsService.BASE_PATH}?${filters.toString()}`;
    return api.get(url);
  }
}

export function unrelated() {
  const url = '/wrong-scope';
  return api.get(url);
}
"""
    nodes, _ = CodeParser().parse_bytes(
        tmp_path / "admin-organizations.service.ts", source,
    )
    requests = [node for node in nodes if node.kind == "HttpRequest"]
    assert len(requests) == 2
    organization = next(
        item for item in requests
        if item.extra["route"].startswith("/admin/organizations?")
    )
    assert organization.extra["dynamic"] is False
