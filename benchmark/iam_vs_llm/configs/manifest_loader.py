from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class PricingConfig:
    input_per_mtok: float
    output_per_mtok: float

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculates financial cost in USD from input/output token counts."""
        cost_in = (input_tokens / 1_000_000.0) * self.input_per_mtok
        cost_out = (output_tokens / 1_000_000.0) * self.output_per_mtok
        return round(cost_in + cost_out, 6)


@dataclass(slots=True)
class ModelRunConfig:
    model_id: str
    provider: str
    temperature: float
    max_turns: int
    pricing: PricingConfig
    name: str = ""


@dataclass(slots=True)
class BenchmarkManifest:
    random_seed: int
    state_isolation: bool
    baseline_a: ModelRunConfig
    baseline_b: ModelRunConfig
    iam_advisor: ModelRunConfig
    judge: ModelRunConfig


ENV_VAR_PATTERN = re.compile(r"\$\{([^:-]+)(?::-([^}]*))?\}")


def _expand_env_vars(raw: Any) -> Any:
    """Recursively replaces ${VAR:-default} patterns with environment values."""
    if isinstance(raw, str):
        def replace(match: re.Match) -> str:
            var_name = match.group(1)
            default_val = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default_val)
        return ENV_VAR_PATTERN.sub(replace, raw)
    elif isinstance(raw, dict):
        return {k: _expand_env_vars(v) for k, v in raw.items()}
    elif isinstance(raw, list):
        return [_expand_env_vars(item) for item in raw]
    return raw


def load_manifest(manifest_path: str | Path | None = None) -> BenchmarkManifest:
    """Loads and resolves the benchmark configuration manifest."""
    if manifest_path is None:
        manifest_path = Path(__file__).parent / "benchmark_manifest.yaml"
    path = Path(manifest_path)

    if not path.exists():
        raise FileNotFoundError(f"Manifest file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    resolved = _expand_env_vars(data)

    harness = resolved.get("harness", {})
    baselines = resolved.get("baselines", {})
    a_data = baselines.get("baseline_a", {})
    b_data = baselines.get("baseline_b", {})
    iam_data = resolved.get("iam_system", {})
    judge_data = resolved.get("judge", {})

    baseline_a = ModelRunConfig(
        name=str(a_data.get("name", "Baseline A (Direct ReAct LLM Agent)")),
        model_id=str(a_data.get("model_id", "mock-frontier-sre")),
        provider=str(a_data.get("provider", "mock")),
        temperature=float(a_data.get("temperature", 0.0)),
        max_turns=int(a_data.get("max_turns", 10)),
        pricing=PricingConfig(
            input_per_mtok=float(a_data.get("pricing_per_mtok", {}).get("input", 3.0)),
            output_per_mtok=float(a_data.get("pricing_per_mtok", {}).get("output", 15.0)),
        ),
    )

    baseline_b = ModelRunConfig(
        name=str(b_data.get("name", "Baseline B (Signals-Augmented LLM Agent)")),
        model_id=str(b_data.get("model_id", "mock-frontier-sre")),
        provider=str(b_data.get("provider", "mock")),
        temperature=float(b_data.get("temperature", 0.0)),
        max_turns=int(b_data.get("max_turns", 6)),
        pricing=PricingConfig(
            input_per_mtok=float(b_data.get("pricing_per_mtok", {}).get("input", 3.0)),
            output_per_mtok=float(b_data.get("pricing_per_mtok", {}).get("output", 15.0)),
        ),
    )

    iam_advisor = ModelRunConfig(
        name=str(iam_data.get("name", "IAM Incident Advisor")),
        model_id=str(iam_data.get("advisor_model_id", "gemma-2-9b-it")),
        provider=str(iam_data.get("provider", "local")),
        temperature=float(iam_data.get("temperature", 0.0)),
        max_turns=1,
        pricing=PricingConfig(
            input_per_mtok=float(iam_data.get("pricing_per_mtok", {}).get("input", 0.20)),
            output_per_mtok=float(iam_data.get("pricing_per_mtok", {}).get("output", 0.20)),
        ),
    )

    judge = ModelRunConfig(
        name=str(judge_data.get("name", "Benchmark Evaluation Judge")),
        model_id=str(judge_data.get("model_id", "mock-judge-evaluator")),
        provider=str(judge_data.get("provider", "mock")),
        temperature=float(judge_data.get("temperature", 0.0)),
        max_turns=1,
        pricing=PricingConfig(
            input_per_mtok=float(judge_data.get("pricing_per_mtok", {}).get("input", 2.50)),
            output_per_mtok=float(judge_data.get("pricing_per_mtok", {}).get("output", 10.00)),
        ),
    )

    return BenchmarkManifest(
        random_seed=int(harness.get("random_seed", 42)),
        state_isolation=bool(harness.get("state_isolation", True)),
        baseline_a=baseline_a,
        baseline_b=baseline_b,
        iam_advisor=iam_advisor,
        judge=judge,
    )
