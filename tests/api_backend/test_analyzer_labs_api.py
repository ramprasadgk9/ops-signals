from datetime import datetime, timedelta

from fastapi.testclient import TestClient
import yaml

from backend.app.api import analyzer_labs
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import NormalizedPoint


def _draft_payload(analyzer_id: str = "motif_detection"):
    return {
        "config": {
            "analyzer_id": analyzer_id,
            "display_name": "Motif Detection",
            "template_type": "Motif / Repeating Pattern",
            "library": "math",
            "enabled": True,
            "runtime_mapping": "stumpy",
            "supported_profiles": ["seasonal", "motif", "repeating_pattern"],
            "min_samples": 30,
            "requires_regular_sampling": True,
            "requires_numeric": True,
            "base_score": 0.3,
            "scoring_rules": [
                {"metric": "seasonality_strength", "operator": "gte", "threshold": 0.42, "add": 0.2}
            ],
            "runtime_params": {"window_size": 20},
            "selected_explanation": "The series appears to repeat similar shapes.",
            "excluded_explanation": "The series is too irregular or too short.",
        }
    }


def test_analyzer_lab_config_suggestions_lifecycle():
    app = create_app("sqlite+pysqlite:///:memory:")
    payload = {
        "analyzer_id": "pyod_outlier",
        "lab_name": "PyOD Outlier Lab",
        "suggestion_name": "strict pyod",
        "yaml_text": "pyod_outlier:\n  enabled: true\n",
        "implementation_json": {"library": "pyod", "contamination": 0.01},
        "finding_rules_json": {"min_range_excess": 0.56},
        "benchmark_summary_json": {"pass_rate": 1.0},
        "pass_fail_status": "pass",
        "created_by": "test",
    }

    with TestClient(app) as client:
        created = client.post("/api/analyzer-labs/config-suggestions", json=payload)
        assert created.status_code == 200
        created_body = created.json()
        assert created_body["id"] > 0
        assert created_body["yaml_text"] == payload["yaml_text"]

        listed = client.get("/api/analyzer-labs/config-suggestions", params={"analyzer_id": "pyod_outlier"})
        assert listed.status_code == 200
        assert [row["suggestion_name"] for row in listed.json()] == ["strict pyod"]

        deleted = client.delete(f"/api/analyzer-labs/config-suggestions/{created_body['id']}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] == 1

        listed_after_delete = client.get("/api/analyzer-labs/config-suggestions", params={"analyzer_id": "pyod_outlier"})
        assert listed_after_delete.json() == []


def test_analyzer_lab_config_suggestions_clear_by_analyzer():
    app = create_app("sqlite+pysqlite:///:memory:")

    with TestClient(app) as client:
        for analyzer_id in ["pyod_outlier", "stumpy"]:
            response = client.post(
                "/api/analyzer-labs/config-suggestions",
                json={
                    "analyzer_id": analyzer_id,
                    "lab_name": "Lab",
                    "suggestion_name": analyzer_id,
                    "yaml_text": f"{analyzer_id}:\n  enabled: true\n",
                    "pass_fail_status": "unknown",
                },
            )
            assert response.status_code == 200

        cleared = client.delete("/api/analyzer-labs/config-suggestions", params={"analyzer_id": "pyod_outlier"})
        assert cleared.status_code == 200
        assert cleared.json()["deleted"] == 1

        remaining = client.get("/api/analyzer-labs/config-suggestions")
        assert [row["analyzer_id"] for row in remaining.json()] == ["stumpy"]


def test_analyzer_lab_library_check_verified_and_missing():
    app = create_app("sqlite+pysqlite:///:memory:")

    with TestClient(app) as client:
        verified = client.post(
            "/api/analyzer-labs/libraries/check",
            json={"package": "math", "import_name": "math"},
        )
        assert verified.status_code == 200
        assert verified.json()["status"] == "verified"
        assert verified.json()["installed"] is True

        missing = client.post(
            "/api/analyzer-labs/libraries/check",
            json={
                "package": "definitely-missing-ops-signals-package",
                "import_name": "definitely_missing_ops_signals_package",
            },
        )
        assert missing.status_code == 200
        assert missing.json()["status"] == "missing"
        assert missing.json()["installed"] is False


def test_analyzer_lab_readiness_existing_and_missing_analyzer():
    app = create_app("sqlite+pysqlite:///:memory:")

    with TestClient(app) as client:
        existing = client.get(
            "/api/analyzer-labs/readiness/stumpy",
            params={"library": "math", "import_name": "math", "runtime_mapping": "stumpy"},
        )
        assert existing.status_code == 200
        existing_body = existing.json()
        assert existing_body["router_definition_exists"] is True
        assert existing_body["router_definition_status"] == "saved"
        assert existing_body["config_exists"] is True
        assert existing_body["runtime_mapping_status"] == "executable"
        assert existing_body["backend_implementation_exists"] is True
        assert existing_body["library_status"] == "verified"
        assert existing_body["executable"] is True

        missing = client.get(
            "/api/analyzer-labs/readiness/greykite_forecast",
            params={
                "library": "definitely-missing-ops-signals-package",
                "import_name": "definitely_missing_ops_signals_package",
                "runtime_mapping": "greykite_forecast",
            },
        )
        assert missing.status_code == 200
        missing_body = missing.json()
        assert missing_body["router_definition_exists"] is False
        assert missing_body["router_definition_status"] == "missing"
        assert missing_body["config_exists"] is False
        assert missing_body["runtime_mapping_status"] == "not_implemented"
        assert missing_body["backend_implementation_exists"] is False
        assert missing_body["library_status"] == "missing"
        assert missing_body["executable"] is False


def test_analyzer_lab_runtime_mappings_and_draft_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZERS_PATH", tmp_path / "custom_analyzers.yaml")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_REGISTRY_DIR", tmp_path / "analyzer_registry.d")
    app = create_app("sqlite+pysqlite:///:memory:")

    with TestClient(app) as client:
        mappings = client.get("/api/analyzer-labs/runtime-mappings")
        assert mappings.status_code == 200
        mapping_ids = [row["id"] for row in mappings.json()]
        assert "stumpy" in mapping_ids
        assert "not_implemented" in mapping_ids

        created = client.post("/api/analyzer-labs/drafts", json=_draft_payload())
        assert created.status_code == 200
        draft = created.json()
        # Structural validation happens automatically at save time (_validate_analyzer already
        # ran above this point) - status lands directly on "routing_tested" instead of "draft",
        # so promotion is available immediately with no separate validate step required.
        assert draft["status"] == "routing_tested"
        assert draft["config"]["runtime_mapping"] == "stumpy"

        preview = client.get(f"/api/analyzer-labs/drafts/{draft['id']}/yaml-preview")
        assert preview.status_code == 200
        assert preview.json()["analyzer_id"] == "motif_detection"
        assert "motif_detection:" in preview.json()["yaml_text"]
        assert "runtime_mapping: stumpy" in preview.json()["yaml_text"]
        assert "implementation:" in preview.json()["yaml_text"]
        assert "status: pending" in preview.json()["yaml_text"]

        promoted = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/promote", json={})
        assert promoted.status_code == 200
        assert promoted.json()["status"] in {"ready_for_backend", "executable"}

        execution = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/execution-test", json={})
        assert execution.status_code == 200
        assert execution.json()["status"] in {"passed", "failed"}
        assert execution.json()["available"] is True

        registration_path = tmp_path / "analyzer_registry.d" / "custom_motif_detection.yml"
        assert registration_path.exists()

        deleted = client.delete("/api/analyzer-labs/analyzers/motif_detection")
        assert deleted.status_code == 200
        deleted_body = deleted.json()
        assert deleted_body["draft"] is True
        assert deleted_body["registration"] is True
        assert deleted_body["code_file"] is False

        remaining = client.get("/api/analyzer-labs/drafts")
        assert remaining.status_code == 200
        assert remaining.json() == []
        assert not registration_path.exists()


