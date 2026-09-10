from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


class MockToolEnvironment:
    """Deterministic observability query environment serving telemetry for a scenario.
    
    Provides standard PromQL-like metric inspection, K8s event queries, and service discovery
    tools for agentic ReAct baselines.
    """

    def __init__(self, scenario_dir: str | Path) -> None:
        self.scenario_dir = Path(scenario_dir)
        metrics_csv = self.scenario_dir / "metrics.csv"
        k8s_json = self.scenario_dir / "k8s_events.json"

        if not metrics_csv.exists():
            raise FileNotFoundError(f"Missing scenario metrics at {metrics_csv}")
        if not k8s_json.exists():
            raise FileNotFoundError(f"Missing scenario k8s events at {k8s_json}")

        self.df = pd.read_csv(metrics_csv)
        self.k8s_events = json.loads(k8s_json.read_text(encoding="utf-8"))
        signals_json = self.scenario_dir / "signals.json"
        self.signals: list[dict[str, Any]] = (
            json.loads(signals_json.read_text(encoding="utf-8"))
            if signals_json.exists()
            else []
        )
        self._dispatcher: dict[str, Any] = {
            "list_services": lambda _: self.list_services(),
            "list_metrics": lambda args: self.list_metrics(args.get("service", "")),
            "list_signals": lambda args: self.list_signals(service=args.get("service")),
            "query_prometheus": lambda args: self.query_prometheus(
                query=args.get("query", ""),
                start_time=args.get("start_time"),
                end_time=args.get("end_time"),
                step=args.get("step", "5m"),
            ),
            "query_k8s_events": lambda args: self.query_k8s_events(
                service=args.get("service"),
                event_type=args.get("event_type"),
            ),
        }


    def list_services(self) -> list[str]:
        """Lists all active services discovered in the cluster."""
        return sorted(list(self.df["service"].dropna().unique()))

    def list_metrics(self, service: str) -> list[str]:
        """Lists all available Prometheus metric names recorded for a specific service."""
        service_df = self.df[self.df["service"] == service]
        return sorted(list(service_df["metric_name"].dropna().unique()))

    def list_signals(self, service: str | None = None) -> list[dict[str, Any]]:
        """Lists structured operational signals extracted for services in the scenario."""
        if not service:
            return self.signals
        return [s for s in self.signals if s.get("service") == service]

    @staticmethod
    def _parse_step_seconds(step: str) -> int:
        """Parses Prometheus duration string (e.g. '5m', '30s', '1h') into seconds."""
        match = re.match(r"^(\d+)([smhd])?$", str(step).strip().lower())
        if not match:
            return 300
        val = int(match.group(1))
        unit = match.group(2) or "s"
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        return val * multipliers.get(unit, 1)

    def query_prometheus(
        self,
        query: str,
        start_time: str | None = None,
        end_time: str | None = None,
        step: str = "5m",
    ) -> dict[str, Any]:
        """Executes a PromQL-like query over the scenario metric series.
        
        Supports queries such as:
          - 'memory_usage{service="payment-service"}'
          - 'cpu_throttled_seconds'
          - 'cpu_usage'
        """
        metric_match = re.match(r"^([\w]+)(?:\{([^}]+)\})?", query.strip())
        if not metric_match:
            return {"status": "error", "error": f"Malformed PromQL query: {query}"}

        metric_name = metric_match.group(1)
        filter_str = metric_match.group(2) or ""

        service_filter = None
        if filter_str:
            svc_match = re.search(r"""service=["']([^"']+)["']""", filter_str)
            if svc_match:
                service_filter = svc_match.group(1)

        filtered = self.df[self.df["metric_name"] == metric_name]
        if service_filter:
            filtered = filtered[filtered["service"] == service_filter]

        if filtered.empty:
            return {
                "status": "success",
                "data": {"result_type": "matrix", "result": []},
                "summary": f"No points found for metric '{metric_name}' (filter: {filter_str})",
            }

        if start_time:
            filtered = filtered[filtered["timestamp"] >= start_time]
        if end_time:
            filtered = filtered[filtered["timestamp"] <= end_time]

        values = filtered["value"].tolist()
        timestamps = filtered["timestamp"].tolist()

        # Objective summary statistics without subjective conclusion leakage
        start_val = round(float(values[0]), 2) if values else 0.0
        end_val = round(float(values[-1]), 2) if values else 0.0
        summary_stats = {
            "point_count": len(values),
            "min": round(float(min(values)), 2) if values else 0.0,
            "max": round(float(max(values)), 2) if values else 0.0,
            "mean": round(float(sum(values) / len(values)), 2) if values else 0.0,
            "start_value": start_val,
            "end_value": end_val,
            "delta": round(end_val - start_val, 2),
        }

        # Resample sample points using the requested step interval (e.g. '5m', '1m')
        step_seconds = self._parse_step_seconds(step)
        sample_points: list[dict[str, Any]] = []
        last_dt: datetime | None = None

        for ts_str, val in zip(timestamps, values):
            try:
                dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
            except Exception:
                dt = None

            if dt is not None:
                if last_dt is None or (dt - last_dt).total_seconds() >= step_seconds:
                    sample_points.append({"timestamp": ts_str, "value": round(float(val), 2)})
                    last_dt = dt
            else:
                sample_points.append({"timestamp": ts_str, "value": round(float(val), 2)})

        if not sample_points and values:
            sample_points.append({"timestamp": timestamps[0], "value": round(float(values[0]), 2)})

        return {
            "status": "success",
            "data": {
                "metric": metric_name,
                "service": service_filter or "all",
                "summary": summary_stats,
                "sample_points": sample_points,
            },
        }

    def query_k8s_events(
        self,
        service: str | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Queries Kubernetes event history, optionally filtered by service or event type."""
        events = self.k8s_events
        if service:
            events = [e for e in events if e.get("service") == service]
        if event_type:
            events = [e for e in events if e.get("type", "").lower() == event_type.lower() or e.get("reason", "").lower() == event_type.lower()]
        return events

    def get_tool_definitions(self, include_signals: bool = False) -> list[dict[str, Any]]:
        """Returns standard JSON Schema tool declarations for LLM function calling."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "list_services",
                    "description": "Lists all active services in the Kubernetes cluster.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_metrics",
                    "description": "Lists available Prometheus metric names recorded for a specific service.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service": {"type": "string", "description": "The name of the service, e.g. payment-service"}
                        },
                        "required": ["service"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_prometheus",
                    "description": "Executes a PromQL query to inspect time-series metric trends, min/max values, and sample points.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "PromQL query, e.g. memory_usage{service=\"payment-service\"} or cpu_usage"},
                            "start_time": {"type": "string", "description": "ISO timestamp for window start (optional)"},
                            "end_time": {"type": "string", "description": "ISO timestamp for window end (optional)"},
                            "step": {"type": "string", "description": "Query resolution step, e.g. 5m, 1m, 30s (optional)"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_k8s_events",
                    "description": "Queries Kubernetes cluster events (OOMKilled, CrashLoopBackOff, pod restarts).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service": {"type": "string", "description": "Filter events by service name (optional)"},
                            "event_type": {"type": "string", "description": "Filter by event type or reason, e.g. Warning or OOMKilled (optional)"},
                        },
                        "required": [],
                    },
                },
            },
        ]
        if include_signals:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "list_signals",
                        "description": "Lists structured operational signals extracted by monitoring rules or anomaly detectors for services.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "service": {"type": "string", "description": "Filter signals by service name (optional)"}
                            },
                            "required": [],
                        },
                    },
                }
            )
        return tools

    def get_dispatcher(self) -> dict[str, Any]:
        """Returns the canonical callable dispatcher mapping tool names to environment methods."""
        return self._dispatcher

    def dispatch(self, tool_name: str, tool_input: dict[str, Any] | None = None) -> Any:
        """Safely dispatches a tool call by name, catching unknown tools and execution errors."""
        if tool_input is None:
            tool_input = {}
        dispatcher = self.get_dispatcher()
        handler = dispatcher.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool '{tool_name}'"}
        try:
            return handler(tool_input)
        except Exception as err:
            return {"error": f"Tool execution failed: {err}"}


