from __future__ import annotations

import base64
import json
import ssl
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pandas as pd
from fastapi import HTTPException

from backend.app.autonomous.schemas import DiscoveredMetric, MetricDiscoveryResult
from backend.app.config import PrometheusConnectionConfig
from backend.app.models.prometheus import PrometheusPreviewOut, PrometheusSeriesOut, PrometheusSeriesSample
from intelligence.normalize.normalizer import CORE_COLUMNS

# Endpoints the Prometheus HTTP API (and Thanos, Mimir, VictoriaMetrics) also accept as a POST form body.
_POST_CAPABLE_PATHS = {"/api/v1/query", "/api/v1/query_range", "/api/v1/series", "/api/v1/labels"}
# Proxies and gateways in front of large backends can reject long request lines with 414.
_MAX_GET_URL_LENGTH = 2048
_MAX_ERROR_MESSAGE_CHARS = 500
# buildinfo is optional on some Prometheus-compatible backends and gateways; these statuses mean
# "endpoint not served", not "connection broken".
_BUILDINFO_UNSUPPORTED_STATUSES = {400, 404, 405, 501}


@dataclass(frozen=True)
class PrometheusConnectionProfile:
    id: str
    name: str
    base_url: str | None
    configured: bool


def configured_connection(config: PrometheusConnectionConfig) -> PrometheusConnectionProfile:
    return PrometheusConnectionProfile(
        id=config.id,
        name=config.name,
        base_url=config.base_url,
        configured=bool(config.base_url),
    )


def parse_step_seconds(value: str, config: PrometheusConnectionConfig) -> int:
    raw = value.strip().lower()
    if not raw:
        raise HTTPException(status_code=400, detail="step is required")
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if raw[-1] in units:
        number = raw[:-1]
        multiplier = units[raw[-1]]
    else:
        number = raw
        multiplier = 1
    try:
        seconds = int(float(number) * multiplier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="step must be a duration like 30s, 5m, 1h, or seconds") from exc
    if seconds < config.min_step_seconds:
        raise HTTPException(status_code=400, detail=f"step must be at least {config.min_step_seconds} seconds")
    if seconds > config.max_step_seconds:
        raise HTTPException(status_code=400, detail=f"step must be at most {config.max_step_seconds} seconds")
    return seconds


def validate_range(start: datetime, end: datetime, step_seconds: int, config: PrometheusConnectionConfig) -> None:
    start_utc = _to_utc(start)
    end_utc = _to_utc(end)
    if start_utc >= end_utc:
        raise HTTPException(status_code=400, detail="start must be before end")
    window_seconds = (end_utc - start_utc).total_seconds()
    if window_seconds > config.max_window_days * 86400:
        raise HTTPException(status_code=400, detail=f"time window exceeds {config.max_window_days} days")
    expected_points = int(window_seconds / step_seconds) + 1
    if expected_points > config.max_samples_per_series:
        raise HTTPException(status_code=400, detail="requested range and step exceed max samples per series")


