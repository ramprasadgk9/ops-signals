"""The methods every benchmark suite compares, with one name each, used the same way in every
report. They answer the question reviewers ask most: does picking analyzers per series (the
router) actually help, compared with running everything or with a simple rule?

- Ops Signals, router picks: the product as users get it. The router profiles the series and runs
  its top picks above the score threshold (plus always-run analyzers such as data_health).
- Ops Signals, all analyzers: every enabled analyzer on every series, with the same finding rules
  and ranking. The "run everything" baseline: if routing helps, the router should match it on
  accuracy while running far fewer analyzers.
- Z-score only: just the product's anomaly_zscore analyzer on every series. The classic
  single-method approach.
- Static threshold: an alert line fixed from data known to be normal, with no analyzer at all.
  The most common alerting setup in operations.
"""

from __future__ import annotations

ROUTER_PICKS = "router_picks"
ALL_ANALYZERS = "all_analyzers"
ZSCORE_ONLY = "zscore_only"
STATIC_THRESHOLD = "static_threshold"

ZSCORE_ANALYZERS = ("anomaly_zscore",)

LABELS = {
    ROUTER_PICKS: "Ops Signals, router picks",
    ALL_ANALYZERS: "Ops Signals, all analyzers",
    ZSCORE_ONLY: "Z-score only",
    STATIC_THRESHOLD: "Static threshold",
}

DESCRIPTIONS = {
    ROUTER_PICKS: "The product as users get it: the router chooses which analyzers run on each series.",
    ALL_ANALYZERS: "Every enabled analyzer runs on every series; same finding rules and ranking as the product.",
    ZSCORE_ONLY: "Only the anomaly_zscore analyzer, on every series.",
    STATIC_THRESHOLD: "A fixed alert line learned from data known to be normal; no analyzer.",
}
