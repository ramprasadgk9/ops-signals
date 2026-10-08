"""Turn an alert's rule expression into the query Ops Signals analyzes.

Deliberately a small scanner, not a PromQL parser: anything it can't handle confidently returns
None, and the rule author can always supply `ops_signals_query` instead.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.app.config import AlertEnrichmentConfig, parse_duration_seconds

_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$|^[+-]?(?:Inf|NaN)$", re.IGNORECASE)
_COMPARISON_OPS = ("==", "!=", ">=", "<=", ">", "<")
_SET_OPERATORS = re.compile(r"\b(and|or|unless)\b", re.IGNORECASE)
_GROUPING_CLAUSE = re.compile(r"\b(by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", re.IGNORECASE)
# Not preceded by a digit/dot (the `m` in `5m`, the `e3` in `1e3`) or `$` (a Grafana variable).
_IDENTIFIER = re.compile(r"(?<![\w.$])[a-zA-Z_:][a-zA-Z0-9_:]*")
_COMMENT = re.compile(r"#[^\n]*")
_KEYWORDS = {
    "by", "without", "on", "ignoring", "group_left", "group_right", "bool", "and", "or", "unless",
    "offset", "inf", "nan", "atan2",
}


def mask_nested(expr: str) -> str:
    """Replace everything inside (), {}, [] and quotes with spaces, keeping positions - so
    operators found in the result are top-level ones."""
    masked: list[str] = []
    depth = 0
    quote: str | None = None
    escaped = False
    for char in expr:
        if quote:
            masked.append(" ")
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'`":
            quote = char
            masked.append(" ")
            continue
        if char in "({[":
            depth += 1
            masked.append(char if depth == 1 else " ")
            continue
        if char in ")}]":
            masked.append(char if depth == 1 else " ")
            depth = max(depth - 1, 0)
            continue
        masked.append(char if depth == 0 else " ")
    return "".join(masked)


def strip_threshold(expr: str) -> str | None:
    """`<metric expr> > 0.3` -> `<metric expr>` (either side may hold the scalar).

    Returns the expression unchanged when it has no top-level comparison, and None when it has
    one we can't safely strip (vector-vs-vector, several comparisons, set operators)."""
    expr = expr.strip()
    masked = mask_nested(expr)
    if _SET_OPERATORS.search(masked):
        return None

    positions: list[tuple[int, str]] = []
    index = 0
    while index < len(masked):
        for op in _COMPARISON_OPS:
            if masked.startswith(op, index):
                # `=~` / `!~` only appear inside {} (masked away); a lone `=` isn't a comparison.
                positions.append((index, op))
                index += len(op)
                break
        else:
            index += 1

    if not positions:
        return expr
    if len(positions) > 1:
        return None

    position, op = positions[0]
    left = expr[:position].strip()
    right = expr[position + len(op):].strip()
    right = re.sub(r"^bool\b", "", right, flags=re.IGNORECASE).strip()
    if _NUMBER.match(right) and left:
        return left
    if _NUMBER.match(left) and right:
        return right
    return None


def metric_names(expr: str) -> list[str]:
    """Metric selector names in order of appearance: `histogram_quantile(0.95, sum by (le)
    (rate(x_bucket{a="b"}[5m])))` -> ["x_bucket"]."""
    cleaned = _COMMENT.sub(" ", _strip_quotes(expr))
    cleaned = re.sub(r"\{[^}]*\}", " ", cleaned)
    cleaned = re.sub(r"\[[^\]]*\]", " ", cleaned)
    cleaned = _GROUPING_CLAUSE.sub(" ", cleaned)
    names: list[str] = []
    for match in _IDENTIFIER.finditer(cleaned):
        name = match.group(0)
        following = cleaned[match.end():].lstrip()
        if following.startswith("("):
            continue  # function call
        if name.lower() in _KEYWORDS or _NUMBER.match(name):
            continue
        if name not in names:
            names.append(name)
    # A bare `{__name__="x"}` / `{job="y"}` selector has no leading name; fine to return [].
    return names


def _strip_quotes(expr: str) -> str:
    return re.sub(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`[^`]*`", '""', expr)


@dataclass(frozen=True)
class QueryWindow:
    start: datetime
    end: datetime
    step_seconds: int

    @property
    def step(self) -> str:
        return f"{self.step_seconds}s"


def query_window(
    config: AlertEnrichmentConfig,
    annotations: dict[str, str],
    now: datetime | None = None,
) -> QueryWindow:
    end = now or datetime.now(timezone.utc)
    lookback = config.lookback_seconds
    override = (annotations.get("ops_signals_lookback") or "").strip()
    if override:
        try:
            lookback = parse_duration_seconds(override)
        except ValueError:
            pass
    lookback = min(max(lookback, 3600), 7 * 86400)
    step = max(config.min_step_seconds, config.scrape_interval_seconds, 1)
    if lookback / step > config.max_points:
        step = math.ceil(lookback / config.max_points)
    return QueryWindow(start=end - timedelta(seconds=lookback), end=end, step_seconds=step)
