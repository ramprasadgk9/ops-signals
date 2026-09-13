from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from intelligence.config import InputConfig

# pd.read_csv() loads the entire file into memory unconditionally, with no cap - a very large
# CSV (whether from the API upload path or a CLI run pointed at a huge local file) can otherwise
# consume unbounded memory and CPU before analyzers ever run. Configurable since different
# self-hosted deployments will have different comfort levels; default sized generously against
# this app's actual use case (metric time series), not against arbitrary big-data workloads.
MAX_CSV_ROWS = int(os.getenv("OPS_SIGNALS_MAX_CSV_ROWS", "200000"))


class CSVAdapter:
    def __init__(self, config: InputConfig, base_path: Path) -> None:
        self.config = config
        self.base_path = base_path

    def load(self) -> pd.DataFrame:
        csv_path = (self.base_path / self.config.file_path).resolve()
        dataframe = pd.read_csv(csv_path)
        self._validate_row_count(dataframe)
        self._validate_columns(dataframe)
        return dataframe

    def _validate_row_count(self, dataframe: pd.DataFrame) -> None:
        if len(dataframe) > MAX_CSV_ROWS:
            raise ValueError(
                f"CSV has {len(dataframe)} rows, exceeding the configured limit of {MAX_CSV_ROWS} "
                "(set OPS_SIGNALS_MAX_CSV_ROWS to change). Consider splitting the file or narrowing "
                "the time range."
            )

    def _validate_columns(self, dataframe: pd.DataFrame) -> None:
        missing = [column for column in self.config.required_columns if column not in dataframe.columns]
        if missing:
            raise ValueError(f"CSV is missing required columns: {missing}")

        provider = (self.config.provider or "generic").lower()
        if provider not in {"generic", "prometheus", "datadog"}:
            raise ValueError(f"Unsupported input provider: {provider}")