def test_analyzer_lab_backend_support_generates_pending_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZERS_PATH", tmp_path / "custom_analyzers.yaml")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_ADAPTER_DIR", tmp_path / "custom_adapters")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_REGISTRY_DIR", tmp_path / "analyzer_registry.d")
    app = create_app("sqlite+pysqlite:///:memory:")
    payload = _draft_payload("statsforecast_forecast")
    payload["config"]["display_name"] = "StatsForecast Forecast"
    payload["config"]["library"] = "statsforecast"
    payload["config"]["runtime_mapping"] = "not_implemented"
    payload["config"]["supported_profiles"] = ["forecast"]

    with TestClient(app) as client:
        created = client.post("/api/analyzer-labs/drafts", json=payload)
        assert created.status_code == 200
        draft = created.json()
        assert draft["status"] == "routing_tested"

        promoted = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/promote", json={})
        assert promoted.status_code == 200

        support = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/backend-support", json={})
        assert support.status_code == 200
        body = support.json()
        assert body["implementation_status"] == "pending"
        assert body["module"] == "backend.app.analyzers.custom.statsforecast_forecast"
        assert body["class_name"] == "StatsforecastForecastAnalyzer"
        assert body["created"] is True

        adapter_path = tmp_path / "custom_adapters" / "statsforecast_forecast.py"
        assert adapter_path.exists()
        assert "class StatsforecastForecastAnalyzer" in adapter_path.read_text(encoding="utf-8")
        assert "return []" in adapter_path.read_text(encoding="utf-8")

        # The real registration - config/analyzer_registry.d/custom_{id}.yml (see
        # analyzer_labs.promote_analyzer_draft / add_backend_support) - not the legacy
        # custom_analyzers.yaml, which nothing in production reads anymore.
        registration_config = yaml.safe_load(
            (tmp_path / "analyzer_registry.d" / "custom_statsforecast_forecast.yml").read_text(encoding="utf-8")
        )
        entry = registration_config["analyzers"]["statsforecast_forecast"]
        assert entry["class_path"] == "backend.app.analyzers.custom.statsforecast_forecast.StatsforecastForecastAnalyzer"
        assert entry["router"]["supported_profiles"] == ["forecast"]


