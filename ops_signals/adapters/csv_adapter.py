from __future__ import annotations

from pathlib import Path

import pandas as pd

from ops_signals.config import InputConfig


class CSVAdapter:
    def __init__(self, config: InputConfig, base_path: Path) -> None:
        self.config = config
        self.base_path = base_path

    def load(self) -> pd.DataFrame:
        csv_path = (self.base_path / self.config.file_path).resolve()
        dataframe = pd.read_csv(csv_path)
        self._validate_columns(dataframe)
        return dataframe

    def _validate_columns(self, dataframe: pd.DataFrame) -> None:
        missing = [column for column in self.config.required_columns if column not in dataframe.columns]
        if missing:
            raise ValueError(f"CSV is missing required columns: {missing}")

        provider = (self.config.provider or "generic").lower()
        if provider not in {"generic", "prometheus", "datadog"}:
            raise ValueError(f"Unsupported input provider: {provider}")
