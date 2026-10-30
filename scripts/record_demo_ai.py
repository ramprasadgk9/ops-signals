#!/usr/bin/env python3
"""Record the demo's AI answers from a real model, for the hosted demo's `recorded` provider.

Asks for every AI answer a visitor can get on the demo story, against a running demo whose backend
records them (OPS_SIGNALS_AI_RECORD_TO). The answers file is then shipped as
config/demo_ai/recorded_answers.json. Steps in docs/demo.md, "Record the AI answers".

    ./scripts/record_demo_ai.py --web-url http://localhost:8080

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TOUR_QUESTIONS = [
    "Have we seen payments-db connection pool problems before?",
    "How did we fix checkout latency last time?",
]


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/") + "/api"

    def call(self, method: str, path: str, body: object | None = None, timeout: float = 180):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(f"{self.base}{path}", data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            return {"_error": f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}"}
        except (URLError, TimeoutError, OSError) as exc:
            return {"_error": str(exc)}
        return json.loads(raw) if raw else None

    def get(self, path: str):
        return self.call("GET", path)

    def post(self, path: str, body: object | None = None):
        return self.call("POST", path, body if body is not None else {})


def report(label: str, result: object) -> bool:
    if isinstance(result, dict) and "_error" in result:
        ok, detail = False, result["_error"]
    elif isinstance(result, dict) and "available" in result:
        ok = bool(result["available"])
        detail = result.get("draft") or result.get("note") or result.get("reasons") or result.get("reason") or ""
    else:
        ok, detail = True, ""
    print(f"  {'ok  ' if ok else 'MISS'}  {label}: {str(detail)[:110]}", flush=True)
    return ok


def recent(finding: dict, hours: float = 3) -> bool:
    stamp = datetime.fromisoformat(finding["created_at"].replace("Z", "+00:00"))
    stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    return stamp > datetime.now(timezone.utc) - timedelta(hours=hours)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--web-url", default="http://localhost:8080")
    args = parser.parse_args()
    api = Api(args.web_url)

    status = api.get("/ai/status")
    if not isinstance(status, dict) or not status.get("active") or status.get("provider") == "recorded":
        print(f"AI must be on with a real model to record (got {status})", file=sys.stderr)
        return 1
    print(f"recording from {status.get('provider')} / {status.get('model')}")

    findings = [f for f in api.get("/findings?limit=200") if f.get("health_status") != "normal"]
    live = [f for f in findings if recent(f)]
    cases = api.get("/cases?limit=50")
    misses = 0

    def latest(service: str, metric: str | None = None) -> dict | None:
        return next((f for f in live if f["service"] == service and (metric is None or f["metric_name"] == metric)), None)

    print("findings (wording in plain words, one per problem):")
    seen: set[tuple[str, str]] = set()
    for finding in live:
        key = (finding["service"], finding["metric_name"])
        if key in seen:
            continue
        seen.add(key)
        misses += not report(f"wording {key}", api.get(f"/findings/{finding['id']}/ai-wording"))

    print("cases:")
    checkout = latest("checkout-api", "request_latency_p95")
    if checkout:
        new_case = api.post(f"/cases/findings/{checkout['id']}/create")
        misses += not report("checkout new case: root cause", api.post(f"/cases/{new_case['case_id']}/rca/suggest"))
    payments = latest("payments-db", "db_connection_wait_seconds")
    if payments:
        payments_case = api.post(f"/cases/findings/{payments['id']}/create")
        misses += not report("payments new case: root cause", api.post(f"/cases/{payments_case['case_id']}/rca/suggest"))
        misses += not report("payments new case: why the fix didn't hold", api.post(f"/cases/{payments_case['case_id']}/fix-came-back/why"))
        misses += not report("payments finding: why the fix didn't hold", api.post(f"/findings/{payments['id']}/fix-came-back/why"))
        misses += not report("payments finding: runbook", api.post(f"/findings/{payments['id']}/suggested-fixes/runbook-draft"))
    if checkout:
        misses += not report("checkout finding: runbook", api.post(f"/findings/{checkout['id']}/suggested-fixes/runbook-draft"))
    for case in cases:
        if case.get("investigation_status") == "in_progress":
            misses += not report(f"case #{case['id']} (in progress): root cause", api.post(f"/cases/{case['id']}/rca/suggest"))
            misses += not report(f"case #{case['id']} (in progress): resolution", api.post(f"/cases/{case['id']}/resolution/suggest"))
        elif case.get("outcome_status") == "resolved":
            misses += not report(f"case #{case['id']} (resolved): write-up", api.post(f"/cases/{case['id']}/writeup/suggest"))

    print("overview, recurring problems, assistant:")
    misses += not report("shift handoff note", api.post("/overview/handoff/note"))
    report("recurring problem names", api.get("/memory/recurring-problems"))
    starters = api.get("/assistant/starter-questions") or {}
    questions = [*TOUR_QUESTIONS, *[q.get("question", q) if isinstance(q, dict) else q for q in starters.get("questions", [])][:6]]
    for question in questions:
        answer = api.post("/assistant/chat", {"message": question})
        report(f"assistant: {question}", {"available": bool(answer and answer.get("ai_synthesis_used"))} if isinstance(answer, dict) else answer)

    print("combined pattern explanations (written in the background):")
    for _ in range(40):
        patterns = api.get("/behavior-evaluations")
        missing = [p for p in patterns if not p.get("ai_explanation")]
        if not missing:
            break
        time.sleep(15)
    report(f"{len(patterns) - len(missing)} of {len(patterns)} patterns explained", {"available": not missing})

    print(f"done; {misses} answer(s) not available (the feature's checks dropped them or the model failed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