def test_analyzer_lab_execution_test_unavailable_for_config_only():
    app = create_app("sqlite+pysqlite:///:memory:")
    payload = _draft_payload("statsforecast_forecast")
    payload["config"]["runtime_mapping"] = "not_implemented"
    payload["config"]["library"] = "math"

    with TestClient(app) as client:
        created = client.post("/api/analyzer-labs/drafts", json=payload)
        assert created.status_code == 200
        draft = created.json()

        execution = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/execution-test", json={})
        assert execution.status_code == 200
        body = execution.json()
        assert body["available"] is False
        assert body["status"] == "unavailable"
        assert "recommendation-only" in body["reason"]


def test_analyzer_lab_execution_test_runs_the_real_promoted_analyzer(tmp_path, monkeypatch):
    """Covers the actual point of wiring Promote/Add backend support into
    config/analyzer_registry.d/: once an analyzer has gone through the full flow, Execution Test
    should run *that analyzer's own analyze()* directly (via intelligence.analyzer_registry),
    not just report a stub adapter file exists. The adapter stub's class_path must be a real
    importable module for this to work, so - unlike the other tests here -
    CUSTOM_ANALYZER_ADAPTER_DIR is intentionally left at its real repo location (Python's import
    system can't resolve a class_path against a monkeypatched tmp path); the registration YAML
    itself is still tmp-isolated. The real adapter file this test creates is removed in the
    finally block so the repo is left clean."""
    analyzer_id = "execution_test_smoke_analyzer"
    adapter_path = analyzer_labs.CUSTOM_ANALYZER_ADAPTER_DIR / f"{analyzer_id}.py"
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZERS_PATH", tmp_path / "custom_analyzers.yaml")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_REGISTRY_DIR", tmp_path / "analyzer_registry.d")
    app = create_app("sqlite+pysqlite:///:memory:")
    payload = _draft_payload(analyzer_id)
    payload["config"]["runtime_mapping"] = "not_implemented"

    try:
        with TestClient(app) as client:
            created = client.post("/api/analyzer-labs/drafts", json=payload)
            assert created.status_code == 200
            draft = created.json()

            promoted = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/promote", json={})
            assert promoted.status_code == 200

            support = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/backend-support", json={})
            assert support.status_code == 200
            assert adapter_path.exists()

            # Real bug caught via live UI verification: the frontend calls readiness with
            # runtime_mapping="not_implemented" (the sentinel a self-implemented analyzer's own
            # config carries) literally as a query param. Before the fix, that sentinel string
            # got used as the "executable id" to look up instead of falling back to analyzer_id,
            # so a genuinely backend-supported custom analyzer showed as NOT executable in the
            # UI even though Execution Test (below) already proves it actually works.
            readiness = client.get(
                f"/api/analyzer-labs/readiness/{analyzer_id}",
                params={"library": "math", "import_name": "math", "runtime_mapping": "not_implemented"},
            )
            assert readiness.status_code == 200
            assert readiness.json()["backend_implementation_exists"] is True
            assert readiness.json()["executable"] is True

            execution = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/execution-test", json={})
            assert execution.status_code == 200
            body = execution.json()
            assert body["available"] is True
            assert body["status"] == "passed"
            assert body["signal_count"] == 0  # the generated stub's analyze() returns []
            assert body["data_source"] == "synthetic"
            assert "your analyzer's own analyze()" in body["reason"]
    finally:
        adapter_path.unlink(missing_ok=True)


