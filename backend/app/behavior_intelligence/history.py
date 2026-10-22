from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from .condition_evaluator import _resolve_fact
from .fact_extractor import input_facts
from .finding_builder import build_evaluation
from .models import BehaviorDefinition


def _condition_text(condition: dict[str, Any]) -> str:
    return f"{condition['fact']} {condition['operator']} {condition['value']}"


def judge_run(definition: BehaviorDefinition, run_id: str, at: datetime | None, signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Whether the definition matches one analysis run's signals, and if not, what stopped it:
    an input with no signals from its analyzers (the run can't be judged), the conditions that
    failed, or the timing check. The same matching as the pipeline, nothing saved."""
    matched_inputs: dict[str, dict[str, Any]] = {}
    for item in definition.inputs:
        found = input_facts(item.metric_names, item.analyzers, signals)
        if found is not None:
            matched_inputs[item.alias] = found
    missing = [item.alias for item in definition.inputs if item.alias not in matched_inputs]
    starts = [signal["start_time"] for signal in signals if signal.get("start_time")]
    ends = [signal.get("end_time") or signal["start_time"] for signal in signals if signal.get("start_time")]
    run: dict[str, Any] = {
        "analysis_run_id": run_id, "at": at, "matched": False, "missing_inputs": missing, "blocked_by": [], "conditions": [], "overlap_minutes": None,
        "confidence": None, "changes": [],
        # When this run's signals on the rule's metrics were active, for the chart.
        "start": min(starts) if starts else None, "end": max(ends) if ends else None,
    }
    if missing:
        return run

    evaluation = build_evaluation(definition, matched_inputs, matched_inputs, None, run_id)
    # Each condition with the value it was checked against, for the run's details.
    conditions = [{**item, "actual": _resolve_fact(matched_inputs, item["fact"])} for item in evaluation.matched_conditions]
    run["conditions"] = conditions
    run["matched"] = evaluation.matched
    run["confidence"] = evaluation.confidence
    run["changes"] = [
        {"alias": alias, "signed_change_percent": facts["change"]["signed_change_percent"]}
        for alias, facts in matched_inputs.items()
        if facts.get("change", {}).get("present")
    ]
    run["overlap_minutes"] = evaluation.correlation.get("overlap_minutes")
    if evaluation.matched:
        return run
    blocked = [_condition_text(item) for item in conditions if item["group"] == "all" and not item["passed"]]
    any_conditions = [item for item in conditions if item["group"] == "any"]
    if any_conditions and not any(item["passed"] for item in any_conditions):
        blocked.append("none of: " + "; ".join(_condition_text(item) for item in any_conditions))
    if not blocked and not evaluation.correlation.get("matched"):
        blocked.append("timing: the metrics did not change at the same time")
    run["blocked_by"] = blocked
    return run


def summarize(definition: BehaviorDefinition, runs: list[dict[str, Any]]) -> dict[str, Any]:
    """One verdict over the judged runs, newest first:
    fired      - matched in at least one run;
    cant_check - in every run some input had no signal from its analyzers, so nothing was tested;
    never      - judged at least once and never matched, with the most common reason why;
    no_runs    - no analysis run of this service in the look-back."""
    judged = [run for run in runs if not run["missing_inputs"]]
    matched = [run for run in runs if run["matched"]]
    conditions: list[dict[str, Any]] = []
    for group in ("all", "any"):
        for condition in definition.conditions.get(group, []):
            fact = condition.fact
            passed = sum(
                1 for run in judged for item in run["conditions"]
                if item["group"] == group and item["fact"] == fact and item["passed"]
            )
            conditions.append({"group": group, "fact": fact, "operator": condition.operator, "value": condition.value, "passed_runs": passed})
    inputs = [
        {
            "alias": item.alias,
            "metric_name": item.metric_name,
            "analyzers": list(item.analyzers),
            "runs_with_signals": sum(1 for run in runs if item.alias not in run["missing_inputs"]),
        }
        for item in definition.inputs
    ]

    if not runs:
        verdict, reason = "no_runs", None
    elif matched:
        verdict, reason = "fired", None
    elif not judged:
        never_seen = [entry["alias"] for entry in inputs if entry["runs_with_signals"] == 0]
        reason = f"no signals for {', '.join(never_seen or [entry['alias'] for entry in inputs if entry['runs_with_signals'] < len(runs)])}"
        verdict = "cant_check"
    else:
        verdict = "never"
        common = Counter(blocker for run in judged for blocker in run["blocked_by"]).most_common(1)
        reason = common[0][0] if common else None
    return {
        "verdict": verdict,
        "reason": reason,
        "runs_checked": len(runs),
        "runs_judged": len(judged),
        "runs_matched": len(matched),
        "conditions": conditions,
        "inputs": inputs,
    }
