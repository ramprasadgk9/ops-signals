"""Where metrics are used: Grafana dashboards, Grafana-managed alert rules, and Prometheus/Mimir
alerting and recording rules. Each reader takes the JSON the API returns and lists one
MetricUsage per metric per place that reads it.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from backend.app.config import PrometheusConnectionConfig
from backend.app.metric_usage.promql_metrics import extract_query_metrics

_MIXED = "-- Mixed --"
_EXPRESSION_UIDS = {"__expr__", "-100"}
_NON_VALUE_VARIABLE_TYPES = {"interval", "datasource", "adhoc", "groupby"}
_ALL_VALUES = {"$__all", "All", ""}
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
# The key a panel or rule with no datasource of its own reads: Grafana's default datasource.
DEFAULT_DATASOURCE = ""


@dataclass(frozen=True)
class MetricUsage:
    metric: str
    kind: str  # "dashboard" | "alert_rule" | "recording_rule"
    location: str  # "Production / API Health / Latency p95", "api / HighErrorRate"
    folder: str | None = None
    dashboard_uid: str | None = None
    # The Prometheus connections the query reads; None when that can't be told (a datasource
    # variable, or no datasource list), so any connection counts.
    connections: frozenset[str] | None = None


@dataclass(frozen=True)
class DatasourceIndex:
    types: dict[str, str]  # uid or name -> plugin type
    scopes: dict[str, frozenset[str] | None]  # Prometheus datasource uid or name -> connections it reads
    names: dict[str, str]  # uid or name -> display name


@dataclass(frozen=True)
class UnresolvedQuery:
    location: str
    variables: frozenset[str]


@dataclass
class UsageScan:
    usages: list[MetricUsage] = field(default_factory=list)
    unresolved: list[UnresolvedQuery] = field(default_factory=list)
    name_patterns: list[tuple[str, str]] = field(default_factory=list)  # (regex, location)
    recording_rules: dict[str, frozenset[str]] = field(default_factory=dict)  # produced name -> metrics it reads
    recording_rule_groups: dict[str, set[str]] = field(default_factory=dict)  # produced name -> rule groups defining it
    # Datasources (as queries name them) read by queries that were left out, because they match no
    # Prometheus connection.
    skipped_datasources: set[str] = field(default_factory=set)

    def merge(self, other: UsageScan) -> UsageScan:
        self.usages.extend(other.usages)
        self.unresolved.extend(other.unresolved)
        self.name_patterns.extend(other.name_patterns)
        self.recording_rules.update(other.recording_rules)
        for name, groups in other.recording_rule_groups.items():
            self.recording_rule_groups.setdefault(name, set()).update(groups)
        self.skipped_datasources |= other.skipped_datasources
        return self

    def _add(self, expr: str, location: str, kind: str, *, variables=None, folder=None, dashboard_uid=None, connections=None) -> frozenset[str]:
        found = extract_query_metrics(expr, variables)
        seen = {(usage.metric, usage.location) for usage in self.usages}
        for metric in sorted(found.names):
            if (metric, location) not in seen:
                self.usages.append(MetricUsage(metric, kind, location, folder, dashboard_uid, connections))
        if found.unresolved_variables:
            self.unresolved.append(UnresolvedQuery(location, found.unresolved_variables))
        self.name_patterns.extend((pattern, location) for pattern in sorted(found.name_patterns))
        return found.names


def folder_excluded(folder: str | None, patterns: Iterable[str]) -> bool:
    """Case-insensitive folder-title match with * wildcards: "Scratch", "Test*"."""
    if not folder:
        return False
    return any(fnmatch.fnmatch(folder.lower(), pattern.lower()) for pattern in patterns)


def datasource_scopes(datasources: Iterable[Mapping], connections: Iterable[PrometheusConnectionConfig]) -> DatasourceIndex:
    """Which Prometheus connections each Grafana datasource (`GET /api/datasources`) reads: those
    that name it in grafana_datasources, else those with the same URL. With several connections an
    unmatched datasource reads none Ops Signals can see; with one, it is assumed to be that one,
    since Grafana often reaches the same Prometheus by another host name (prometheus:9090 in Docker)."""
    connections = list(connections)
    types: dict[str, str] = {}
    scopes: dict[str, frozenset[str] | None] = {}
    names: dict[str, str] = {}
    for datasource in datasources:
        keys = [key for key in (datasource.get("uid"), datasource.get("name")) if key]
        ds_type = datasource.get("type")
        for key in keys:
            names[key] = datasource.get("name") or key
            if ds_type:
                types[key] = ds_type
        if not _is_prometheus_type(ds_type):
            continue
        named = {connection.id for connection in connections if set(keys) & set(connection.grafana_datasources)}
        url = _normalized_url(datasource.get("url"))
        same_url = {connection.id for connection in connections if url and _normalized_url(connection.base_url) == url}
        scope: frozenset[str] | None = frozenset(named or same_url)
        if not scope and len(connections) == 1:
            scope = None
        if datasource.get("isDefault"):
            keys.append(DEFAULT_DATASOURCE)
            names[DEFAULT_DATASOURCE] = datasource.get("name") or "the default datasource"
        for key in keys:
            scopes[key] = scope
    return DatasourceIndex(types, scopes, names)


def dashboard_usages(
    payload: Mapping,
    *,
    library_panels: Mapping[str, Mapping] | None = None,
    datasource_types: Mapping[str, str] | None = None,
    datasource_scopes: Mapping[str, frozenset[str] | None] | None = None,
) -> UsageScan:
    """`payload` is the GET /api/dashboards/uid/<uid> response: {"meta": ..., "dashboard": ...}."""
    meta = payload.get("meta") or {}
    dashboard = payload.get("dashboard") or {}
    folder = meta.get("folderTitle") or "General"
    title = dashboard.get("title") or dashboard.get("uid") or "Untitled"
    variables = {
        variable["name"]: _variable_options(variable)
        for variable in (dashboard.get("templating") or {}).get("list") or []
        if variable.get("name") and variable.get("type") not in _NON_VALUE_VARIABLE_TYPES
    }

    scan = UsageScan()
    for panel in walk_panels(dashboard):
        library_uid = (panel.get("libraryPanel") or {}).get("uid")
        if library_uid and library_panels and library_uid in library_panels:
            panel = {**library_panels[library_uid], "title": panel.get("title") or library_panels[library_uid].get("title")}
        panel_title = panel.get("title") or f"Panel {panel.get('id')}"
        location = f"{folder} / {title} / {panel_title}"
        for target in panel.get("targets") or []:
            expr = target.get("expr")
            if not expr or target.get("hide"):
                continue
            datasource = target.get("datasource") or panel.get("datasource")
            if _is_mixed(datasource):
                datasource = target.get("datasource")
            if not _is_prometheus(datasource, datasource_types):
                continue
            key, connections = _scope(datasource, datasource_scopes)
            if connections == frozenset():
                scan.skipped_datasources.add(key)
                continue
            scan._add(expr, location, "dashboard", variables=variables, folder=folder, dashboard_uid=dashboard.get("uid"), connections=connections)
    return scan


def grafana_alert_rule_usages(
    rules: Iterable[Mapping],
    *,
    folder_titles: Mapping[str, str] | None = None,
    datasource_types: Mapping[str, str] | None = None,
    datasource_scopes: Mapping[str, frozenset[str] | None] | None = None,
) -> UsageScan:
    """`rules` is the GET /api/v1/provisioning/alert-rules response."""
    scan = UsageScan()
    for rule in rules:
        folder = (folder_titles or {}).get(rule.get("folderUID") or "", rule.get("folderUID") or "General")
        location = f"{folder} / {rule.get('title') or rule.get('uid')}"
        for query in rule.get("data") or []:
            uid = query.get("datasourceUid")
            expr = (query.get("model") or {}).get("expr")
            if not expr or uid in _EXPRESSION_UIDS:
                continue
            if not _is_prometheus({"uid": uid}, datasource_types):
                continue
            key, connections = _scope({"uid": uid}, datasource_scopes)
            if connections == frozenset():
                scan.skipped_datasources.add(key)
                continue
            scan._add(expr, location, "alert_rule", folder=folder, connections=connections)
    return scan


def prometheus_rule_usages(payload: Mapping, connection_id: str | None = None) -> UsageScan:
    """`payload` is the GET /api/v1/rules response from Prometheus or the Mimir ruler of
    `connection_id`; its rules read that connection only."""
    scan = UsageScan()
    connections = frozenset({connection_id}) if connection_id else None
    for group in (payload.get("data") or {}).get("groups") or []:
        for rule in group.get("rules") or []:
            expr = rule.get("query")
            if not expr:
                continue
            location = f"{group.get('name')} / {rule.get('name')}"
            recording = rule.get("type") == "recording"
            names = scan._add(expr, location, "recording_rule" if recording else "alert_rule", connections=connections)
            if recording and rule.get("name"):
                scan.recording_rules[rule["name"]] = frozenset(names)
                scan.recording_rule_groups.setdefault(rule["name"], set()).add(str(group.get("name")))
    return scan


def walk_panels(dashboard: Mapping) -> Iterable[Mapping]:
    stack = list(dashboard.get("panels") or [])
    for row in dashboard.get("rows") or []:  # pre-5.0 dashboard schema
        stack.extend(row.get("panels") or [])
    while stack:
        panel = stack.pop(0)
        yield panel
        stack[0:0] = panel.get("panels") or []  # collapsed rows hold their panels


def _variable_options(variable: Mapping) -> list[str]:
    values: list[str] = []
    for option in variable.get("options") or []:
        values.extend(_as_list(option.get("value")))
    if not values and variable.get("type") == "custom":
        for item in str(variable.get("query") or "").split(","):
            values.append(item.split(" : ", 1)[-1].strip())  # "label : value" form
    if not values and variable.get("type") in {"constant", "textbox"}:
        values.extend(_as_list(variable.get("query")))
    if not values:
        values.extend(_as_list((variable.get("current") or {}).get("value")))
    return list(dict.fromkeys(value for value in values if value not in _ALL_VALUES))


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)] if value is not None else []


def _is_mixed(datasource: object) -> bool:
    uid = datasource.get("uid") if isinstance(datasource, Mapping) else datasource
    return uid == _MIXED


def _scope(datasource: object, scopes: Mapping[str, frozenset[str] | None] | None) -> tuple[str, frozenset[str] | None]:
    """The datasource key a query reads (uid, name, or DEFAULT_DATASOURCE) and its connections."""
    if isinstance(datasource, Mapping):
        key = str(datasource.get("uid") or "")
    else:
        key = str(datasource or "")
    if key.startswith("$") or key == _MIXED:
        return key, None
    return key, (scopes or {}).get(key)


def _normalized_url(url: object) -> str | None:
    if not url:
        return None
    parts = urlsplit(str(url).strip())
    host = (parts.hostname or "").lower()
    host = "localhost" if host in _LOOPBACK else host
    port = parts.port or {"http": 80, "https": 443}.get(parts.scheme.lower())
    return f"{parts.scheme.lower()}://{host}:{port}{parts.path.rstrip('/')}"


def _is_prometheus_type(ds_type: object) -> bool:
    return ds_type == "prometheus" or str(ds_type or "").endswith("prometheus-datasource")


def _is_prometheus(datasource: object, datasource_types: Mapping[str, str] | None) -> bool:
    """A query with no datasource, a variable one or a mixed one is assumed to be Prometheus,
    unless the datasource lookup says otherwise."""
    lookup = datasource_types or {}
    if isinstance(datasource, str):
        if datasource == _MIXED or datasource.startswith("$"):
            return True
        ds_type = lookup.get(datasource)
    elif isinstance(datasource, Mapping):
        uid = str(datasource.get("uid") or "")
        if uid == _MIXED:
            return True
        ds_type = datasource.get("type")
        if not ds_type or str(ds_type).startswith("$"):
            ds_type = lookup.get(uid)
    else:
        ds_type = None
    return ds_type is None or _is_prometheus_type(ds_type)