def test_analyzer_lab_adapter_source_returns_generated_file_contents(tmp_path, monkeypatch):
    """Covers showing the generated adapter inline instead of sending the user to find the file
    themselves - fetches the same file backend-support just created."""
    analyzer_id = "adapter_source_smoke_analyzer"
    adapter_path = analyzer_labs.CUSTOM_ANALYZER_ADAPTER_DIR / f"{analyzer_id}.py"
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZERS_PATH", tmp_path / "custom_analyzers.yaml")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_REGISTRY_DIR", tmp_path / "analyzer_registry.d")
    app = create_app("sqlite+pysqlite:///:memory:")
    payload = _draft_payload(analyzer_id)
    payload["config"]["runtime_mapping"] = "not_implemented"

    try:
        with TestClient(app) as client:
            created = client.post("/api/analyzer-labs/drafts", json=payload)
            draft = created.json()

            missing = client.get(f"/api/analyzer-labs/drafts/{draft['id']}/adapter-source")
            assert missing.status_code == 404

            client.post(f"/api/analyzer-labs/drafts/{draft['id']}/promote", json={})
            client.post(f"/api/analyzer-labs/drafts/{draft['id']}/backend-support", json={})

            source = client.get(f"/api/analyzer-labs/drafts/{draft['id']}/adapter-source")
            assert source.status_code == 200
            body = source.json()
            assert body["analyzer_id"] == analyzer_id
            assert "class AdapterSourceSmokeAnalyzerAnalyzer" in body["source"]
            assert "def analyze(" in body["source"]
            assert body["adapter_path"] == str(adapter_path)

            # Reflects edits made directly to the file, same as clicking Refresh after editing
            # in your own editor.
            adapter_path.write_text(adapter_path.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
            refreshed = client.get(f"/api/analyzer-labs/drafts/{draft['id']}/adapter-source")
            assert refreshed.json()["source"].endswith("# edited\n")
    finally:
        adapter_path.unlink(missing_ok=True)


def test_analyzer_lab_execution_test_uses_real_sample_when_given_an_analysis_run_id(tmp_path, monkeypatch):
    """Covers testing against real history instead of a synthetic ramp - the same trust upgrade
    Behavior Lab's dry-run already has. Seeds real ops_normalized_timeseries_points rows for a
    known analysis_run_id, then confirms execution-test uses exactly those rows (not synthetic
    data) when asked to."""
    analyzer_id = "real_sample_smoke_analyzer"
    adapter_path = analyzer_labs.CUSTOM_ANALYZER_ADAPTER_DIR / f"{analyzer_id}.py"
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZERS_PATH", tmp_path / "custom_analyzers.yaml")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_REGISTRY_DIR", tmp_path / "analyzer_registry.d")
    app = create_app("sqlite+pysqlite:///:memory:")
    payload = _draft_payload(analyzer_id)
    payload["config"]["runtime_mapping"] = "not_implemented"

    try:
        with TestClient(app) as client:
            session_local = get_session_local()
            with session_local() as db:
                base = datetime.utcnow() - timedelta(hours=1)
                for i in range(5):
                    db.add(
                        NormalizedPoint(
                            metric_name="cpu_usage",
                            timestamp=base + timedelta(minutes=i * 10),
                            value=50.0 + i,
                            service="real-sample-service",
                            analysis_run_id="real-sample-run-1",
                        )
                    )
                db.commit()

            created = client.post("/api/analyzer-labs/drafts", json=payload)
            draft = created.json()
            client.post(f"/api/analyzer-labs/drafts/{draft['id']}/promote", json={})
            client.post(f"/api/analyzer-labs/drafts/{draft['id']}/backend-support", json={})

            execution = client.post(
                f"/api/analyzer-labs/drafts/{draft['id']}/execution-test",
                json={"analysis_run_id": "real-sample-run-1", "service": "real-sample-service"},
            )
            assert execution.status_code == 200
            body = execution.json()
            assert body["available"] is True
            assert body["status"] == "passed"
            assert body["data_source"] == "real"
            assert body["sample_count"] == 5
            assert "real data" in body["reason"]
    finally:
        adapter_path.unlink(missing_ok=True)


