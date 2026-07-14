from __future__ import annotations


def calculate_confidence(condition_matches: list[dict], correlation_matched: bool) -> float:
    if not condition_matches:
        return 0.0
    passed = sum(1 for item in condition_matches if item["passed"])
    base = passed / len(condition_matches)
    if correlation_matched:
        base += 0.2
    return min(1.0, round(base, 3))
