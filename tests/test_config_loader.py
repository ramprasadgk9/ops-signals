from __future__ import annotations

from pathlib import Path

from ops_signals.config import load_config


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
    database: ops_signals
    user: ops_signals
    password: ops_signals
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
