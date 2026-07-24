from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class DatasetConfig:
    csv_path: str
    timestamp_column: str | None = None
    value_column: str | None = None
    label_column: str | None = None
    anomaly_start_column: str | None = None
    anomaly_end_column: str | None = None


@dataclass
class NormalizationConfig:
    method: str = "none"


@dataclass
class RupturesConfig:
    algorithm: str = "pelt"
    model: str = "l2"
    penalty: float = 5.0
    min_size: int = 10
    jump: int = 1


@dataclass
class ExperimentTuningConfig:
    penalties: list[float] = field(default_factory=lambda: [3, 5, 8, 10])
    models: list[str] = field(default_factory=lambda: ["l2", "rbf", "normal"])
    algorithms: list[str] = field(default_factory=lambda: ["pelt", "binseg", "bottomup"])


@dataclass
class OutputConfig:
    plots_dir: str = "experiments/ruptures/plots"
    reports_dir: str = "experiments/ruptures/reports"


@dataclass
class ExperimentConfig:
    dataset: DatasetConfig
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    ruptures: RupturesConfig = field(default_factory=RupturesConfig)
    experiments: ExperimentTuningConfig = field(default_factory=ExperimentTuningConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


def load_config(path: str | Path) -> ExperimentConfig:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return ExperimentConfig(
        dataset=DatasetConfig(**data.get("dataset", {})),
        normalization=NormalizationConfig(**data.get("normalization", {})),
        ruptures=RupturesConfig(**data.get("ruptures", {})),
        experiments=ExperimentTuningConfig(**data.get("experiments", {})),
        output=OutputConfig(**data.get("output", {})),
    )


def as_dict(config: ExperimentConfig) -> dict[str, Any]:
    return {
        "dataset": config.dataset.__dict__,
        "normalization": config.normalization.__dict__,
        "ruptures": config.ruptures.__dict__,
        "experiments": config.experiments.__dict__,
        "output": config.output.__dict__,
    }
