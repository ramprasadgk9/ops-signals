from __future__ import annotations

from pathlib import Path

from intelligence.config import load_config


def test_load_config_merges_shared_analyzers_with_provider_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    providers_dir = config_dir / "providers"
    providers_dir.mkdir(parents=True)

    (config_dir / "config.yaml").write_text(
        """
output:
  save_normalized_data: true
  save_signals: true
  save_embeddings: true
storage:
  postgres:
    host: localhost
    port: 5432
    database: intelligence
    user: intelligence
    password: intelligence
    table_prefix: ops_
embeddings:
  enabled: true
  provider: sentence_transformers
  model: all-MiniLM-L6-v2
ui:
  enabled: true
  default_status: new
  default_page: overview
  show_technical_signals: true
  theme: system
""".strip(),
        encoding="utf-8",
    )

    (config_dir / "analyzers.yaml").write_text(
        """
analysis:
  mode: batch
  window: entire_dataset
  analyzers:
    ruptures:
      enabled: false
    trend:
      enabled: true
      min_slope_percent: 10
    anomaly_zscore:
      enabled: true
      zscore_threshold: 3.0
""".strip(),
        encoding="utf-8",
    )

    (providers_dir / "prometheus.yaml").write_text(
        """
input:
  source_type: csv
  provider: prometheus
  schema_version: v1
  file_path: sample_data/prometheus_cpu_usage_sample.csv
  history: 1d
  interval: 5m
  service: checkout
  metric_name: node_cpu_usage_seconds_total
  timestamp_column: timestamp
  value_column: value
  metric_column: metric_name
  provider_mappings:
    metric_name: metric
    host: instance
  validation:
    enforce_monotonic_timestamp: true
    allow_negative_values: false
    max_gap_minutes: 30
    max_null_ratio: 0.1
  required_columns:
    - timestamp
    - metric
    - value
  optional_columns:
    - service
    - env
    - host
""".strip(),
        encoding="utf-8",
    )

    config = load_config(providers_dir / "prometheus.yaml")

    assert config.analysis.mode == "batch"
    assert config.analysis.window == "entire_dataset"
    assert config.analysis.analyzers["trend"].enabled is True
    assert config.analysis.analyzers["trend"].params["min_slope_percent"] == 10
    assert config.analysis.analyzers["anomaly_zscore"].params["zscore_threshold"] == 3.0
    assert config.input.provider == "prometheus"
    assert config.input.provider_mappings == {"metric_name": "metric", "host": "instance"}
    assert config.input.required_columns == ["timestamp", "metric", "value"]


def test_load_config_keeps_legacy_flat_configs_working() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = load_config(project_root / "config.yaml")

    assert config.analysis.mode == "batch"
    assert "baseline_shift" in config.analysis.analyzers
    assert config.input.provider == "generic"


def test_modular_analyzer_config_supports_nested_baseline_shift_schema() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = load_config(project_root / "config/providers/prometheus.yaml")

    baseline_params = config.analysis.analyzers["baseline_shift"].params
    anomaly_params = config.analysis.analyzers["anomaly_zscore"].params
    pyod_params = config.analysis.analyzers["pyod_outlier"].params
    stumpy_params = config.analysis.analyzers["stumpy"].params
    prophet_params = config.analysis.analyzers["prophet"].params
    trend_params = config.analysis.analyzers["trend"].params
    assert config.analysis.selection_mode == "recommended_threshold"
    assert config.analysis.recommendation_execution.min_score == 0.8
    assert config.analysis.recommendation_execution.max_analyzers == 3
    assert config.analysis.recommendation_execution.include_optional is False
    assert anomaly_params["implementation"] == {
        "library": "pandas",
        "method": "zscore",
        "zscore_threshold": 3.0,
        "grouping_gap": "15m",
    }
    assert anomaly_params["finding_rules"] == {"min_abs_zscore": 3.0, "min_points": 1}
    assert "zscore_threshold" not in anomaly_params
    assert pyod_params["implementation"]["library"] == "pyod"
    assert pyod_params["implementation"]["detector"] == "KNN"
    assert pyod_params["implementation"]["detector_type"] == "knn"
    assert pyod_params["implementation"]["contamination"] == 0.01
    assert pyod_params["implementation"]["grouping_gap"] == "15m"
    assert pyod_params["implementation"]["min_samples"] == 50
    assert "detector_type" not in pyod_params
    assert stumpy_params["finding_rules"]["max_motif_distance"] == 1.0
    assert stumpy_params["finding_rules"]["min_confidence"] == 0.75
    assert stumpy_params["finding_rules"]["min_surprise"] == 8.0
    assert stumpy_params["implementation"] == {
        "library": "stumpy",
        "algorithm": "stump",
        "mode": "discord",
        "max_discords": 3,
        "window_size": 20,
        "motif_count": 1,
        "profile_threshold": 2.0,
    }
    assert prophet_params["finding_rules"]["min_relative_error"] == 0.25
    assert "min_confidence" not in prophet_params["finding_rules"]
    assert prophet_params["implementation"] == {
        "library": "prophet",
        "horizon_points": 10,
        "changepoint_prior_scale": 0.05,
        "uncertainty_threshold": 0.15,
    }
    assert "min_slope_percent" not in trend_params
    assert trend_params["implementation"] == {"library": "statsmodels", "model": "OLS"}
    assert trend_params["finding_rules"]["min_slope_percent"] == 10
    assert baseline_params["ruptures"]["algorithm"] == "binseg"
    assert baseline_params["ruptures"]["model"] == "l2"
    assert baseline_params["ruptures"]["min_size"] == 5
    assert baseline_params["ruptures"]["jump"] == 5
    assert baseline_params["ruptures"]["n_bkps"] == 1
    assert baseline_params["finding_rules"]["min_change_percent"] == 25
    assert baseline_params["finding_rules"]["min_effect_size"] == 1.5
    # finding_rules is the one place for these; the older statistical_gate/operational_significance
    # copies are gone from the shipped file (still read from older configs, finding_rules wins).
    assert "statistical_gate" not in baseline_params
    assert "operational_significance" not in baseline_params
