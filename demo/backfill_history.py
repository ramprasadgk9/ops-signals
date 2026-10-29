"""One-shot: write the demo timeline and 7h of metric history for every Prometheus service in the
story as OpenMetrics, for promtool to turn into Prometheus blocks before Prometheus starts
(docker-compose.demo.yml: demo-history).

Idempotent: if a timeline already exists the history was already backfilled, so this exits
without touching anything - a second `docker compose up` keeps the original incident. Reset with
`docker compose -f docker-compose.demo.yml down -v`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scenario  # noqa: E402


def main() -> int:
    state_dir = Path(os.environ.get("DEMO_STATE_DIR", "/demo-state"))
    if scenario.read_timeline(state_dir) is not None:
        print("demo-history: timeline already exists, keeping it")
        return 0

    timeline = scenario.new_timeline()
    start = scenario.parse_time(timeline["history_start"]).timestamp()
    # Stop one step short of now: the live scrape takes over from there, and promtool blocks must
    # not overlap the samples Prometheus is about to scrape.
    end = scenario.parse_time(timeline["anchor"]).timestamp() - scenario.STEP_SECONDS
    target = {"job": scenario.SCRAPE_JOB, "instance": scenario.SCRAPE_INSTANCE}

    lines: list[str] = []
    family = None
    for series in scenario.prometheus_series(timeline):
        # OpenMetrics wants each family's samples together, in time order, one series after another.
        if series.name != family:
            family = series.name
            lines.append(f"# TYPE {family} gauge")
        series_labels = scenario.format_labels({**series.labels, **target})
        t = start
        while t <= end:
            value = series.value_at(t)
            if value is not None:
                lines.append(f"{series.name}{{{series_labels}}} {value:.4f} {int(t)}")
            t += scenario.STEP_SECONDS
    lines.append("# EOF")

    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / scenario.HISTORY_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Written last: its presence means the history file is complete.
    scenario.write_timeline(state_dir, timeline)
    print(
        f"demo-history: wrote {len(lines)} lines, shift at {timeline['shift_at']}, "
        f"deploy {scenario.CURRENT_DEPLOY_VERSION} at {timeline['deploy_at']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
