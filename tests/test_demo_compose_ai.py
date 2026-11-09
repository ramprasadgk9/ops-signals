"""Which AI the demo's backend uses (docker-compose.demo.yml, the backend's start-up script): the
script runs here with `getent` and `uvicorn` stubbed, once per way of starting the demo."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.demo.yml"
KEYS = (
    "OPS_SIGNALS_AI_ENABLED",
    "OPS_SIGNALS_AI_PROVIDER",
    "OPS_SIGNALS_OLLAMA_URL",
    "OPS_SIGNALS_OLLAMA_MODEL",
    "OPS_SIGNALS_OPENAI_BASE_URL",
    "OPS_SIGNALS_OLLAMA_TIMEOUT_SECONDS",
    "OPS_SIGNALS_INVESTIGATION_ROUND_SECONDS",
)
# The dev stack's .env, as Docker Compose hands it to the demo.
DOT_ENV = {"OPS_SIGNALS_AI_ENABLED": "true", "OPS_SIGNALS_AI_PROVIDER": "ollama", "OPS_SIGNALS_OLLAMA_MODEL": "qwen3:14b"}
PROFILE = {"OLLAMA_UP": "1"}
API = {"DEMO_AI_URL": "https://api.example.com/v1", "DEMO_AI_MODEL": "small-model"}


def start(tmp_path: Path, env: dict[str, str]) -> tuple[str, dict[str, str]]:
    script = yaml.safe_load(COMPOSE.read_text())["services"]["backend"]["command"][2].replace("$$", "$")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # `getent hosts ollama` succeeds only when the `ai` profile's server runs.
    (bin_dir / "getent").write_text('#!/bin/sh\n[ -n "$OLLAMA_UP" ]\n')
    (bin_dir / "uvicorn").write_text("#!/bin/sh\n" + "".join(f'echo "{key}=${key}"\n' for key in KEYS))
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    result = subprocess.run(
        ["sh", "-c", script],
        env={"PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin", **env},
        capture_output=True,
        text=True,
        check=True,
    )
    lines = result.stdout.splitlines()
    said = "\n".join(line for line in lines if line.startswith("AI "))
    backend = dict(line.split("=", 1) for line in lines if line.startswith("OPS_SIGNALS_"))
    return said, backend


def test_no_ai_stays_off(tmp_path) -> None:
    said, backend = start(tmp_path, {})
    assert said == ""
    assert backend["OPS_SIGNALS_AI_ENABLED"] == ""


def test_the_ai_profile_turns_its_model_on_with_time_for_investigate(tmp_path) -> None:
    said, backend = start(tmp_path, PROFILE)
    assert said == "AI is on: gemma3:4b from the ollama container (--profile ai)"
    assert backend["OPS_SIGNALS_OLLAMA_URL"] == "http://ollama:11434"
    assert (backend["OPS_SIGNALS_OLLAMA_TIMEOUT_SECONDS"], backend["OPS_SIGNALS_INVESTIGATION_ROUND_SECONDS"]) == ("90", "300")


@pytest.mark.parametrize("url", ["", "http://localhost:11434", "http://127.0.0.1:11434"])
def test_the_dev_env_ollama_is_found_on_your_machine_not_inside_the_container(tmp_path, url) -> None:
    # Before: the backend called localhost:11434, its own container, and every investigation failed.
    said, backend = start(tmp_path, {**DOT_ENV, "OPS_SIGNALS_OLLAMA_URL": url})
    assert said == "AI is on: qwen3:14b from Ollama on your machine (http://host.docker.internal:11434)"
    assert backend["OPS_SIGNALS_OLLAMA_URL"] == "http://host.docker.internal:11434"
    assert (backend["OPS_SIGNALS_OLLAMA_TIMEOUT_SECONDS"], backend["OPS_SIGNALS_INVESTIGATION_ROUND_SECONDS"]) == ("180", "300")


def test_your_own_time_limits_are_kept(tmp_path) -> None:
    _, backend = start(tmp_path, {**DOT_ENV, "OPS_SIGNALS_OLLAMA_TIMEOUT_SECONDS": "300", "OPS_SIGNALS_INVESTIGATION_ROUND_SECONDS": "600"})
    assert (backend["OPS_SIGNALS_OLLAMA_TIMEOUT_SECONDS"], backend["OPS_SIGNALS_INVESTIGATION_ROUND_SECONDS"]) == ("300", "600")


def test_the_ai_profile_wins_over_a_dev_env_ollama_with_no_address(tmp_path) -> None:
    said, backend = start(tmp_path, {**DOT_ENV, **PROFILE})
    assert said == "AI is on: gemma3:4b from the ollama container (--profile ai)"
    assert backend["OPS_SIGNALS_OLLAMA_MODEL"] == "gemma3:4b"


def test_an_ollama_you_point_at_wins_over_the_ai_profile(tmp_path) -> None:
    said, backend = start(tmp_path, {**DOT_ENV, **PROFILE, "OPS_SIGNALS_OLLAMA_URL": "http://gpu-box:11434"})
    assert said == "AI is on: ollama, from your settings"
    assert backend["OPS_SIGNALS_OLLAMA_URL"] == "http://gpu-box:11434"


def test_a_model_api_always_wins(tmp_path) -> None:
    # Before: the .env's OPS_SIGNALS_AI_ENABLED made the demo ignore DEMO_AI_URL.
    said, backend = start(tmp_path, {**DOT_ENV, **PROFILE, **API})
    assert said == "AI is on: small-model from https://api.example.com/v1 (the key is not printed)"
    assert (backend["OPS_SIGNALS_AI_PROVIDER"], backend["OPS_SIGNALS_OPENAI_BASE_URL"]) == ("openai_compatible", API["DEMO_AI_URL"])


def test_a_model_api_without_a_model_turns_ai_off(tmp_path) -> None:
    said, backend = start(tmp_path, {**DOT_ENV, "DEMO_AI_URL": API["DEMO_AI_URL"]})
    assert said.startswith("AI stays off: DEMO_AI_URL is set but DEMO_AI_MODEL is empty")
    assert backend["OPS_SIGNALS_AI_ENABLED"] == "false"


def test_another_provider_from_your_settings_is_left_alone(tmp_path) -> None:
    said, backend = start(tmp_path, {"OPS_SIGNALS_AI_ENABLED": "true", "OPS_SIGNALS_AI_PROVIDER": "anthropic"})
    assert said == "AI is on: anthropic, from your settings"
    assert backend["OPS_SIGNALS_AI_PROVIDER"] == "anthropic"
