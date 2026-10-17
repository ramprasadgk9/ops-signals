"""Stumpy computes with Numba, whose default threading layer aborts the whole process when two
threads use it at once. Analyses run on several threads (API threadpool, scheduler, alerts), so
in-process analyzers take turns; HTTP analyzers compute elsewhere and don't wait."""

from __future__ import annotations

import threading
import time

import pandas as pd

from intelligence.analyzers.http_analyzer import HttpAnalyzer
from intelligence.series_identity import run_analyzer_by_cluster


class _RecordingAnalyzer:
    analyzer_id = "recording"

    def __init__(self, tracker: dict, remote: bool = False) -> None:
        self.tracker = tracker
        self.runs_remotely = remote

    def analyze(self, _frame: pd.DataFrame) -> list:
        with self.tracker["lock"]:
            self.tracker["running"] += 1
            self.tracker["most"] = max(self.tracker["most"], self.tracker["running"])
        time.sleep(0.2)
        with self.tracker["lock"]:
            self.tracker["running"] -= 1
        return []


def _most_at_once(remote: bool) -> int:
    tracker = {"lock": threading.Lock(), "running": 0, "most": 0}
    frame = pd.DataFrame({"timestamp": [], "metric_name": [], "value": []})
    threads = [threading.Thread(target=run_analyzer_by_cluster, args=(_RecordingAnalyzer(tracker, remote), frame)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return tracker["most"]


def test_in_process_analyzers_never_run_at_the_same_time() -> None:
    assert _most_at_once(remote=False) == 1


def test_remote_analyzers_do_not_wait_for_each_other() -> None:
    assert HttpAnalyzer.runs_remotely
    assert _most_at_once(remote=True) > 1
