from __future__ import annotations

from typing import Any

from .models import BehaviorCondition


def _resolve_fact(facts: dict[str, Any], path: str) -> Any:
    current: Any = facts
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def evaluate_condition(facts: dict[str, Any], condition: BehaviorCondition) -> bool:
    left = _resolve_fact(facts, condition.fact)
    right = condition.value
    if condition.operator == "equals":
        return left == right
    if condition.operator == "greater_than":
        return left is not None and left > right
    if condition.operator == "less_than":
        return left is not None and left < right
    if condition.operator == "contains":
        return left is not None and right in left
    return False


def evaluate_conditions(facts: dict[str, Any], conditions: dict[str, list[BehaviorCondition]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for group_name in ("all", "any"):
        for condition in conditions.get(group_name, []):
            results.append(
                {
                    "group": group_name,
                    "fact": condition.fact,
                    "operator": condition.operator,
                    "value": condition.value,
                    "passed": evaluate_condition(facts, condition),
                }
            )
    return results
