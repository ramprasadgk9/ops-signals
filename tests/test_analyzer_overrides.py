from __future__ import annotations

from pathlib import Path

import pytest

from intelligence.analyzer_overrides import OverrideSet, load_overrides
from intelligence.analyzer_registry import load_registrations

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRATIONS = load_registrations(PROJECT_ROOT / "config" / "analyzer_registry.d")

PAYMENTS = """
overrides:
  payments_trend:
    scope: {service: payments-api}
    reason: Memory grows slowly before an outage here.
    analyzers:
      trend:
        finding_rules: {min_slope_percent: 5}
"""


def _load(tmp_path: Path, **files: str) -> OverrideSet:
    directory = tmp_path / "analyzer_overrides.d"
    directory.mkdir()
    for name, text in files.items():
        (directory / name).write_text(text.strip(), encoding="utf-8")
    return load_overrides(directory, REGISTRATIONS)


def test_a_missing_or_empty_directory_means_no_overrides(tmp_path: Path) -> None:
    assert load_overrides(tmp_path / "absent", REGISTRATIONS).overrides == []
    resolution = _load(tmp_path).resolve("payments-api", "cpu")
    assert (resolution.params, resolution.applied, resolution.max_analyzers) == ({}, [], None)


def test_an_override_applies_to_its_service_and_nothing_else(tmp_path: Path) -> None:
    overrides = _load(tmp_path, **{"payments-team.yml": PAYMENTS})

    assert overrides.errors == []
    assert overrides.resolve("payments-api", "memory").params == {"trend": {"finding_rules": {"min_slope_percent": 5}}}
    # A service no file names keeps the defaults.
    assert overrides.resolve("checkout-api", "memory").params == {}
    assert overrides.resolve(None, "memory").params == {}


def test_the_file_name_does_not_matter_only_the_scope(tmp_path: Path) -> None:
    overrides = _load(tmp_path, **{"anything-at-all.yaml": PAYMENTS})
    assert overrides.resolve("payments-api", "memory").applied == ["payments_trend"]


def test_wildcards_match_service_variants(tmp_path: Path) -> None:
    overrides = _load(tmp_path, **{"payments.yml": PAYMENTS.replace("service: payments-api", "service: payments-*")})

    assert overrides.resolve("payments-refunds", "memory").applied == ["payments_trend"]
    assert overrides.resolve("checkout-payments", "memory").applied == []


def test_more_specific_scopes_apply_later_and_win(tmp_path: Path) -> None:
    overrides = _load(
        tmp_path,
        **{
            "platform.yml": """
overrides:
  all_payments:
    scope: {service: payments-*}
    reason: Payments services are noisy.
    analyzers:
      trend: {finding_rules: {min_slope_percent: 20}}
      pyod_outlier: {finding_rule: {min_sustained_points: 12}}
    selection: {disabled: [stumpy]}
  memory_everywhere:
    scope: {metric: process_resident_memory_bytes}
    reason: Memory leaks start small.
    analyzers:
      trend: {finding_rules: {min_slope_percent: 8}}
""",
            "payments-team.yml": """
overrides:
  payments_api_memory:
    scope: {service: payments-api, metric: process_resident_memory_bytes}
    reason: This service leaks memory before outages.
    analyzers:
      trend: {finding_rules: {min_slope_percent: 3}}
    selection: {max_analyzers: 2}
""",
        },
    )

    resolution = overrides.resolve("payments-api", "process_resident_memory_bytes")

    assert resolution.applied == ["memory_everywhere", "all_payments", "payments_api_memory"]
    assert resolution.params == {
        "trend": {"finding_rules": {"min_slope_percent": 3}},
        "pyod_outlier": {"finding_rule": {"min_sustained_points": 12}},
    }
    assert (resolution.max_analyzers, resolution.disabled) == (2, {"stumpy"})
    assert resolution.conflicts == []
    # Service beats metric when only one of them is set.
    assert overrides.resolve("payments-refunds", "process_resident_memory_bytes").params["trend"] == {"finding_rules": {"min_slope_percent": 20}}


