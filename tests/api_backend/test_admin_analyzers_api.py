from fastapi.testclient import TestClient

from backend.app.api import admin_analyzers
from backend.app.main import create_app


def _custom_payload(analyzer_id: str = "custom_forecast"):
    return {
        "analyzer_id": analyzer_id,
        "display_name": "Custom Forecast",
        "template_type": "Forecast",
        "library": "customlib",
        "enabled": True,
        "runtime_mapping": "not_implemented",
        "supported_profiles": ["forecast"],
        "min_samples": 30,
        "requires_regular_sampling": True,
        "requires_numeric": True,
        "base_score": 0.3,
        "scoring_rules": [
            {"metric": "seasonality_strength", "operator": "gte", "threshold": 0.42, "add": 0.2}
        ],
        "runtime_params": {},
        "selected_explanation": "Forecast behavior is present.",
        "excluded_explanation": "Forecast behavior is not present.",
    }


def test_delete_custom_analyzer_removes_promoted_yaml_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_analyzers, "CUSTOM_ANALYZERS_PATH", tmp_path / "custom_analyzers.yaml")
    app = create_app("sqlite+pysqlite:///:memory:")

    with TestClient(app) as client:
        created = client.post("/api/admin/analyzers", json=_custom_payload("statsforecast_forecast"))
        assert created.status_code == 200
        assert created.json()["source"] == "custom"

        listed = client.get("/api/admin/analyzers")
        assert listed.status_code == 200
        assert any(row["analyzer_id"] == "statsforecast_forecast" for row in listed.json())

        deleted = client.delete("/api/admin/analyzers/statsforecast_forecast")
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": 1, "analyzer_id": "statsforecast_forecast"}

        listed_after_delete = client.get("/api/admin/analyzers")
        assert listed_after_delete.status_code == 200
        assert all(row["analyzer_id"] != "statsforecast_forecast" for row in listed_after_delete.json())


def test_delete_builtin_analyzer_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_analyzers, "CUSTOM_ANALYZERS_PATH", tmp_path / "custom_analyzers.yaml")
    app = create_app("sqlite+pysqlite:///:memory:")

    with TestClient(app) as client:
        deleted = client.delete("/api/admin/analyzers/stumpy")
        assert deleted.status_code == 400
        assert "Built-in analyzers cannot be removed" in deleted.json()["detail"]
