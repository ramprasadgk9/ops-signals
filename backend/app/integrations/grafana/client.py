"""Read-only Grafana HTTP API client: dashboards, folders, alert rules, datasources, library panels."""

from __future__ import annotations

import base64
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from backend.app.config import GrafanaConfig

_SEARCH_PAGE_SIZE = 5000


class GrafanaError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class GrafanaClient:
    def __init__(self, config: GrafanaConfig) -> None:
        if not config.base_url:
            raise GrafanaError("Grafana is not configured. Set OPS_SIGNALS_GRAFANA_URL.")
        self.config = config

    def check(self) -> str:
        """Raises GrafanaError when Grafana can't be reached or the credentials can't list dashboards."""
        health = self._get("/api/health")
        self._get("/api/search", {"type": "dash-db", "limit": 1})
        return str(health.get("version") or "") if isinstance(health, dict) else ""

    def list_dashboards(self) -> list[dict]:
        found: list[dict] = []
        page = 1
        while True:
            batch = self._get("/api/search", {"type": "dash-db", "limit": _SEARCH_PAGE_SIZE, "page": page})
            found.extend(batch or [])
            if not batch or len(batch) < _SEARCH_PAGE_SIZE:
                return found
            page += 1

    def get_dashboard(self, uid: str) -> dict:
        return self._get(f"/api/dashboards/uid/{quote(uid, safe='')}")

    def folder_titles(self) -> dict[str, str]:
        return {folder["uid"]: folder["title"] for folder in self._get("/api/folders", {"limit": 1000}) or [] if folder.get("uid")}

    def alert_rules(self) -> list[dict]:
        return self._get("/api/v1/provisioning/alert-rules") or []

    def datasource_types(self) -> dict[str, str]:
        """uid and name -> plugin type, so queries pointing at a datasource by either can be told apart."""
        types: dict[str, str] = {}
        for datasource in self._get("/api/datasources") or []:
            for key in (datasource.get("uid"), datasource.get("name")):
                if key and datasource.get("type"):
                    types[key] = datasource["type"]
        return types

    def library_panel(self, uid: str) -> dict:
        return (self._get(f"/api/library-elements/{quote(uid, safe='')}").get("result") or {}).get("model") or {}

    def _get(self, path: str, params: dict[str, object] | None = None):
        url = f"{self.config.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(url, headers=self._headers())
        context = None if self.config.verify_tls else ssl._create_unverified_context()
        try:
            with urlopen(request, timeout=self.config.timeout_seconds, context=context) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise GrafanaError(f"Grafana refused {path} ({exc.code}): check the token's role", exc.code) from exc
            raise GrafanaError(f"Grafana returned {exc.code} for {path}", exc.code) from exc
        except TimeoutError as exc:
            raise GrafanaError("Grafana request timed out") from exc
        except URLError as exc:
            raise GrafanaError(f"Grafana connection failed: {exc.reason}") from exc
        try:
            return json.loads(body) if body else None
        except json.JSONDecodeError as exc:
            raise GrafanaError(f"Grafana returned malformed JSON for {path}") from exc

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        elif self.config.username is not None and self.config.password is not None:
            raw = f"{self.config.username}:{self.config.password}".encode("utf-8")
            headers["Authorization"] = f"Basic {base64.b64encode(raw).decode('ascii')}"
        return headers
