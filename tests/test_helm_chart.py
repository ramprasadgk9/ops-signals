"""Tests for the Ops Signals Helm chart templates and rendered manifests."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART_DIR = Path(__file__).resolve().parents[1] / "helm" / "ops-signals"
HELM_BIN = shutil.which("helm")

pytestmark = pytest.mark.skipif(HELM_BIN is None, reason="helm binary not found on PATH")


def run_helm_template(release_name: str = "ops-signals", values: dict | None = None, extra_args: list[str] | None = None) -> list[dict]:
    cmd = [HELM_BIN, "template", release_name, str(CHART_DIR)]
    if extra_args:
        cmd.extend(extra_args)
    if values:
        values_yaml = yaml.dump(values)
        res = subprocess.run(cmd + ["-f", "-"], input=values_yaml, text=True, capture_output=True, check=True)
    else:
        res = subprocess.run(cmd, text=True, capture_output=True, check=True)
    return [doc for doc in yaml.safe_load_all(res.stdout) if doc]


def test_helm_lint_succeeds():
    res = subprocess.run([HELM_BIN, "lint", str(CHART_DIR)], capture_output=True, text=True)
    assert res.returncode == 0, f"helm lint failed:\n{res.stderr}\n{res.stdout}"


def test_default_manifests_structure():
    manifests = run_helm_template("ops-signals")
    kinds_and_names = {(m["kind"], m["metadata"]["name"]) for m in manifests}

    assert ("Service", "ops-signals-backend") in kinds_and_names
    assert ("Deployment", "ops-signals-backend") in kinds_and_names
    assert ("Service", "ops-signals-web") in kinds_and_names
    assert ("Deployment", "ops-signals-web") in kinds_and_names
    # MCP is disabled by default to prevent ImagePullBackOff on stdio server
    assert ("Deployment", "ops-signals-mcp") not in kinds_and_names


def test_web_backend_url_matches_service_name_with_custom_release():
    manifests = run_helm_template("prod-signals")
    web_dep = next(m for m in manifests if m["kind"] == "Deployment" and m["metadata"]["name"] == "prod-signals-ops-signals-web")
    env = {e["name"]: e.get("value") for e in web_dep["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["OPS_SIGNALS_BACKEND_URL"] == "http://prod-signals-ops-signals-backend:8000/api/"


def test_probes_configured_on_backend_and_web():
    manifests = run_helm_template("ops-signals")
    backend_dep = next(m for m in manifests if m["kind"] == "Deployment" and m["metadata"]["name"] == "ops-signals-backend")
    web_dep = next(m for m in manifests if m["kind"] == "Deployment" and m["metadata"]["name"] == "ops-signals-web")

    backend_c = backend_dep["spec"]["template"]["spec"]["containers"][0]
    assert backend_c.get("readinessProbe") is not None
    assert backend_c.get("livenessProbe") is not None
    assert backend_c["readinessProbe"]["httpGet"]["path"] == "/api/health"
    assert backend_c["livenessProbe"]["httpGet"]["path"] == "/api/health/live"

    web_c = web_dep["spec"]["template"]["spec"]["containers"][0]
    assert web_c.get("readinessProbe") is not None
    assert web_c.get("livenessProbe") is not None
    assert web_c["readinessProbe"]["httpGet"]["path"] == "/"
    assert web_c["livenessProbe"]["httpGet"]["path"] == "/"


def test_integrations_render_secret_refs():
    values = {
        "ticketing": {
            "enabled": True,
            "activeProvider": "jira",
            "jira": {
                "baseUrl": "https://company.atlassian.net",
                "secret": {
                    "name": "jira-creds",
                    "apiTokenKey": "token",
                    "webhookSecretKey": "secret",
                },
            },
        },
        "slack": {
            "enabled": True,
            "secret": {
                "name": "slack-creds",
                "key": "webhook",
            },
        },
        "alertEnrichment": {
            "enabled": True,
            "secret": {
                "name": "alert-creds",
                "receiverTokenKey": "recv-tok",
                "slackWebhookUrlKey": "slack-url",
            },
        },
        "ingress": {
            "enabled": True,
            "host": "signals.internal",
            "tls": [{"hosts": ["signals.internal"], "secretName": "tls-secret"}],
        },
        "backend": {
            "extraEnv": [{"name": "MY_VAR", "value": "123"}],
        },
    }
    manifests = run_helm_template("ops-signals", values=values)
    backend_dep = next(m for m in manifests if m["kind"] == "Deployment" and m["metadata"]["name"] == "ops-signals-backend")
    container = backend_dep["spec"]["template"]["spec"]["containers"][0]
    env_list = container["env"]

    env_map = {e["name"]: e for e in env_list}

    # Jira
    assert env_map["OPS_SIGNALS_TICKETING_ENABLED"]["value"] == "true"
    assert env_map["OPS_SIGNALS_JIRA_BASE_URL"]["value"] == "https://company.atlassian.net"
    assert env_map["OPS_SIGNALS_JIRA_API_TOKEN"]["valueFrom"]["secretKeyRef"]["name"] == "jira-creds"
    assert env_map["OPS_SIGNALS_JIRA_WEBHOOK_SECRET"]["valueFrom"]["secretKeyRef"]["name"] == "jira-creds"

    # Slack
    assert env_map["OPS_SIGNALS_SLACK_ENABLED"]["value"] == "true"
    assert env_map["OPS_SIGNALS_SLACK_WEBHOOK_URL"]["valueFrom"]["secretKeyRef"]["name"] == "slack-creds"

    # Alert enrichment
    assert env_map["OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED"]["value"] == "true"
    assert env_map["OPS_SIGNALS_ALERT_RECEIVER_TOKEN"]["valueFrom"]["secretKeyRef"]["name"] == "alert-creds"
    assert env_map["OPS_SIGNALS_ALERT_SLACK_WEBHOOK_URL"]["valueFrom"]["secretKeyRef"]["name"] == "alert-creds"

    # Ingress host sets UI base URL automatically
    assert env_map["OPS_SIGNALS_UI_BASE_URL"]["value"] == "https://signals.internal"

    # ExtraEnv
    assert env_map["MY_VAR"]["value"] == "123"


def test_ticketing_worker_can_be_disabled_and_ingress_hosts_fallback():
    values = {
        "ticketing": {
            "enabled": True,
            "worker": {
                "enabled": False,
            },
        },
        "alertEnrichment": {
            "enabled": True,
            "notifyOnResolve": False,
        },
        "ingress": {
            "enabled": True,
            "host": "",
            "hosts": ["ops.example.com"],
        },
    }
    manifests = run_helm_template("ops-signals", values=values)
    backend_dep = next(m for m in manifests if m["kind"] == "Deployment" and m["metadata"]["name"] == "ops-signals-backend")
    env_map = {e["name"]: e for e in backend_dep["spec"]["template"]["spec"]["containers"][0]["env"]}

    assert env_map["OPS_SIGNALS_TICKETING_WORKER_ENABLED"]["value"] == "false"
    assert env_map["OPS_SIGNALS_ALERT_NOTIFY_ON_RESOLVE"]["value"] == "false"
    assert env_map["OPS_SIGNALS_UI_BASE_URL"]["value"] == "http://ops.example.com"

