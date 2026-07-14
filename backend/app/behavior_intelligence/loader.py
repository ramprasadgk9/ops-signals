from __future__ import annotations

from pathlib import Path

import yaml

from .models import BehaviorCondition, BehaviorDefinition, BehaviorInput, BehaviorOutput


def load_definitions(config_path: str | Path) -> list[BehaviorDefinition]:
    path = Path(config_path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    defs = raw.get("behavior_definitions", {}) or {}
    out: list[BehaviorDefinition] = []
    for definition_id, details in defs.items():
        inputs = [
            BehaviorInput(alias=item["alias"], metric_name=item["metric_name"], analyzers=list(item.get("analyzers", [])))
            for item in details.get("inputs", [])
        ]
        conditions = {
            key: [BehaviorCondition(fact=cond["fact"], operator=cond["operator"], value=cond["value"]) for cond in details.get("conditions", {}).get(key, [])]
            for key in ("all", "any")
        }
        output = details.get("output", {})
        out.append(
            BehaviorDefinition(
                id=definition_id,
                enabled=bool(details.get("enabled", True)),
                version=int(details.get("version", 1)),
                title=details.get("title", definition_id),
                description=details.get("description", ""),
                scope=dict(details.get("scope", {})),
                inputs=inputs,
                conditions=conditions,
                correlation=dict(details.get("correlation", {})),
                output=BehaviorOutput(
                    category=output.get("category", "behavior"),
                    severity=output.get("severity", "medium"),
                    title=output.get("title", details.get("title", definition_id)),
                    summary=output.get("summary", ""),
                    evidence=list(output.get("evidence", [])),
                ),
            )
        )
    return out
