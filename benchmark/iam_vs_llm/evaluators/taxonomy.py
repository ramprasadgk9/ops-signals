from __future__ import annotations

from enum import Enum


class RootCauseClass(str, Enum):
    """Canonical root-cause fault classes for the IAM vs. LLM benchmark.

    Kept within the benchmark evaluation package to avoid coupling production schemas
    or requiring migrations on operational findings tables.
    """
    MEMORY_LEAK = "MEMORY_LEAK"
    CPU_STARVATION = "CPU_STARVATION"
    CONFIG_REGRESSION = "CONFIG_REGRESSION"
    POOL_EXHAUSTION = "POOL_EXHAUSTION"
    DISTRIBUTED_DEADLOCK = "DISTRIBUTED_DEADLOCK"
    BENIGN_MAINTENANCE = "BENIGN_MAINTENANCE"
    UNKNOWN = "UNKNOWN"