def test_equally_specific_overrides_that_disagree_are_reported(tmp_path: Path) -> None:
    overrides = _load(
        tmp_path,
        **{
            "a.yml": PAYMENTS.replace("payments-api", "payments-*").replace("payments_trend", "wide"),
            "b.yml": PAYMENTS.replace("payments-api", '"*-api"').replace("payments_trend", "apis").replace("min_slope_percent: 5", "min_slope_percent: 15"),
        },
    )

    resolution = overrides.resolve("payments-api", "memory")

    # Same specificity: applied in file order, so the later file's value stands, and it's flagged.
    assert resolution.params["trend"] == {"finding_rules": {"min_slope_percent": 15}}
    assert resolution.conflicts == [("trend.finding_rules.min_slope_percent", "apis", "wide")]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("overrides: [1, 2]", "'overrides' mapping"),
        ("overrides:\n  x: {scope: {service: a}, analyzers: {trend: {finding_rules: {min_slope_percent: 5}}}}", "reason is required"),
        ("overrides:\n  x: {reason: r, analyzers: {trend: {finding_rules: {min_slope_percent: 5}}}}", "scope must be a mapping"),
        ("overrides:\n  x: {scope: {}, reason: r, analyzers: {trend: {finding_rules: {min_slope_percent: 5}}}}", "scope needs a service"),
        ("overrides:\n  x: {scope: {team: payments}, reason: r}", "scope must be a mapping with service and/or metric"),
        ("overrides:\n  x: {scope: {service: unknown-service}, reason: r, analyzers: {trend: {finding_rules: {min_slope_percent: 5}}}}", "no service label"),
        ("overrides:\n  x: {scope: {service: a}, reason: r, analyzers: {nope: {x: 1}}}", "unknown analyzer 'nope'"),
        ("overrides:\n  x: {scope: {service: a}, reason: r, analyzers: {trend: {implementation: {model: RLM}}}}", "'trend.implementation.model' can't be set per service"),
        ("overrides:\n  x: {scope: {service: a}, reason: r, analyzers: {trend: {finding_rules: {min_slope_percent: 0.5}}}}", "must be between 1 and 100, got 0.5"),
        ("overrides:\n  x: {scope: {service: a}, reason: r, analyzers: {trend: {finding_rules: {min_slope_percent: high}}}}", "must be a number"),
        ("overrides:\n  x: {scope: {service: a}, reason: r, analyzers: {pyod_outlier: {finding_rule: {min_sustained_points: 4.5}}}}", "must be a whole number"),
        ("overrides:\n  x: {scope: {service: a}, reason: r, selection: {max_analyzers: 0}}", "max_analyzers must be a whole number from 1"),
        ("overrides:\n  x: {scope: {service: a}, reason: r, selection: {disabled: [nope]}}", "selection.disabled must list known analyzer ids"),
        ("overrides:\n  x: {scope: {service: a}, reason: r}", "changes nothing"),
        ("overrides:\n  x: {scope: {service: a}, reason: r, owner: me, selection: {max_analyzers: 2}}", "unknown key(s) ['owner']"),
        ("overrides: {x: [", "not valid YAML"),
        ("overrides:\n  x: {scope: {service: *-api}, reason: r, selection: {max_analyzers: 2}}", 'quote a name that starts with *, e.g. service: "*-api"'),
    ],
)
def test_a_file_with_a_problem_is_skipped_and_says_why(tmp_path: Path, text: str, message: str) -> None:
    overrides = _load(tmp_path, **{"broken.yml": text})

    assert overrides.overrides == []
    assert len(overrides.errors) == 1
    assert overrides.errors[0].source_file == "broken.yml"
    assert message in overrides.errors[0].message


def test_one_broken_file_does_not_stop_the_others(tmp_path: Path) -> None:
    broken = PAYMENTS.replace("payments_trend", "checkout_trend").replace("payments-api", "checkout-api").replace("min_slope_percent: 5", "min_slope_percent: 500")
    overrides = _load(tmp_path, **{"checkout-team.yml": broken, "payments-team.yml": PAYMENTS})

    assert [error.source_file for error in overrides.errors] == ["checkout-team.yml"]
    assert overrides.resolve("payments-api", "memory").applied == ["payments_trend"]
    # The broken file is skipped whole: its service runs on the defaults.
    assert overrides.resolve("checkout-api", "memory").params == {}


def test_a_broken_override_skips_its_whole_file_not_just_itself(tmp_path: Path) -> None:
    text = PAYMENTS + """
  payments_bad:
    scope: {service: payments-api, metric: cpu}
    reason: r
    analyzers: {trend: {finding_rules: {min_slope_percent: 500}}}
"""
    overrides = _load(tmp_path, **{"payments-team.yml": text})

    assert overrides.overrides == []
    assert "payments_bad" in overrides.errors[0].message


def test_the_same_override_id_or_scope_in_two_files_skips_the_later_file(tmp_path: Path) -> None:
    same_scope = PAYMENTS.replace("payments_trend", "other_name")
    overrides = _load(tmp_path, **{"a.yml": PAYMENTS, "b.yml": PAYMENTS, "c.yml": same_scope})

    assert [override.source_file for override in overrides.overrides] == ["a.yml"]
    assert [error.source_file for error in overrides.errors] == ["b.yml", "c.yml"]
    assert "already defined in a.yml" in overrides.errors[0].message
    assert "same scope as 'payments_trend'" in overrides.errors[1].message


def test_every_tunable_path_exists_in_the_shipped_settings() -> None:
    """A tunable must name a setting config/analyzers.yaml really has, or overriding it does nothing."""
    import yaml

    shipped = yaml.safe_load((PROJECT_ROOT / "config" / "analyzers.yaml").read_text())["analysis"]["analyzers"]
    for registration in REGISTRATIONS:
        for path in registration.tunable:
            current = shipped[registration.analyzer_id]
            for part in path.split("."):
                current = current[part]
            spec = registration.tunable[path]
            assert spec["min"] <= current <= spec["max"], f"{registration.analyzer_id}.{path} default {current} is outside its range"


def test_the_shipped_example_is_a_valid_overrides_file(tmp_path: Path) -> None:
    example = (PROJECT_ROOT / "config" / "analyzer_overrides.d" / "example.yml.example").read_text()
    overrides = _load(tmp_path, **{"payments-team.yml": example})

    assert overrides.errors == []
    resolution = overrides.resolve("payments-api", "process_resident_memory_bytes")
    assert resolution.params == {"trend": {"finding_rules": {"min_slope_percent": 5}}}
    assert (resolution.max_analyzers, resolution.disabled) == (2, {"stumpy"})


def test_the_example_is_not_loaded_until_it_is_copied_to_a_yml_file() -> None:
    assert load_overrides(PROJECT_ROOT / "config" / "analyzer_overrides.d", REGISTRATIONS).overrides == []
