from __future__ import annotations

from benchmark.scorecard import analyzer_scorecard, own_router_scenarios, router_choices


def _ucr_series(number: int, ran: list[str], correct: dict[str, bool]) -> dict:
    return {
        "number": number,
        "name": f"s{number}",
        "methods": {"product": {"executed_analyzers": ran}, "all_analyzers": {"per_analyzer_correct": correct}},
    }


def test_router_right_kind_and_worked_are_judged_case_by_case() -> None:
    ucr = {
        "series": [
            _ucr_series(1, ["pyod_outlier", "trend"], {"pyod_outlier": True}),  # right kind, worked
            _ucr_series(2, ["trend", "stumpy"], {"anomaly_zscore": True}),  # wrong kind, missed a solvable case
            _ucr_series(3, ["anomaly_zscore"], {}),  # right kind; nobody could solve it
        ],
        "summary": {"overall": {}},
    }

    (row,) = router_choices({"ucr": ucr})

    assert (row["right_kind"]["hits"], row["right_kind"]["total"]) == (2, 3)
    assert (row["worked"]["hits"], row["worked"]["total"]) == (1, 2)
    assert row["nobody_could"] == 1
    assert [c["id"] for c in row["misses"]] == ["#2 s2"]
    assert row["right_kind"]["meets_bar"] is False


def test_tcpd_leaves_out_series_where_most_annotators_marked_no_change() -> None:
    def series(name, counts, ran, per, no_change):
        return {"series": name, "annotated_cp_counts": counts, "executed_analyzers": ran,
                "per_analyzer_scores": per, "scores": {"no_change": {"f1": no_change}}}

    tcpd = {"series": [
        series("quiet", [0, 0, 0, 1, 0], ["trend"], {"ruptures": {"f1": 0.2}}, 1.0),
        series("shift", [1, 1, 1, 1, 2], ["ruptures", "trend"], {"ruptures": {"f1": 0.9}, "baseline_shift": {"f1": 0.3}}, 0.4),
    ], "leaderboard": []}

    (row,) = router_choices({"tcpd": tcpd})

    assert row["right_kind"]["total"] == 1 and row["right_kind"]["hits"] == 1
    assert (row["worked"]["hits"], row["worked"]["total"]) == (1, 1)


def test_an_anomaly_detector_is_good_only_when_it_beats_the_static_threshold_on_both_counts() -> None:
    def counts(caught, false):
        return {"caught": caught, "incidents": 10, "false_alerts": false}

    smd = {
        "analyzers": {"pyod_outlier": {"0.5": counts(6, 20)}, "anomaly_zscore": {"0.5": counts(8, 90)}, "seasonal_anomaly": {"0.5": counts(2, 5)}},
        "comparison": {"static_threshold": {"overall": {"0.5": counts(5, 30)}}},
    }

    cards = {row["analyzer"]: row for row in analyzer_scorecard({"smd": smd})}

    assert cards["pyod_outlier"]["cells"]["smd"]["good"] is True
    assert cards["anomaly_zscore"]["cells"]["smd"]["good"] is False  # catches more, but far more false alerts
    assert cards["seasonal_anomaly"]["cells"]["smd"]["good"] is False  # quiet, but catches fewer
    assert cards["ruptures"]["verdict"] == "not graded"


def test_own_router_scenarios_count_only_analyzers_that_can_run() -> None:
    def scenario(required, status):
        return {"expected_router": {"required_recommended": required}, "evaluation": {"status": status}}

    router = {"executable_analyzers": ["ruptures", "stumpy"], "scenarios": [
        scenario(["ruptures"], "PASS"), scenario(["kats"], "PASS"), scenario(["stumpy"], "FAIL")]}

    own = own_router_scenarios({"router": router})

    assert (own["runnable_passed"], own["runnable"], own["total"]) == (1, 2, 3)
    assert own["router_only"] == ["kats"]
