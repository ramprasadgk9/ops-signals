from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal


class Analyzer(ABC):
    @property
    @abstractmethod
    def analyzer_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def capability(self) -> Capability:
        raise NotImplementedError

    @abstractmethod
    def analyze(self, dataframe: pd.DataFrame) -> list[OperationalSignal]:
        raise NotImplementedError
