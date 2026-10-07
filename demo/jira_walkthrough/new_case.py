"""Open a fresh case for the Jira walkthrough on a running demo stack, and print its id.

A finding has at most one case and a case at most one ticket, so each recording needs its own:
this analyzes a new copy of the demo's checkout-api latency shift (ending now) through the public
API and opens a case from the finding, the same way demo/seed.py seeds the past incident.

    python3 demo/jira_walkthrough/new_case.py        # DEMO_WEB_URL defaults to http://localhost:8080
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# seed.py reads its backend URL at import; the web container proxies /api to the backend.
os.environ.setdefault("DEMO_BACKEND_URL", os.environ.get("DEMO_WEB_URL", "http://localhost:8080"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scenario  # noqa: E402
import seed  # noqa: E402


def main() -> int:
    # past_incident_csv() ends its window PAST_INCIDENT_DAYS_AGO before the anchor, so this window ends now.
    anchor = datetime.now(timezone.utc) + timedelta(days=scenario.PAST_INCIDENT_DAYS_AGO)
    run = seed.post_csv(
        "/api/ingestion/csv-run",
        "checkout-api-latency.csv",
        scenario.past_incident_csv(anchor),
        {
            "provider": "generic",
            "service": scenario.SERVICE,
            "metric_name": scenario.LATENCY_METRIC,
            "interval": "30s",
        },
    )
    findings = [
        finding
        for finding in seed.get(f"/api/findings?analysis_run_id={run['analysis_run_id']}")
        if finding.get("health_status") != "normal"
    ]
    if not findings:
        raise RuntimeError(f"analysis {run['analysis_run_id']} produced no significant finding")
    case = seed.send("POST", f"/api/cases/findings/{findings[0]['id']}/create", {})
    print(case["case_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
