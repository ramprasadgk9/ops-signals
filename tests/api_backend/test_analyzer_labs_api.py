from fastapi.testclient import TestClient

from backend.app.main import create_app


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
