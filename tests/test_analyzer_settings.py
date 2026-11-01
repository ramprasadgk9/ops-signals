"""Settings in use (backend/app/services/analyzer_settings.py): each analyzer setting's value and the
file it comes from, and whether a run uses the analyzer. Each test builds its own config folder from
the real built-in registrations, so it never reads or changes config/ itself."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.analyzer_settings import router
from backend.app.services import analyzer_settings
from backend.app.services.analyzer_settings import settings_in_use

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"
# The router's own picks, so these tests don't depend on its catalog file.
ROUTER_IDS = {"ruptures", "pyod_outlier", "trend", "prophet", "stumpy"}


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    shutil.copytree(REPO_CONFIG / "analyzer_registry.d", tmp_path / "analyzer_registry.d")
    (tmp_path / "providers").mkdir()
    (tmp_path / "analyzer_overrides.d").mkdir()
    return tmp_path


def write(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def site(config_dir: Path, analyzers: dict | None = None, **analysis) -> None:
    write(config_dir / "analyzers.yaml", {"analysis": {"selection_mode": "recommended_threshold", **analysis, "analyzers": analyzers or {}}})


def resolve(config_dir: Path, **kwargs) -> dict:
    return settings_in_use(config_dir=config_dir, router_ids=ROUTER_IDS, **kwargs)


def analyzer(result: dict, analyzer_id: str) -> dict:
    return next(item for item in result["analyzers"] if item["analyzer_id"] == analyzer_id)


def setting(result: dict, analyzer_id: str, path: str) -> dict:
    return next(item for item in analyzer(result, analyzer_id)["settings"] if item["path"] == path)


def test_without_any_changes_every_value_is_the_built_in_default(config_dir: Path) -> None:
    site(config_dir)
    result = resolve(config_dir)
    slope = setting(result, "trend", "finding_rules.min_slope_percent")
    assert slope["value"] == 10 and slope["default"] == 10 and not slope["changed"]
    assert slope["source"] == {"layer": "default", "file": "config/analyzer_registry.d/builtin.yml"}
    assert slope["per_service"] and slope["label"]
    assert all(item["changed_count"] == 0 for item in result["analyzers"])
    assert [layer["key"] for layer in result["layers"]] == ["default", "site", "provider", "override"]


def test_a_value_repeated_in_analyzers_yaml_is_not_a_change(config_dir: Path) -> None:
    site(config_dir, {"trend": {"finding_rules": {"min_slope_percent": 10}}})
    result = resolve(config_dir)
    slope = setting(result, "trend", "finding_rules.min_slope_percent")
    assert slope["source"]["layer"] == "site" and not slope["changed"]
    assert result["layers"][1]["changed"] == 0


def test_analyzers_yaml_changes_only_the_keys_it_sets(config_dir: Path) -> None:
    site(config_dir, {"trend": {"finding_rules": {"min_slope_percent": 5}}})
    result = resolve(config_dir)
    slope = setting(result, "trend", "finding_rules.min_slope_percent")
    assert (slope["value"], slope["default"], slope["changed"]) == (5, 10, True)
    assert slope["source"] == {"layer": "site", "file": "config/analyzers.yaml"}
    assert setting(result, "trend", "implementation.model")["source"]["layer"] == "default"
    assert result["layers"][1]["changed"] == 1
    assert analyzer(result, "trend")["changed_count"] == 1


def test_the_data_source_file_wins_over_analyzers_yaml(config_dir: Path) -> None:
    site(config_dir, {"trend": {"finding_rules": {"min_slope_percent": 5}}})
    write(config_dir / "providers" / "otel.yaml", {"analysis": {"analyzers": {"trend": {"finding_rules": {"min_slope_percent": 7}}}}})
    assert setting(resolve(config_dir), "trend", "finding_rules.min_slope_percent")["value"] == 5
    otlp = resolve(config_dir, provider="otel")
    slope = setting(otlp, "trend", "finding_rules.min_slope_percent")
    assert slope["value"] == 7 and slope["source"]["file"] == "config/providers/otel.yaml"
    assert otlp["provider_label"] == "OTLP"


def test_an_unknown_data_source_is_refused(config_dir: Path) -> None:
    with pytest.raises(ValueError):
        resolve(config_dir, provider="nope")


def test_legacy_flat_and_block_names_show_as_the_path_people_write(config_dir: Path) -> None:
    site(config_dir, {"baseline_shift": {"threshold_percent": 30, "finding_rules": {"min_change_percent": 40}}})
    result = resolve(config_dir)
    change = setting(result, "baseline_shift", "finding_rules.min_change_percent")
    # The block path wins over the flat name, as _baseline_shift_params reads it.
    assert (change["value"], change["default"]) == (40, 25.0)
    paths = {item["path"] for item in analyzer(result, "baseline_shift")["settings"]}
    assert "threshold_percent" not in paths and "ruptures.min_size" in paths


def test_a_top_level_copy_of_an_implementation_setting_is_hidden(config_dir: Path) -> None:
    site(config_dir)
    paths = {item["path"] for item in analyzer(resolve(config_dir), "anomaly_zscore")["settings"]}
    assert "implementation.zscore_threshold" in paths and "zscore_threshold" not in paths


def test_a_teams_override_applies_only_to_its_services(config_dir: Path) -> None:
    site(config_dir)
    write(
        config_dir / "analyzer_overrides.d" / "payments-team.yml",
        {
            "overrides": {
                "payments_service_wide": {
                    "scope": {"service": "payments-api"},
                    "reason": "Bursty by design.",
                    "analyzers": {"pyod_outlier": {"finding_rule": {"min_range_excess": 1.0}}},
                    "selection": {"disabled": ["stumpy"]},
                },
                "payments_memory": {
                    "scope": {"service": "payments-api", "metric": "process_resident_memory_bytes"},
                    "reason": "Memory grows slowly before an outage.",
                    "analyzers": {"pyod_outlier": {"finding_rule": {"min_range_excess": 0.6}}, "trend": {"finding_rules": {"min_slope_percent": 5}}},
                    "selection": {"max_analyzers": 2},
                },
            }
        },
    )
    site_wide = resolve(config_dir)
    assert setting(site_wide, "trend", "finding_rules.min_slope_percent")["value"] == 10
    assert analyzer(site_wide, "stumpy")["run"]["status"] == "every_metric"
    assert site_wide["layers"][3]["overrides"] == 2 and site_wide["layers"][3]["files"] == 1
    assert {scope["override_id"] for scope in site_wide["scopes"]} == {"payments_service_wide", "payments_memory"}

    service = resolve(config_dir, service="payments-api")
    assert setting(service, "pyod_outlier", "finding_rule.min_range_excess")["value"] == 1.0
    assert setting(service, "trend", "finding_rules.min_slope_percent")["value"] == 10
    assert analyzer(service, "stumpy")["run"]["status"] == "turned_off"
    assert service["layers"][3]["applied"] == ["payments_service_wide"]

    memory = resolve(config_dir, service="payments-api", metric="process_resident_memory_bytes")
    excess = setting(memory, "pyod_outlier", "finding_rule.min_range_excess")
    # The service-and-metric override wins over the service-wide one.
    assert excess["value"] == 0.6
    assert excess["source"] == {
        "layer": "override",
        "file": "config/analyzer_overrides.d/payments-team.yml",
        "override_id": "payments_memory",
        "reason": "Memory grows slowly before an outage.",
    }
    assert memory["selection"]["max_analyzers"] == 2
    assert memory["selection"]["max_analyzers_source"]["override_id"] == "payments_memory"


def test_a_broken_override_file_is_reported_not_applied(config_dir: Path) -> None:
    site(config_dir)
    (config_dir / "analyzer_overrides.d" / "broken.yml").write_text("overrides: [not, a, mapping]\n", encoding="utf-8")
    result = resolve(config_dir, service="payments-api")
    assert result["layers"][3]["errors"][0]["file"] == "broken.yml"
    assert result["layers"][3]["applied"] == []


def test_run_status_follows_how_a_run_picks_analyzers(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analyzer_settings, "library_installed", lambda name: name != "prophet")
    site(config_dir, {"ruptures": {"enabled": False}})
    result = resolve(config_dir)
    status = {item["analyzer_id"]: item["run"]["status"] for item in result["analyzers"]}
    assert status["stumpy"] == "every_metric" and status["data_health"] == "every_metric"
    assert status["trend"] == "router" and status["pyod_outlier"] == "router"
    assert status["anomaly_zscore"] == "only_if_chosen" and status["seasonal_anomaly"] == "only_if_chosen"
    assert status["ruptures"] == "turned_off"
    assert status["prophet"] == "cant_run"
    assert "PyOD" in analyzer(result, "anomaly_zscore")["run"]["note"]

    site(config_dir, selected_analyzers=["anomaly_zscore"], selection_mode="manual_override")
    assert analyzer(resolve(config_dir), "anomaly_zscore")["run"]["status"] == "every_metric"

    site(config_dir, selection_mode="all")
    every = resolve(config_dir)
    assert analyzer(every, "seasonal_anomaly")["run"]["status"] == "every_metric"
    assert "fallback" in analyzer(every, "prophet")["run"]["text"]


def test_each_setting_says_whether_the_analyzer_reads_it(config_dir: Path) -> None:
    site(config_dir, {"stumpy": {"implementation": {"mode": "discord", "motif_count": 2}}, "trend": {"finding_rule": {"min_slope_percent": 5}}})
    result = resolve(config_dir)
    assert setting(result, "pyod_outlier", "implementation.detector")["use"] == "label"
    assert setting(result, "pyod_outlier", "implementation.detector_type")["use"] == "used"
    assert setting(result, "trend", "finding_rules.min_slope_percent")["meaning"].startswith("Smallest steady climb")
    motif = setting(result, "stumpy", "implementation.motif_count")
    assert motif["use"] == "unused" and "mode is motif" in motif["use_note"]
    assert setting(result, "stumpy", "implementation.max_discords")["use"] == "used"
    # A misspelt block (finding_rule for finding_rules) is a key Trend never reads.
    typo = setting(result, "trend", "finding_rule.min_slope_percent")
    assert typo["use"] == "unknown" and "Check its spelling" in typo["use_note"]

    site(config_dir, {"stumpy": {"implementation": {"mode": "motif"}}})
    motif_mode = resolve(config_dir)
    assert setting(motif_mode, "stumpy", "implementation.motif_count")["use"] == "used"
    assert setting(motif_mode, "stumpy", "implementation.max_discords")["use"] == "unused"


def test_ruptures_and_baseline_shift_say_their_settings_are_separate(config_dir: Path) -> None:
    site(config_dir, {"baseline_shift": {"ruptures": {"min_size": 9}}})
    result = resolve(config_dir)
    assert setting(result, "baseline_shift", "ruptures.min_size")["value"] == 9
    assert setting(result, "ruptures", "ruptures.min_size")["value"] == 5
    assert "separate settings" in analyzer(result, "ruptures")["settings_note"]
    assert "separate settings" in analyzer(result, "baseline_shift")["settings_note"]


def test_the_real_config_resolves() -> None:
    """The shipped files load and every analyzer gets a run status (reads config/, changes nothing)."""
    result = settings_in_use()
    assert {item["analyzer_id"] for item in result["analyzers"]} >= {"trend", "pyod_outlier", "anomaly_zscore", "stumpy"}
    assert all(item["run"]["status"] in {"every_metric", "router", "only_if_chosen", "turned_off", "cant_run"} for item in result["analyzers"])
    # Every setting the shipped files name is a real one, and says what it does.
    assert all(entry["use"] != "unknown" and entry["meaning"] for item in result["analyzers"] for entry in item["settings"])


def test_api_answers_and_refuses_an_unknown_data_source() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    ok = client.get("/api/analyzer-settings", params={"service": "payments-api"})
    assert ok.status_code == 200 and ok.json()["service"] == "payments-api"
    assert client.get("/api/analyzer-settings", params={"provider": "nope"}).status_code == 400
