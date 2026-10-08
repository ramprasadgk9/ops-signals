"""Which metrics a dashboard or alert query reads.

Builds on the alert scanner's `metric_names` and adds what Grafana queries need on top: dashboard
variables (`$metric`, `${metric}`, `[[metric]]`) and `{__name__="x"}` selectors. Like that scanner,
this is deliberately not a full PromQL parser - a query it can't read just yields fewer names.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from backend.app.alerts.query_builder import metric_names

_VARIABLE = re.compile(r"\$\{(\w+)(?:[:.][^}]*)?\}|\$(\w+)|\[\[(\w+)(?::\w+)?\]\]")
_NAME_MATCHER = re.compile(r"""__name__\s*(=~|=)\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|`([^`]*)`)""")
_PLAIN_NAMES = re.compile(r"^[a-zA-Z_:][\w:]*(?:\|[a-zA-Z_:][\w:]*)*$")
# Stands in for a variable with no known options, so a name that comes out of it is recognisable.
_PLACEHOLDER = "__ops_signals_var_{}__"
_PLACEHOLDER_NAME = re.compile(r"^__ops_signals_var_(\w+?)__$")
# Grafana's own variables ($__rate_interval, $__range_s, ...) are all intervals or numbers.
_BUILTIN_VALUE = "5m"
_MAX_VARIANTS = 200


@dataclass(frozen=True)
class QueryMetrics:
    names: frozenset[str]
    # Variables used where a metric name goes, with no options to expand them to.
    unresolved_variables: frozenset[str] = frozenset()
    # `{__name__=~"node_.*"}` regexes that aren't a plain `a|b` list of names.
    name_patterns: frozenset[str] = frozenset()


def extract_query_metrics(expr: str, variables: Mapping[str, Sequence[str]] | None = None) -> QueryMetrics:
    variables = variables or {}
    refs = list(dict.fromkeys(_variable_name(match) for match in _VARIABLE.finditer(expr)))
    refs = [name for name in refs if not name.startswith("__")]

    base = {name: (variables.get(name) or [_PLACEHOLDER.format(name)])[0] for name in refs}
    variants = [base]
    for name in refs:
        for value in list(variables.get(name) or [])[1:]:
            variants.append({**base, name: value})
    variants = variants[:_MAX_VARIANTS]

    names: set[str] = set()
    patterns: set[str] = set()
    for values in variants:
        rendered = _VARIABLE.sub(lambda match: _render(match, values), expr)
        names.update(metric_names(rendered))
        for op, *quoted in _NAME_MATCHER.findall(rendered):
            value = next((part for part in quoted if part), "")
            if op == "=":
                names.add(value)
            elif _PLAIN_NAMES.match(value):
                names.update(value.split("|"))
            elif value:
                patterns.add(value)

    unresolved = {match.group(1) for name in names if (match := _PLACEHOLDER_NAME.match(name))}
    resolved = {name for name in names if not _PLACEHOLDER_NAME.match(name)}
    return QueryMetrics(frozenset(resolved), frozenset(unresolved), frozenset(patterns))


def _variable_name(match: re.Match[str]) -> str:
    return next(group for group in match.groups() if group)


def _render(match: re.Match[str], values: Mapping[str, str]) -> str:
    name = _variable_name(match)
    if name.startswith("__"):
        return _BUILTIN_VALUE
    return values.get(name, match.group(0))
