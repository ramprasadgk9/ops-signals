from __future__ import annotations

from typing import Any

from backend.app.integrations.ticketing.models import TicketDraft, TicketResolutionDraft


def build_case_resolution_adf_comment(resolution: TicketResolutionDraft) -> dict:
    """Builds a Jira Cloud v3 Atlassian Document Format (ADF) closing resolution comment."""
    status_label = "Verified Resolution" if resolution.root_cause_verified else "Case Resolution"
    content: list[dict] = [
        {
            "type": "heading",
            "attrs": {"level": 3},
            "content": [
                {"type": "text", "text": f"🎯 Ops Signals Incident Resolution: Case #{resolution.case_id}"}
            ],
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Status: ", "marks": [{"type": "strong"}]},
                {"type": "text", "text": f"{resolution.outcome_status.upper()} ({status_label})"},
            ],
        },
    ]

    if resolution.root_cause_summary:
        content.append(
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Root Cause: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": resolution.root_cause_summary},
                ],
            }
        )

    if resolution.corrective_action:
        content.append(
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Corrective Action: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": resolution.corrective_action},
                ],
            }
        )

    if resolution.outcome_summary:
        content.append(
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Outcome Summary: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": resolution.outcome_summary},
                ],
            }
        )

    if resolution.deep_link_url:
        content.append(
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": f"View Case #{resolution.case_id} in Ops Signals",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": resolution.deep_link_url},
                            }
                        ],
                    }
                ],
            }
        )

    return {
        "version": 1,
        "type": "doc",
        "content": content,
    }


def build_case_adf_description(draft: TicketDraft) -> dict:
    """Builds a Jira Cloud v3 Atlassian Document Format (ADF) document tree."""
    content: list[dict] = [
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [
                {"type": "text", "text": f"Ops Signals Case #{draft.case_id}: {draft.case_title}"}
            ],
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Summary: ", "marks": [{"type": "strong"}]},
                {"type": "text", "text": draft.summary or "No summary provided."},
            ],
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Service: ", "marks": [{"type": "strong"}]},
                {"type": "text", "text": f"{draft.service}   |   "},
                {"type": "text", "text": "Metric: ", "marks": [{"type": "strong"}]},
                {"type": "text", "text": f"{draft.metric_name}   |   "},
                {"type": "text", "text": "Health: ", "marks": [{"type": "strong"}]},
                {"type": "text", "text": f"{draft.health_status}   |   "},
                {"type": "text", "text": "Importance: ", "marks": [{"type": "strong"}]},
                {"type": "text", "text": f"{draft.importance_score:.2f}"},
            ],
        },
    ]

    if draft.rca_summary:
        content.append(
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Root Cause: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": draft.rca_summary},
                ],
            }
        )

    if draft.deep_link_url:
        content.append(
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "View Case in Ops Signals",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": draft.deep_link_url},
                            }
                        ],
                    }
                ],
            }
        )

    return {
        "version": 1,
        "type": "doc",
        "content": content,
    }


def adf_to_plain_text(node: Any) -> str:
    """Recursively extracts plain text from Atlassian Document Format (ADF) nodes."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_plain_text(item) for item in node)
    if isinstance(node, dict):
        node_type = node.get("type")
        if node_type == "text":
            return node.get("text", "")
        content = node.get("content", [])
        inner_text = "".join(adf_to_plain_text(item) for item in content)
        if node_type in ("paragraph", "heading"):
            return inner_text.strip() + "\n\n"
        if node_type == "listItem":
            return f"- {inner_text.strip()}\n"
        return inner_text
    return str(node)
