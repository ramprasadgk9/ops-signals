"""docker-compose.packaged.yml passes only the settings it lists to the backend, so a setting the
app documents but the file leaves out can't be turned on in that deployment (the in-app "How to
turn it on" steps for Jira tell team-server users to put these in .env)."""

from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.packaged.yml"

JIRA_SETTINGS = [
    "OPS_SIGNALS_TICKETING_ENABLED",
    "OPS_SIGNALS_JIRA_BASE_URL",
    "OPS_SIGNALS_JIRA_EMAIL",
    "OPS_SIGNALS_JIRA_API_TOKEN",
    "OPS_SIGNALS_JIRA_PROJECT_KEY",
    "OPS_SIGNALS_JIRA_ISSUE_TYPE",
    "OPS_SIGNALS_JIRA_WEBHOOK_SECRET",
]


def backend_environment() -> dict[str, str]:
    return yaml.safe_load(COMPOSE.read_text())["services"]["backend"]["environment"]


def test_jira_settings_reach_the_backend_from_dot_env():
    environment = backend_environment()
    for name in JIRA_SETTINGS:
        assert environment.get(name) is not None, f"{name} is not passed to the backend"
        assert environment[name].startswith(f"${{{name}:-"), f"{name} should come from .env, got {environment[name]!r}"


def test_ticketing_stays_off_unless_turned_on():
    assert backend_environment()["OPS_SIGNALS_TICKETING_ENABLED"] == "${OPS_SIGNALS_TICKETING_ENABLED:-false}"


SIGN_IN_SETTINGS = [
    "OPS_SIGNALS_AUTH_MODE",
    "OPS_SIGNALS_AUTH_USER_HEADER",
    "OPS_SIGNALS_AUTH_GROUPS_HEADER",
    "OPS_SIGNALS_AUTH_EDITOR_GROUPS",
    "OPS_SIGNALS_AUTH_ADMIN_GROUPS",
]


def test_sign_in_settings_reach_the_backend_from_dot_env():
    environment = backend_environment()
    for name in SIGN_IN_SETTINGS:
        assert environment.get(name, "").startswith(f"${{{name}:-"), f"{name} should come from .env"


def test_sign_in_stays_off_and_the_dev_user_stays_out():
    environment = backend_environment()
    assert environment["OPS_SIGNALS_AUTH_MODE"] == "${OPS_SIGNALS_AUTH_MODE:-none}"
    assert "OPS_SIGNALS_DEV_USER" not in environment