def test_analyzer_lab_execution_test_with_unknown_analysis_run_id_fails_clearly(tmp_path, monkeypatch):
    analyzer_id = "missing_sample_smoke_analyzer"
    adapter_path = analyzer_labs.CUSTOM_ANALYZER_ADAPTER_DIR / f"{analyzer_id}.py"
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZERS_PATH", tmp_path / "custom_analyzers.yaml")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_REGISTRY_DIR", tmp_path / "analyzer_registry.d")
    app = create_app("sqlite+pysqlite:///:memory:")
    payload = _draft_payload(analyzer_id)
    payload["config"]["runtime_mapping"] = "not_implemented"

    try:
        with TestClient(app) as client:
            created = client.post("/api/analyzer-labs/drafts", json=payload)
            draft = created.json()
            client.post(f"/api/analyzer-labs/drafts/{draft['id']}/promote", json={})
            client.post(f"/api/analyzer-labs/drafts/{draft['id']}/backend-support", json={})

            execution = client.post(
                f"/api/analyzer-labs/drafts/{draft['id']}/execution-test",
                json={"analysis_run_id": "does-not-exist"},
            )
            assert execution.status_code == 200
            body = execution.json()
            assert body["status"] == "failed"
            assert body["data_source"] == "real"
            assert "No normalized points found" in body["reason"]
    finally:
        adapter_path.unlink(missing_ok=True)


def test_delete_analyzer_removes_draft_registration_and_code_file_when_asked(tmp_path, monkeypatch):
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZERS_PATH", tmp_path / "custom_analyzers.yaml")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_REGISTRY_DIR", tmp_path / "analyzer_registry.d")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_ADAPTER_DIR", tmp_path / "custom_adapters")
    app = create_app("sqlite+pysqlite:///:memory:")
    payload = _draft_payload("deletable_analyzer")
    payload["config"]["runtime_mapping"] = "not_implemented"

    with TestClient(app) as client:
        created = client.post("/api/analyzer-labs/drafts", json=payload)
        draft = created.json()
        client.post(f"/api/analyzer-labs/drafts/{draft['id']}/promote", json={})
        client.post(f"/api/analyzer-labs/drafts/{draft['id']}/backend-support", json={})

        registration_path = tmp_path / "analyzer_registry.d" / "custom_deletable_analyzer.yml"
        adapter_path = tmp_path / "custom_adapters" / "deletable_analyzer.py"
        assert registration_path.exists()
        assert adapter_path.exists()

        deleted = client.delete("/api/analyzer-labs/analyzers/deletable_analyzer?delete_code_file=true")
        assert deleted.status_code == 200
        body = deleted.json()
        assert body == {"analyzer_id": "deletable_analyzer", "draft": True, "registration": True, "code_file": True}

        assert not registration_path.exists()
        assert not adapter_path.exists()
        assert client.get("/api/analyzer-labs/drafts").json() == []


def test_delete_analyzer_keeps_code_file_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZERS_PATH", tmp_path / "custom_analyzers.yaml")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_REGISTRY_DIR", tmp_path / "analyzer_registry.d")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_ADAPTER_DIR", tmp_path / "custom_adapters")
    app = create_app("sqlite+pysqlite:///:memory:")
    payload = _draft_payload("keep_code_analyzer")
    payload["config"]["runtime_mapping"] = "not_implemented"

    with TestClient(app) as client:
        created = client.post("/api/analyzer-labs/drafts", json=payload)
        draft = created.json()
        client.post(f"/api/analyzer-labs/drafts/{draft['id']}/promote", json={})
        client.post(f"/api/analyzer-labs/drafts/{draft['id']}/backend-support", json={})

        adapter_path = tmp_path / "custom_adapters" / "keep_code_analyzer.py"
        assert adapter_path.exists()

        deleted = client.delete("/api/analyzer-labs/analyzers/keep_code_analyzer")
        assert deleted.status_code == 200
        assert deleted.json()["code_file"] is False
        assert adapter_path.exists()  # not deleted - default keeps it