class PrometheusQueryService:
    def __init__(self, config: PrometheusConnectionConfig):
        self.config = config

    def test_connection(self) -> tuple[bool, str | None, int | None, str]:
        if not self.config.base_url:
            return False, None, None, "Prometheus is not configured"
        started = time.perf_counter()
        try:
            payload = self._get_json("/api/v1/status/buildinfo", {})
            version = str(payload.get("data", {}).get("version")) if isinstance(payload.get("data"), dict) else None
            latency_ms = int((time.perf_counter() - started) * 1000)
            return True, version, latency_ms, "Connection successful"
        except HTTPException as exc:
            if exc.status_code not in _BUILDINFO_UNSUPPORTED_STATUSES:
                return False, None, int((time.perf_counter() - started) * 1000), str(exc.detail)
        try:
            payload = self._get_json("/api/v1/query", {"query": "vector(1)"})
        except HTTPException as exc:
            return False, None, int((time.perf_counter() - started) * 1000), str(exc.detail)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if payload.get("status") != "success":
            return False, None, latency_ms, str(payload.get("error") or "Prometheus query API check failed")
        return True, None, latency_ms, "Connection successful (server version unavailable)"

    def label_values(
        self,
        label: str,
        matchers: list[str] | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        warnings: list[str] | None = None,
    ) -> list[str]:
        if not self.config.base_url:
            raise HTTPException(status_code=400, detail="Prometheus is not configured. Add OPS_SIGNALS_PROMETHEUS_URL and restart the backend.")
        normalized = label.strip()
        if not normalized:
            raise HTTPException(status_code=400, detail="label is required")
        params: list[tuple[str, object]] = [("match[]", m) for m in matchers or [] if m and m != "{}"]
        params.extend(_time_range_params(start, end))
        payload = self._get_json(f"/api/v1/label/{quote(normalized, safe='')}/values", params)
        if payload.get("status") != "success":
            raise HTTPException(status_code=502, detail=str(payload.get("error") or "Prometheus label lookup failed"))
        if warnings is not None:
            warnings.extend(_response_warnings(payload))
        values = payload.get("data")
        if not isinstance(values, list):
            raise HTTPException(status_code=502, detail="Prometheus label response is malformed")
        return sorted(str(value) for value in values if value is not None)

    @staticmethod
    def _series_sort_key(r: dict[str, str]) -> tuple:
        return (
            str(r.get("__name__", "")),
            str(r.get("service", "")),
            str(r.get("namespace", "")),
            str(r.get("env") or r.get("environment") or ""),
            sorted(r.items()),
        )

    @staticmethod
    def _round_robin_interleave(
        series_by_metric: dict[str, list[dict[str, str]]],
        limit: int,
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        names = sorted(series_by_metric.keys())
        idx = 0
        while len(rows) < limit:
            progress = False
            for name in names:
                metric_series = series_by_metric[name]
                if idx < len(metric_series):
                    rows.append(metric_series[idx])
                    progress = True
                    if len(rows) >= limit:
                        break
            if not progress:
                break
            idx += 1
        return rows

    @staticmethod
    def _build_metric_matchers(metric_names: list[str], scope_selector: str = "") -> list[str]:
        if not scope_selector or scope_selector == "{}":
            return [f'{{__name__="{name}"}}' for name in metric_names]
        selector = scope_selector.strip()
        inner = selector[1:-1].strip() if selector.startswith("{") and selector.endswith("}") else selector
        if inner:
            return [f'{{{inner},__name__="{name}"}}' for name in metric_names]
        return [f'{{__name__="{name}"}}' for name in metric_names]

    def direct_scoped_series(
        self,
        scope_selector: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        warnings: list[str] | None = None,
    ) -> list[dict[str, str]]:
        if not scope_selector or scope_selector == "{}":
            return []
        payload = self._get_json("/api/v1/series", [("match[]", scope_selector), *_time_range_params(start, end)])
        if warnings is not None:
            warnings.extend(_response_warnings(payload))
        data = payload.get("data")
        rows: list[dict[str, str]] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    rows.append({str(key): str(value) for key, value in item.items()})
        rows.sort(key=self._series_sort_key)
        return rows

    def discover_metric_metadata(
        self,
        *,
        service_label: str = "service",
        namespace_label: str = "namespace",
        environment_label: str = "env",
        limit: int = 5000,
        scope_selector: str = "",
        max_series_per_metric: int = 10,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> MetricDiscoveryResult:
        if not self.config.base_url:
            raise HTTPException(status_code=400, detail="Prometheus is not configured. Add OPS_SIGNALS_PROMETHEUS_URL and restart the backend.")

        effective_limit = max(1, min(limit, 50000))
        warnings: list[str] = []

        # 1. Fast Path for Scoped Policies (Single-Call Pushdown)
        if scope_selector and scope_selector != "{}":
            try:
                direct_rows = self.direct_scoped_series(scope_selector, start=start, end=end, warnings=warnings)
            except HTTPException:
                direct_rows = None

            if direct_rows is not None:
                if not direct_rows:
                    return MetricDiscoveryResult(
                        metrics=[],
                        series_available=0,
                        series_discovered=0,
                        truncated=False,
                        starved_metrics=[],
                        warnings=_unique(warnings),
                    )
                metric_names = sorted({row.get("__name__") for row in direct_rows if row.get("__name__")})
                metadata_by_name = self.metric_metadata(metric_names)
                filtered_rows = self._sample_distinct_series(direct_rows, max_per_metric=max_series_per_metric, limit=effective_limit)
                discovered = self._rows_to_discovered_metrics(
                    filtered_rows,
                    metadata_by_name=metadata_by_name,
                    service_label=service_label,
                    namespace_label=namespace_label,
                    environment_label=environment_label,
                )
                sampled_names = {row.get("__name__") for row in filtered_rows if row.get("__name__")}
                starved_metrics = [name for name in metric_names if name not in sampled_names]
                series_available = len(direct_rows)
                truncated = series_available > len(filtered_rows) or len(starved_metrics) > 0
                return MetricDiscoveryResult(
                    metrics=discovered,
                    series_available=series_available,
                    series_discovered=len(filtered_rows),
                    truncated=truncated,
                    starved_metrics=starved_metrics,
                    warnings=_unique(warnings),
                )

        # 2. Breadth-First Dynamic Quota for Unscoped Policies (Cluster-Wide)
        matchers = [scope_selector] if scope_selector and scope_selector != "{}" else None
        metric_names = self.label_values("__name__", matchers=matchers, start=start, end=end, warnings=warnings)
        if not metric_names:
            return MetricDiscoveryResult(
                metrics=[],
                series_available=0,
                series_discovered=0,
                truncated=False,
                starved_metrics=[],
                warnings=_unique(warnings),
            )

        metadata_by_name = self.metric_metadata(metric_names)
        series_rows, starved_metrics, total_available = self.series_metadata(
            metric_names,
            limit=effective_limit,
            scope_selector=scope_selector,
            max_series_per_metric=max_series_per_metric,
            start=start,
            end=end,
            warnings=warnings,
        )

        if not series_rows:
            fallback_metrics = [
                DiscoveredMetric(
                    metric_name=name,
                    labels={"__name__": name},
                    metric_type=metadata_by_name.get(name),
                    source="prometheus",
                    cardinality_estimate=1,
                )
                for name in metric_names
            ]
            return MetricDiscoveryResult(
                metrics=fallback_metrics,
                series_available=0,
                series_discovered=len(fallback_metrics),
                truncated=False,
                starved_metrics=[],
                warnings=_unique(warnings),
            )

        discovered = self._rows_to_discovered_metrics(
            series_rows,
            metadata_by_name=metadata_by_name,
            service_label=service_label,
            namespace_label=namespace_label,
            environment_label=environment_label,
        )
        truncated = len(starved_metrics) > 0 or len(series_rows) >= effective_limit
        return MetricDiscoveryResult(
            metrics=discovered,
            series_available=total_available,
            series_discovered=len(series_rows),
            truncated=truncated,
            starved_metrics=starved_metrics,
            warnings=_unique(warnings),
        )

    @classmethod
    def _sample_distinct_series(
        cls,
        rows: list[dict[str, str]],
        max_per_metric: int = 10,
        limit: int = 5000,
    ) -> list[dict[str, str]]:
        sorted_rows = sorted(rows, key=cls._series_sort_key)
        by_metric: dict[str, list[dict[str, str]]] = defaultdict(list)

        for row in sorted_rows:
            name = row.get("__name__", "")
            if not name:
                continue
            if len(by_metric[name]) >= max_per_metric:
                continue
            by_metric[name].append(row)

        return cls._round_robin_interleave(by_metric, limit=limit)

    @staticmethod
    def _rows_to_discovered_metrics(
        rows: list[dict[str, str]],
        *,
        metadata_by_name: dict[str, str | None],
        service_label: str,
        namespace_label: str,
        environment_label: str,
    ) -> list[DiscoveredMetric]:
        discovered: list[DiscoveredMetric] = []
        for labels in rows:
            metric_name = labels.get("__name__")
            if not metric_name:
                continue
            service = labels.get(service_label)
            namespace = labels.get(namespace_label)
            environment = labels.get(environment_label) or labels.get("environment")
            discovered.append(
                DiscoveredMetric(
                    metric_name=metric_name,
                    labels=labels,
                    service=service,
                    namespace=namespace,
                    environment=environment,
                    services=[service] if service else [],
                    namespaces=[namespace] if namespace else [],
                    environments=[environment] if environment else [],
                    metric_type=metadata_by_name.get(metric_name),
                    source="prometheus",
                    estimated_series_count=1,
                    cardinality_estimate=1,
                )
            )
        return discovered

    def metric_metadata(self, metric_names: list[str]) -> dict[str, str | None]:
        metadata: dict[str, str | None] = {}
        try:
            payload = self._get_json("/api/v1/metadata", {})
        except HTTPException:
            return metadata
        data = payload.get("data")
        if not isinstance(data, dict):
            return metadata
        wanted = set(metric_names)
        for metric_name, entries in data.items():
            if metric_name not in wanted or not isinstance(entries, list) or not entries:
                continue
            first = entries[0]
            metadata[str(metric_name)] = str(first.get("type")) if isinstance(first, dict) and first.get("type") else None
        return metadata

    def series_metadata(
        self,
        metric_names: list[str],
        limit: int = 5000,
        scope_selector: str = "",
        max_series_per_metric: int = 10,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        warnings: list[str] | None = None,
    ) -> tuple[list[dict[str, str]], list[str], int]:
        if not metric_names:
            return [], [], 0
        chunk_size = 80
        quota = max(1, min(max_series_per_metric, max(1, limit // max(1, len(metric_names)))))
        series_by_metric: dict[str, list[dict[str, str]]] = defaultdict(list)
        total_available = 0

        for offset in range(0, len(metric_names), chunk_size):
            chunk = metric_names[offset : offset + chunk_size]
            matchers = self._build_metric_matchers(chunk, scope_selector=scope_selector)
            params = [*(("match[]", matcher) for matcher in matchers), *_time_range_params(start, end)]
            payload = self._get_json("/api/v1/series", params)
            if warnings is not None:
                warnings.extend(_response_warnings(payload))
            data = payload.get("data")
            if isinstance(data, list):
                total_available += len(data)
                sorted_chunk = sorted(
                    (item for item in data if isinstance(item, dict)),
                    key=self._series_sort_key,
                )
                for item in sorted_chunk:
                    name = str(item.get("__name__", ""))
                    if not name:
                        continue
                    if len(series_by_metric[name]) >= quota:
                        continue
                    series_by_metric[name].append({str(key): str(value) for key, value in item.items()})

            current_total = sum(len(items) for items in series_by_metric.values())
            if current_total >= limit:
                break

        rows = self._round_robin_interleave(series_by_metric, limit=limit)
        discovered_names = {row.get("__name__") for row in rows if row.get("__name__")}
        starved_metrics = [name for name in metric_names if name not in discovered_names]
        return rows, starved_metrics, total_available

    def preview(self, query: str, start: datetime, end: datetime, step: str) -> PrometheusPreviewOut:
        if not self.config.base_url:
            raise HTTPException(status_code=400, detail="Prometheus is not configured. Add OPS_SIGNALS_PROMETHEUS_URL and restart the backend.")
        step_seconds = parse_step_seconds(step, self.config)
        validate_range(start, end, step_seconds, self.config)

        payload = self._get_json(
            "/api/v1/query_range",
            {
                "query": query.strip(),
                "start": _to_utc(start).timestamp(),
                "end": _to_utc(end).timestamp(),
                "step": step_seconds,
            },
        )
        if payload.get("status") != "success":
            raise HTTPException(status_code=502, detail=str(payload.get("error") or "Prometheus query failed"))
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("resultType") != "matrix":
            raise HTTPException(status_code=400, detail="Prometheus response must be a matrix range-vector result")
        result = data.get("result")
        if not isinstance(result, list):
            raise HTTPException(status_code=502, detail="Prometheus response is malformed")
        parsed = self._parse_matrix(query, start, end, step, step_seconds, result)
        parsed.warnings = [*_response_warnings(payload), *parsed.warnings]
        return parsed

    def _parse_matrix(
        self,
        query: str,
        start: datetime,
        end: datetime,
        step: str,
        step_seconds: int,
        result: list[object],
    ) -> PrometheusPreviewOut:
        if len(result) > self.config.max_series:
            raise HTTPException(status_code=400, detail=f"query returned {len(result)} series, which exceeds max_series {self.config.max_series}")

        series_items: list[PrometheusSeriesOut] = []
        warnings: list[str] = []
        total_samples = 0
        for item in result:
            if not isinstance(item, dict):
                raise HTTPException(status_code=502, detail="Prometheus response is malformed")
            metric = item.get("metric") or {}
            values = item.get("values") or []
            if not isinstance(metric, dict) or not isinstance(values, list):
                raise HTTPException(status_code=502, detail="Prometheus response is malformed")
            if len(values) > self.config.max_samples_per_series:
                raise HTTPException(status_code=400, detail="series exceeds max samples per series")
            samples: list[PrometheusSeriesSample] = []
            for value in values:
                if not isinstance(value, list) or len(value) != 2:
                    raise HTTPException(status_code=502, detail="Prometheus sample is malformed")
                try:
                    timestamp = datetime.fromtimestamp(float(value[0]), tz=timezone.utc)
                    sample_value = float(value[1])
                except (TypeError, ValueError) as exc:
                    raise HTTPException(status_code=400, detail="Prometheus returned a non-numeric sample value") from exc
                samples.append(PrometheusSeriesSample(timestamp=timestamp, value=sample_value))
            total_samples += len(samples)
            if total_samples > self.config.max_total_samples:
                raise HTTPException(status_code=400, detail=f"query exceeds max total samples {self.config.max_total_samples}")
            labels = {str(key): str(label_value) for key, label_value in metric.items()}
            series_items.append(PrometheusSeriesOut(labels=labels, samples=samples))

        if not series_items or total_samples == 0:
            warnings.append("The query succeeded, but Prometheus returned no samples for the selected time range.")

        return PrometheusPreviewOut(
            query=query,
            start=_to_utc(start),
            end=_to_utc(end),
            step=step,
            step_seconds=step_seconds,
            series_count=len(series_items),
            sample_count=total_samples,
            series=series_items,
            warnings=warnings,
        )

    def _get_json(self, path: str, params: dict[str, object] | list[tuple[str, object]]) -> dict:
        assert self.config.base_url is not None
        url = f"{self.config.base_url}{path}"
        query = urlencode(params, doseq=True) if params else ""
        headers = self._headers()
        data = None
        if query and path in _POST_CAPABLE_PATHS and len(url) + 1 + len(query) > _MAX_GET_URL_LENGTH:
            data = query.encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif query:
            url = f"{url}?{query}"
        request = Request(url, data=data, headers=headers, method="GET" if data is None else "POST")
        context = None if self.config.verify_tls else ssl._create_unverified_context()
        try:
            with urlopen(request, timeout=self.config.timeout_seconds, context=context) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            raise HTTPException(status_code=exc.code, detail=_http_error_detail(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="Prometheus request timed out") from exc
        except URLError as exc:
            raise HTTPException(status_code=503, detail="Prometheus connection failed") from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail="Prometheus returned malformed JSON") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=502, detail="Prometheus returned malformed JSON")
        return parsed

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", **self.config.headers}
        if self.config.bearer_token:
            headers["Authorization"] = f"Bearer {self.config.bearer_token}"
        elif self.config.username is not None and self.config.password is not None:
            raw = f"{self.config.username}:{self.config.password}".encode("utf-8")
            headers["Authorization"] = f"Basic {base64.b64encode(raw).decode('ascii')}"
        return headers


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _http_error_detail(exc: HTTPError) -> str:
    """Keep the backend's own explanation (e.g. a Mimir or Thanos series limit) instead of only the status code."""
    detail = f"Prometheus HTTP error: {exc.code}"
    try:
        body = exc.read().decode("utf-8", errors="replace").strip() if exc.fp else ""
    except OSError:
        return detail
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and parsed.get("error"):
        message = str(parsed["error"])
    elif body and not body.startswith("<"):
        message = body
    else:
        return detail
    return f"{detail}: {message[:_MAX_ERROR_MESSAGE_CHARS]}"


def _response_warnings(payload: dict) -> list[str]:
    """Warnings a successful response carries, e.g. partial data when a Thanos store is unreachable."""
    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        return []
    return [f"Prometheus warning: {warning}" for warning in warnings if isinstance(warning, str) and warning]


def _time_range_params(start: datetime | None, end: datetime | None) -> list[tuple[str, object]]:
    params: list[tuple[str, object]] = []
    if start is not None:
        params.append(("start", _to_utc(start).timestamp()))
    if end is not None:
        params.append(("end", _to_utc(end).timestamp()))
    return params


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_interval(seconds: int) -> str:
    if seconds >= 60 and seconds % 60 == 0:
        return f"{max(int(seconds / 60), 1)}m"
    return f"{max(seconds, 1)}s"


def _observed_interval(samples: list[object], fallback_seconds: int) -> str:
    timestamps = sorted(
        sample.timestamp
        for sample in samples
        if isinstance(getattr(sample, "timestamp", None), datetime)
    )
    if len(timestamps) < 2:
        return _format_interval(fallback_seconds)

    diffs = sorted(
        int((timestamps[index] - timestamps[index - 1]).total_seconds())
        for index in range(1, len(timestamps))
        if (timestamps[index] - timestamps[index - 1]).total_seconds() > 0
    )
    if not diffs:
        return _format_interval(fallback_seconds)

    return _format_interval(diffs[len(diffs) // 2])


def _prometheus_series_to_normalized(
    *,
    samples: list[object],
    labels: dict[str, str],
    service: str,
    metric: str,
) -> pd.DataFrame:
    rows = []
    metric_name = labels.get("__name__") or metric
    service_name = labels.get("service") or labels.get("service_name") or labels.get("job") or labels.get("app") or service
    for sample in samples:
        rows.append(
            {
                "metric_name": metric_name,
                "timestamp": sample.timestamp,
                "value": sample.value,
                "service": service_name,
                "env": labels.get("env") or labels.get("environment"),
                "host": labels.get("instance"),
                "namespace": labels.get("namespace"),
                "pod": labels.get("pod"),
                "source": "prometheus",
                "unit": None,
                "metric_type": None,
                "tags_json": {key: value for key, value in labels.items() if key != "__name__"},
            }
        )
    normalized = pd.DataFrame.from_records(rows)
    for column in CORE_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = None
    if "tags_json" not in normalized.columns:
        normalized["tags_json"] = [{} for _ in range(len(normalized))]
    return normalized[[*CORE_COLUMNS, "tags_json"]].sort_values("timestamp").reset_index(drop=True)
