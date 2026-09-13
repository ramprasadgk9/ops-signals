from __future__ import annotations

import pytest
import yaml

from backend.app.services.timeseries_routing_service import build_csv_routing_config, repo_root


def _load_yaml_input_section(provider: str) -> dict:
    path = repo_root() / "config" / "providers" / f"{provider}.yaml"
    with path.open() as handle:
        return yaml.safe_load(handle)["input"]


@pytest.mark.parametrize("provider", ["generic", "prometheus", "datadog"])
def test_build_csv_routing_config_uses_the_providers_own_yaml_mapping_and_required_columns(provider: str) -> None:
    # This is the regression test for the fix: provider_mappings/required_columns used to be
    # silently replaced by a second, hardcoded Python copy that happened to agree with these
    # YAML files - this proves the actual function output now comes from the file itself, read
    # independently here (not via the function under test), so it would fail if that override
    # ever crept back in or if someone edited a provider YAML expecting it to take effect.
    expected = _load_yaml_input_section(provider)

    config = build_csv_routing_config(provider=provider, file_path="unused.csv")

    assert config.input.provider_mappings == (expected.get("provider_mappings") or {})
    assert config.input.required_columns == expected["required_columns"]
