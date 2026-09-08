from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from benchmark.iam_vs_llm.evaluators.taxonomy import RootCauseClass
from intelligence.findings.schema import OperationalFinding
from intelligence.signals.schema import OperationalSignal


@dataclass(slots=True)
class NormalizedRCA:
    """Normalized representation of a diagnosed root-cause for benchmark evaluation."""
    entity: str | None
    root_cause: RootCauseClass
    fault_window: tuple[datetime, datetime] | None = None
    evidence_keys: list[str] = field(default_factory=list)
    raw_summary: str = ""


def normalize_iam_findings(
    findings: list[OperationalFinding],
    signals: list[OperationalSignal] | None = None,
    behavior_findings: list[Any] | None = None,
) -> NormalizedRCA:
    """Normalizes IAM findings, signals, and behavior findings into a structured NormalizedRCA object.
    
    Acts as a boundary adapter without modifying core IAM finding schemas.
    """
    if not findings and not behavior_findings:
        return NormalizedRCA(
            entity=None,
            root_cause=RootCauseClass.UNKNOWN,
            fault_window=None,
            evidence_keys=[],
            raw_summary="No findings generated",
        )

    # If behavior intelligence emitted causal findings, prioritize them
    top_behavior = behavior_findings[0] if behavior_findings else None

    # Sort findings by importance_score descending
    sorted_findings = sorted(findings, key=lambda f: getattr(f, "importance_score", 0.0), reverse=True)
    top_finding = sorted_findings[0] if sorted_findings else None
    entity = getattr(top_behavior, "service", None) or (top_finding.service if top_finding else None)

    # Collect evidence keys from all findings & signals
    evidence_keys: list[str] = []
    signals_by_id = {s.signal_id: s for s in (signals or [])}

    for f in findings:
        if f.metric_name and f.metric_name not in evidence_keys:
            evidence_keys.append(f.metric_name)
        for sig_id in f.signal_ids:
            sig = signals_by_id.get(sig_id)
            if sig and sig.signal_type and sig.signal_type not in evidence_keys:
                evidence_keys.append(sig.signal_type)

    # Time window resolution from underlying signals
    fault_window: tuple[datetime, datetime] | None = None
    start_times: list[datetime] = []
    end_times: list[datetime] = []

    for sig_id in top_finding.signal_ids:
        sig = signals_by_id.get(sig_id)
        if sig:
            if sig.start_time:
                start_times.append(sig.start_time)
            if sig.end_time:
                end_times.append(sig.end_time)

    if start_times and end_times:
        fault_window = (min(start_times), max(end_times))

    # Infer RootCauseClass from behavior findings, finding category, metric names, and signal types
    category = (((top_behavior.category if top_behavior else None) or (top_finding.category if top_finding else None)) or "").lower()
    title = (((top_behavior.title if top_behavior else None) or (top_finding.title if top_finding else None)) or "").lower()
    summary = ((top_behavior.summary if top_behavior else None) or (top_finding.summary if top_finding else None)) or ""
    metric = (top_finding.metric_name if top_finding else "").lower()

    root_cause = RootCauseClass.UNKNOWN

    # Check for Memory Leak: memory metric/evidence + leak/resource_constraint indicator
    is_memory_metric = any(m in metric for m in ("memory", "mem", "working_set"))
    has_memory_evidence = any("memory" in str(k).lower() for k in evidence_keys)
    has_leak_indicator = any(
        kw in category or kw in title or kw in summary.lower()
        for kw in ("leak", "resource_constraint", "performance", "upward", "trend")
    )
    if "leak" in title or "leak" in summary.lower() or ((is_memory_metric or has_memory_evidence) and has_leak_indicator):
        root_cause = RootCauseClass.MEMORY_LEAK
    elif "throttling" in metric or "cpu_throttling" in category or "cpu" in metric:
        root_cause = RootCauseClass.CPU_STARVATION
    elif "config" in category or "timeout" in category:
        root_cause = RootCauseClass.CONFIG_REGRESSION
    elif "pool" in category or "connection" in category:
        root_cause = RootCauseClass.POOL_EXHAUSTION
    elif "deadlock" in category:
        root_cause = RootCauseClass.DISTRIBUTED_DEADLOCK
    elif "maintenance" in category or "backup" in category:
        root_cause = RootCauseClass.BENIGN_MAINTENANCE

    return NormalizedRCA(
        entity=entity,
        root_cause=root_cause,
        fault_window=fault_window,
        evidence_keys=evidence_keys,
        raw_summary=f"{title}: {summary}",
    )


def normalize_structured_text(text: str) -> NormalizedRCA:
    """Parses a structured text block (such as Baseline A's output tail) via regex."""
    rc_match = re.search(r"ROOT_CAUSE:\s*([A-Z_]+)", text, re.IGNORECASE)
    entity_match = re.search(r"ENTITY:\s*([\w\-]+)", text, re.IGNORECASE)
    window_match = re.search(
        r"WINDOW:\s*([0-9TZ:\-\+]+)\s*(?:to|--)\s*([0-9TZ:\-\+]+)", text, re.IGNORECASE
    )

    root_cause = RootCauseClass.UNKNOWN
    if rc_match:
        val = rc_match.group(1).upper()
        try:
            root_cause = RootCauseClass(val)
        except ValueError:
            root_cause = RootCauseClass.UNKNOWN

    entity = entity_match.group(1) if entity_match else None

    fault_window = None
    if window_match:
        try:
            s_str = window_match.group(1).replace("Z", "+00:00")
            e_str = window_match.group(2).replace("Z", "+00:00")
            fault_window = (datetime.fromisoformat(s_str), datetime.fromisoformat(e_str))
        except Exception:
            fault_window = None

    # Evidence keys can be listed as EVIDENCE: key1, key2
    evidence_match = re.search(r"EVIDENCE:\s*([^\n]+)", text, re.IGNORECASE)
    evidence_keys = []
    if evidence_match:
        evidence_keys = [k.strip() for k in evidence_match.group(1).split(",") if k.strip()]

    return NormalizedRCA(
        entity=entity,
        root_cause=root_cause,
        fault_window=fault_window,
        evidence_keys=evidence_keys,
        raw_summary=text[:500],
    )
