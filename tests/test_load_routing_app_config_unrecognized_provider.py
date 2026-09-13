from __future__ import annotations

import pytest

from backend.app.services.timeseries_routing_service import build_csv_routing_config, load_routing_app_config


def test_unrecognized_provider_raises_a_clear_error_instead_of_a_confusing_keyerror() -> None:
    # Previously this silently fell back to loading config/config.yaml directly - a partial base
    # config missing "input"/"analysis" entirely, which crashed with KeyError: 'analysis' instead
    # of explaining what went wrong.
    with pytest.raises(ValueError, match="clodwatch"):
        load_routing_app_config("clodwatch")


def test_unrecognized_provider_error_points_at_the_custom_provider_as_the_real_answer() -> None:
    with pytest.raises(ValueError, match="provider='custom'"):
        load_routing_app_config("clodwatch")


def test_build_csv_routing_config_surfaces_the_same_clear_error() -> None:
    with pytest.raises(ValueError, match="clodwatch"):
        build_csv_routing_config(provider="clodwatch", file_path="unused.csv")


@pytest.mark.parametrize("provider", ["generic", "prometheus", "datadog", "custom"])
def test_every_real_provider_still_loads_without_error(provider: str) -> None:
    config = load_routing_app_config(provider)
    assert config.input is not None