def test_delete_draft_only_analyzer_that_was_never_promoted(tmp_path, monkeypatch):
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_REGISTRY_DIR", tmp_path / "analyzer_registry.d")
    app = create_app("sqlite+pysqlite:///:memory:")
    payload = _draft_payload("never_promoted_analyzer")

    with TestClient(app) as client:
        client.post("/api/analyzer-labs/drafts", json=payload)

        deleted = client.delete("/api/analyzer-labs/analyzers/never_promoted_analyzer")
        assert deleted.status_code == 200
        assert deleted.json() == {
            "analyzer_id": "never_promoted_analyzer",
            "draft": True,
            "registration": False,
            "code_file": False,
        }


def test_delete_builtin_analyzer_via_wizard_endpoint_is_blocked():
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        deleted = client.delete("/api/analyzer-labs/analyzers/trend")
        assert deleted.status_code == 400
        assert "Built-in analyzers cannot be deleted" in deleted.json()["detail"]


def test_delete_nonexistent_analyzer_returns_404():
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        deleted = client.delete("/api/analyzer-labs/analyzers/totally_made_up_analyzer_id")
        assert deleted.status_code == 404


def test_deleting_and_resaving_the_same_analyzer_id_does_not_inherit_stale_status(tmp_path, monkeypatch):
    """The bug the unified delete endpoint fixes: previously, deleting only the registry file
    (not the Postgres draft row) left an invisible draft behind with status='executable'. Saving
    a new draft under the same analyzer_id then kept that stale status instead of starting over
    fresh - misleadingly showing readiness/promotion for code that was never re-verified. After a
    real delete, the draft row is gone entirely, so re-saving creates a brand new row landing on
    the normal freshly-validated baseline ('routing_tested', not 'executable'), never promoted."""
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZERS_PATH", tmp_path / "custom_analyzers.yaml")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_REGISTRY_DIR", tmp_path / "analyzer_registry.d")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_ADAPTER_DIR", tmp_path / "custom_adapters")
    app = create_app("sqlite+pysqlite:///:memory:")
    payload = _draft_payload("reused_analyzer_id")
    payload["config"]["runtime_mapping"] = "not_implemented"

    with TestClient(app) as client:
        created = client.post("/api/analyzer-labs/drafts", json=payload)
        draft = created.json()
        client.post(f"/api/analyzer-labs/drafts/{draft['id']}/promote", json={})
        client.post(f"/api/analyzer-labs/drafts/{draft['id']}/backend-support", json={})

        client.delete("/api/analyzer-labs/analyzers/reused_analyzer_id")

        resaved = client.post("/api/analyzer-labs/drafts", json=payload)
        assert resaved.status_code == 200
        assert resaved.json()["status"] == "routing_tested"
        assert resaved.json()["promoted_at"] is None


def test_analyzer_lab_routing_with_generated_lab_data():
    app = create_app("sqlite+pysqlite:///:memory:")
    payload = _draft_payload("statsforecast_forecast")["config"]
    payload["display_name"] = "StatsForecast Forecast"
    payload["library"] = "statsforecast"
    payload["runtime_mapping"] = "not_implemented"
    payload["supported_profiles"] = ["forecast", "seasonal", "trend"]
    payload["scoring_rules"] = [
        {"metric": "seasonality_strength", "operator": "gte", "threshold": 0.5, "add": 0.25},
        {"metric": "trend_strength", "operator": "gte", "threshold": 0.3, "add": 0.2},
        {"metric": "sample_count", "operator": "gte", "threshold": 60, "add": 0.05},
    ]

    with TestClient(app) as client:
        response = client.post(
            "/api/analyzer-labs/lab-routing-test",
            json={"config": payload, "lab_profile": "prophet_forecast"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["lab_profile"] == "prophet_forecast"
        assert body["detected_profiles"] == ["forecast", "seasonal", "trend"]
        assert body["runtime_status"] == "config_only"
        assert body["recommendation"] in {"RECOMMENDED", "OPTIONAL"}
