#!/usr/bin/env python3
"""Posts one synthetic finding straight to a real Slack webhook, bypassing the rest of the
analysis pipeline entirely - the fastest way to see the actual rendered message in a channel
and confirm SlackConfig/SlackNotifier are wired correctly before relying on a real finding to
trigger it.

Usage:
    export OPS_SIGNALS_SLACK_ENABLED=true
    export OPS_SIGNALS_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T000/B000/XXXX
    ./scripts/send_test_slack_finding.py

    # or pass the webhook URL directly, without touching env vars:
    ./scripts/send_test_slack_finding.py --webhook-url https://hooks.slack.com/services/T000/B000/XXXX

    # confirm the importance filter actually skips low-importance findings:
    ./scripts/send_test_slack_finding.py --importance 0.2
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import get_slack_config
from backend.app.notifications.slack_client import SlackNotifier
from intelligence.findings.schema import OperationalFinding


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--webhook-url", default=None, help="Overrides OPS_SIGNALS_SLACK_WEBHOOK_URL for this run only")
    parser.add_argument("--importance", type=float, default=0.93, help="importance_score on the synthetic finding (default: %(default)s)")
    parser.add_argument("--service", default="payments-api")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config = get_slack_config()
    if args.webhook_url:
        config.webhook_url = args.webhook_url
        config.enabled = True

    if not config.enabled:
        print("OPS_SIGNALS_SLACK_ENABLED is not set to true and --webhook-url was not given - nothing to test.")
        print("Set OPS_SIGNALS_SLACK_ENABLED=true and OPS_SIGNALS_SLACK_WEBHOOK_URL=<your webhook>, or pass --webhook-url.")
        raise SystemExit(1)
    if not config.webhook_url:
        print("No webhook URL configured. Set OPS_SIGNALS_SLACK_WEBHOOK_URL or pass --webhook-url.")
        raise SystemExit(1)

    finding = OperationalFinding(
        service=args.service,
        metric_name="cpu_usage",
        title=f"CPU spike on {args.service}",
        summary="The current window is materially above the previous baseline and shows sustained elevated utilization.",
        category="anomaly",
        health_status="critical" if args.importance >= 0.8 else "significant" if args.importance >= 0.55 else "normal",
        importance_score=args.importance,
    )

    if finding.importance_score < config.minimum_importance:
        print(
            f"importance_score={finding.importance_score} is below minimum_importance="
            f"{config.minimum_importance} - SlackNotifier will skip this finding and post nothing."
        )
        print("Pass a higher --importance, or lower OPS_SIGNALS_SLACK_MIN_IMPORTANCE, to actually see a message.")
        raise SystemExit(0)

    print(f"Posting to {config.webhook_url[:40]}...")
    SlackNotifier(config).notify_findings([finding])
    print("Done. Check the Slack channel the webhook is bound to.")
    print("(A WARNING above means delivery failed - see the message for why; nothing else here confirms success,")
    print("since Slack incoming webhooks only return 'ok' text, not a message we can inspect.)")


if __name__ == "__main__":
    main()
