from fastapi.testclient import TestClient

from backend.app.api import analyzer_labs
from backend.app.main import create_app


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
        "finding_rules_json": {"min_outlier_points": 8},
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
        assert draft["status"] == "draft"
        assert draft["config"]["runtime_mapping"] == "stumpy"

        routed = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/routing-test", json={})
        assert routed.status_code == 200
        assert routed.json()["status"] == "routing_tested"

        preview = client.get(f"/api/analyzer-labs/drafts/{draft['id']}/yaml-preview")
        assert preview.status_code == 200
        assert preview.json()["analyzer_id"] == "motif_detection"
        assert "motif_detection:" in preview.json()["yaml_text"]
        assert "runtime_mapping: stumpy" in preview.json()["yaml_text"]

        promoted = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/promote", json={})
        assert promoted.status_code == 200
        assert promoted.json()["status"] in {"ready_for_backend", "executable"}

        execution = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/execution-test", json={})
        assert execution.status_code == 200
        assert execution.json()["status"] in {"passed", "failed"}
        assert execution.json()["available"] is True

        deleted = client.delete(f"/api/analyzer-labs/drafts/{draft['id']}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] == 1

        remaining = client.get("/api/analyzer-labs/drafts")
        assert remaining.status_code == 200
        assert remaining.json() == []


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
