from __future__ import annotations

from intelligence.findings.schema import OperationalFinding

_SEVERITY_ICON = {
    "critical": "🔴",
    "significant": "🟡",
    "normal": "🟢",
}

# Slack's header block rejects text over 150 characters.
_HEADER_MAX_LEN = 150


def build_finding_blocks(finding: OperationalFinding) -> dict:
    icon = _SEVERITY_ICON.get(finding.health_status, "⚪")
    header_text = f"{icon} {finding.title}"[:_HEADER_MAX_LEN]

    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": header_text, "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": finding.summary or "No summary available."},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Service:*\n{finding.service or 'unknown'}"},
                    {"type": "mrkdwn", "text": f"*Metric:*\n{finding.metric_name}"},
                    {"type": "mrkdwn", "text": f"*Category:*\n{finding.category}"},
                    {"type": "mrkdwn", "text": f"*Importance:*\n{finding.importance_score:.2f}"},
                ],
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "Posted by Ops Signals"}],
            },
        ],
    }
