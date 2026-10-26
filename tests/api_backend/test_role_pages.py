"""Which web UI pages each role may open (backend/app/roles.py PAGES), as GET /api/me hands them to the
web UI. The web UI hides the rest from its menu and closes them when opened by address."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.roles import PAGES, page_role, pages_for

ROUTES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "routes" / "AppRoutes.tsx"


@pytest.mark.parametrize(
    ("path", "needed"),
    [
        ("/", "Viewer"),
        ("/findings", "Viewer"),
        ("/cases/412", "Viewer"),
        ("/signals/abc", "Viewer"),
        ("/assistant", "Viewer"),
        ("/autonomous-monitoring", "Viewer"),
        ("/validate-data", "Editor"),
        ("/analyzer-recommendation", "Editor"),
        ("/assistant/docs-check", "Admin"),
        ("/experiments/trend-lab", "Admin"),
        ("/integrations", "Admin"),
        ("/settings/", "Admin"),
        ("/setup-check", "Admin"),
        ("/a-page-nobody-listed", "Admin"),
        ("/findingsx", "Admin"),
    ],
)
def test_each_page_needs_the_role_the_table_says(path: str, needed: str) -> None:
    assert page_role(path) == needed


def test_every_page_route_is_listed_and_guarded() -> None:
    """A page added to AppRoutes.tsx without a PAGES entry would be closed to everyone but Admins, and
    one without RoleArea would open for everyone."""
    source = ROUTES.read_text()
    routes = re.findall(r'<Route path=(?:"([^"]+)"|\{(\w+)\}) element=\{<(?!Navigate|RedirectKeepingQuery)(\w+)', source)
    assert len(routes) > 20
    for literal, constant, wrapper in routes:
        assert wrapper == "RoleArea", literal or constant
        path = literal or {"DOCS_CHECK_PATH": "/assistant/docs-check"}[constant]
        base = re.sub(r"/:[^/]+", "", path)
        assert base in PAGES or any(base.startswith(f"{entry}/") for entry in PAGES if entry != "/"), path


def test_only_viewers_see_autonomous_analysis_read_only() -> None:
    assert pages_for("Viewer")[1] == ["/autonomous-monitoring"]
    assert pages_for("Editor")[1] == []
    assert pages_for(None) == (PAGES, [])


@pytest.fixture()
def dev_user(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPS_SIGNALS_API_TOKEN", raising=False)
    monkeypatch.setenv("OPS_SIGNALS_AUTH_MODE", "none")

    def as_role(role: str) -> None:
        monkeypatch.setenv("OPS_SIGNALS_DEV_USER", f"sam@example.com:{role}")
    return as_role


def test_me_lists_the_pages_and_the_read_only_ones(dev_user, client: TestClient) -> None:
    dev_user("Viewer")
    viewer = client.get("/api/me").json()
    assert viewer["role"] == "Viewer"
    assert viewer["pages"]["/validate-data"] == "Editor"
    assert viewer["read_only_pages"] == ["/autonomous-monitoring"]

    dev_user("Admin")
    assert client.get("/api/me").json()["read_only_pages"] == []


def test_without_sign_in_me_still_lists_the_pages(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.delenv("OPS_SIGNALS_DEV_USER", raising=False)
    me = client.get("/api/me").json()
    assert (me["signed_in"], me["read_only_pages"]) == (False, [])
    assert me["pages"] == PAGES
