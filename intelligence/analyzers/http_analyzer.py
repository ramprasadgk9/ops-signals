"""Runs an analyzer that lives outside Ops Signals, as an HTTP service.

Each run POSTs the metric window to the service's analyze_url and turns the findings it returns
into OperationalSignals, so they are scored, grouped and shown like any built-in analyzer's.
Nothing is called when the analyzer is constructed, only in analyze(). A service that is down,
slow or answers badly raises HttpAnalyzerError; the pipeline records that analyzer as failed for
the run and carries on with the others. The request and reply format is documented in
docs/http-analyzer-contract.md.
"""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

import pandas as pd

from intelligence.analyzers.base import Analyzer
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal

if TYPE_CHECKING:
    from intelligence.analyzer_registry import HttpAnalyzerSpec

CONTRACT_VERSION = 1
SIGNAL_TYPES = {"anomaly", "baseline_shift", "trend", "forecast", "pattern_discovery"}
SEVERITIES = {"low", "medium", "high"}
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
# Wizard-only settings that describe the service itself; never forwarded as analyzer params.
_INTERNAL_PARAMS = {"external_runtime"}


class HttpAnalyzerError(RuntimeError):
    """The service could not be reached, failed, or replied in a shape Ops Signals can't use."""


class HttpAnalyzer(Analyzer):
    """An analyzer implemented by an external HTTP service (see docs/http-analyzer-contract.md)."""

    # Computes in another process, so it doesn't take series_identity.IN_PROCESS_ANALYZER_LOCK.
    runs_remotely = True

    def __init__(self, analyzer_id: str, spec: HttpAnalyzerSpec, params: dict[str, Any] | None = None, display_name: str | None = None) -> None:
        self._analyzer_id = analyzer_id
        self.spec = spec
        self.display_name = display_name or analyzer_id
        self.params = {key: value for key, value in (params or {}).items() if key not in _INTERNAL_PARAMS}

    @property
    def analyzer_id(self) -> str:
        return self._analyzer_id

    def capability(self) -> Capability:
        return Capability(
            id=f"{self._analyzer_id}_remote",
            title=self.display_name,
            description=f"External analyzer service at {safe_url(self.spec.analyze_url)}.",
            analyzer_id=self._analyzer_id,
            enabled=True,
            supported_question_ids=["unusual_activity", "what_changed"],
        )

    def analyze(self, dataframe: pd.DataFrame) -> list[OperationalSignal]:
        if dataframe.empty:
            return []
        series_keys: list[tuple[Any, Any, Any]] = []
        series_payload: list[dict[str, Any]] = []
        for key, group in dataframe.groupby(["metric_name", "service", "env"], dropna=False, sort=False):
            ordered = group.sort_values("timestamp")
            series_keys.append(tuple(_none_if_missing(part) for part in key))
            series_payload.append(
                {
                    "series_id": str(len(series_payload)),
                    "metric_name": _none_if_missing(key[0]),
                    "service": _none_if_missing(key[1]),
                    "env": _none_if_missing(key[2]),
                    "timestamps": [_iso(ts) for ts in pd.to_datetime(ordered["timestamp"], utc=True)],
                    "values": [_json_number(value) for value in ordered["value"]],
                }
            )

        reply = self._post(
            {
                "contract_version": CONTRACT_VERSION,
                "analyzer_id": self._analyzer_id,
                "params": self.params,
                "series": series_payload,
            }
        )
        findings = reply.get("findings") if isinstance(reply, dict) else None
        if not isinstance(findings, list):
            raise HttpAnalyzerError(f"{self._label()} reply must be a JSON object with a 'findings' list")
        return [self._to_signal(index, finding, series_keys) for index, finding in enumerate(findings)]

    def check_health(self) -> str | None:
        """None when the service answers its health check (or none is configured), else why not."""
        if not self.spec.health_check_url:
            return None
        request = urllib.request.Request(self.spec.health_check_url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=min(self.spec.timeout_seconds, 10.0)):
                return None
        except urllib.error.HTTPError as exc:
            return f"Health check at {safe_url(self.spec.health_check_url)} returned HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return f"Health check could not reach {safe_url(self.spec.health_check_url)}: {_reason(exc)}"

    def _post(self, payload: dict[str, Any]) -> Any:
        request = urllib.request.Request(
            self.spec.analyze_url,
            data=json.dumps(payload, allow_nan=False).encode("utf-8"),
            headers={**self._headers(), "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.spec.timeout_seconds) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise HttpAnalyzerError(f"{self._label()} returned HTTP {exc.code}: {_error_detail(exc)}") from exc
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            if _is_timeout(exc):
                raise HttpAnalyzerError(f"{self._label()} timed out after {self.spec.timeout_seconds:g}s") from exc
            raise HttpAnalyzerError(f"Could not reach {self._label()}: {_reason(exc)}") from exc
        if len(body) > MAX_RESPONSE_BYTES:
            raise HttpAnalyzerError(f"{self._label()} reply is larger than {MAX_RESPONSE_BYTES // (1024 * 1024)} MB")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpAnalyzerError(f"{self._label()} returned invalid JSON: {exc}") from exc

    def _to_signal(self, index: int, finding: Any, series_keys: list[tuple[Any, Any, Any]]) -> OperationalSignal:
        def bad(reason: str) -> HttpAnalyzerError:
            return HttpAnalyzerError(f"{self._label()} finding {index}: {reason}")

        if not isinstance(finding, dict):
            raise bad("must be a JSON object")

        series_id = finding.get("series_id")
        if series_id is None:
            if len(series_keys) != 1:
                raise bad("series_id is required when more than one series is sent")
            series_index = 0
        else:
            series_index = int(series_id) if str(series_id).isdigit() else -1
            if not 0 <= series_index < len(series_keys):
                raise bad(f"series_id '{series_id}' does not match any series that was sent")
        metric_name, service, env = series_keys[series_index]

        start_time = _parse_time(finding.get("start_time"))
        if start_time is None:
            raise bad("start_time is required (ISO 8601)")
        end_time = _parse_time(finding.get("end_time")) if finding.get("end_time") is not None else start_time
        if end_time is None:
            raise bad("end_time must be an ISO 8601 time")

        summary = finding.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise bad("summary is required")

        signal_type = str(finding.get("signal_type", "anomaly"))
        if signal_type not in SIGNAL_TYPES:
            raise bad(f"signal_type '{signal_type}' is not one of {sorted(SIGNAL_TYPES)}")
        severity = str(finding.get("severity", "medium")).lower()
        if severity not in SEVERITIES:
            raise bad(f"severity '{severity}' is not one of {sorted(SEVERITIES)}")
        try:
            confidence = float(finding.get("confidence", 0.5))
        except (TypeError, ValueError):
            raise bad("confidence must be a number between 0 and 1") from None
        if math.isnan(confidence):
            raise bad("confidence must be a number between 0 and 1")

        evidence = finding.get("evidence") or {}
        if not isinstance(evidence, dict):
            raise bad("evidence must be a JSON object")

        return OperationalSignal(
            signal_type=signal_type,
            analyzer_id=self._analyzer_id,
            metric_name=str(metric_name),
            service=service,
            env=env,
            severity=severity,
            confidence=max(0.0, min(1.0, confidence)),
            start_time=start_time,
            end_time=max(start_time, end_time),
            summary=summary.strip(),
            evidence={
                **evidence,
                "library": "http",
                "method": "remote",
                "remote_analyzer_url": safe_url(self.spec.analyze_url),
            },
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        api_key = os.environ.get(self.spec.api_key_env) if self.spec.api_key_env else None
        api_key = api_key or self.spec.api_key
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _label(self) -> str:
        return f"HTTP analyzer '{self._analyzer_id}' at {safe_url(self.spec.analyze_url)}"


def _none_if_missing(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _json_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def _iso(timestamp: pd.Timestamp) -> str:
    return timestamp.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S") + (
        f".{timestamp.microsecond:06d}Z" if timestamp.microsecond else "Z"
    )


def _parse_time(value: Any):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    parsed = parsed.tz_localize("UTC") if parsed.tzinfo is None else parsed.tz_convert("UTC")
    return parsed.to_pydatetime()


def safe_url(url: str) -> str:
    """Drop credentials and query strings, which can carry keys."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def _is_timeout(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    return isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in str(reason)


def _reason(exc: BaseException) -> str:
    return str(getattr(exc, "reason", exc))


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read(2000).decode("utf-8", errors="replace")
    except Exception:
        return str(exc.reason)
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body[:500] or str(exc.reason)
    if isinstance(parsed, dict):
        for key in ("error", "detail", "message"):
            if isinstance(parsed.get(key), str):
                return parsed[key]
            if isinstance(parsed.get(key), dict) and parsed[key].get("message"):
                return str(parsed[key]["message"])
    return body[:500]
