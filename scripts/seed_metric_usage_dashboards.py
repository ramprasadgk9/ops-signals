#!/usr/bin/env python3
"""Load the metric-usage test dashboards and alert rules into a local Grafana, so the metric usage
check has something real to read. The same JSON files are the fixtures the unit tests use
(tests/fixtures/grafana_metric_usage), so what you see in Grafana is exactly what the tests check.

Everything this script creates has a "cov-test-" uid, so --remove deletes only its own objects.

Usage:
    ./scripts/seed_metric_usage_dashboards.py              # create or update in http://localhost:3000
    ./scripts/seed_metric_usage_dashboards.py --remove     # delete the test dashboards, rules and folders
    ./scripts/seed_metric_usage_dashboards.py --url http://localhost:3001 --user admin --password admin
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "grafana_metric_usage"


class Grafana:
    def __init__(self, url: str, user: str, password: str) -> None:
        self.url = url.rstrip("/")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

    def call(self, method: str, path: str, body: object | None = None, extra_headers: dict[str, str] | None = None) -> tuple[int, object]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"{self.url}{path}", data=data, method=method, headers={**self.headers, **(extra_headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return exc.code, raw.decode(errors="replace")


def _dashboards() -> list[dict]:
    return [json.loads(path.read_text()) for path in sorted((FIXTURES_DIR / "dashboards").glob("*.json"))]


def _alert_rules() -> list[dict]:
    return json.loads((FIXTURES_DIR / "alert_rules.json").read_text())


def _folders() -> dict[str, str]:
    return {item["meta"]["folderUid"]: item["meta"]["folderTitle"] for item in _dashboards()}


def seed(grafana: Grafana) -> None:
    for uid, title in _folders().items():
        status, _ = grafana.call("GET", f"/api/folders/{uid}")
        if status == 404:
            status, body = grafana.call("POST", "/api/folders", {"uid": uid, "title": title})
            if status >= 300:
                sys.exit(f"Creating folder {title} failed ({status}): {body}")
        print(f"folder     {title}")

    for item in _dashboards():
        payload = {"dashboard": {**item["dashboard"], "id": None}, "folderUid": item["meta"]["folderUid"], "overwrite": True}
        status, body = grafana.call("POST", "/api/dashboards/db", payload)
        if status >= 300:
            sys.exit(f"Saving dashboard {item['dashboard']['title']} failed ({status}): {body}")
        print(f"dashboard  {item['meta']['folderTitle']} / {item['dashboard']['title']}")

    # X-Disable-Provenance keeps the rules editable in the Grafana UI, like hand-made ones.
    no_provenance = {"X-Disable-Provenance": "true"}
    for rule in _alert_rules():
        status, _ = grafana.call("GET", f"/api/v1/provisioning/alert-rules/{rule['uid']}")
        if status == 404:
            status, body = grafana.call("POST", "/api/v1/provisioning/alert-rules", rule, no_provenance)
        else:
            status, body = grafana.call("PUT", f"/api/v1/provisioning/alert-rules/{rule['uid']}", rule, no_provenance)
        if status >= 300:
            sys.exit(f"Saving alert rule {rule['title']} failed ({status}): {body}")
        print(f"alert      {rule['title']}")

    print(f"\nDone. Open {grafana.url}/dashboards?tag=ops-signals-metric-usage-test")


def remove(grafana: Grafana) -> None:
    for rule in _alert_rules():
        status, _ = grafana.call("DELETE", f"/api/v1/provisioning/alert-rules/{rule['uid']}")
        print(f"alert      {rule['title']}: {'deleted' if status < 300 else 'not found'}")
    for item in _dashboards():
        status, _ = grafana.call("DELETE", f"/api/dashboards/uid/{item['dashboard']['uid']}")
        print(f"dashboard  {item['dashboard']['title']}: {'deleted' if status < 300 else 'not found'}")
    for uid, title in _folders().items():
        status, _ = grafana.call("DELETE", f"/api/folders/{uid}")
        print(f"folder     {title}: {'deleted' if status < 300 else 'not found'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:3000")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--remove", action="store_true", help="delete everything this script created")
    args = parser.parse_args()
    grafana = Grafana(args.url, args.user, args.password)
    remove(grafana) if args.remove else seed(grafana)


if __name__ == "__main__":
    main()
