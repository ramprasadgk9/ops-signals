from __future__ import annotations

from .fact_catalog import FACT_KEYS, fact_root
from .models import BehaviorDefinition

SUPPORTED_OPERATORS = {"equals", "greater_than", "less_than", "contains"}
KNOWN_SEVERITIES = {"low", "medium", "high", "critical"}


class BehaviorDefinitionValidator:
    """Checks a definition against the fact catalog, declared inputs, and supported operators —
    so a typo'd fact path or an undeclared alias fails loudly at validate/load time instead of
    silently never matching (confirmed before this existed: a bad fact path just made
    evaluate_condition() return None/False forever, with no signal anything was wrong)."""

    @staticmethod
    def validate(definition: BehaviorDefinition, known_analyzer_ids: set[str] | None = None) -> list[str]:
        errors: list[str] = []

        if not definition.id:
            errors.append("definition must have a non-empty id")
        if not definition.inputs:
            errors.append("definition must declare at least one input")
        if not definition.output.title:
            errors.append("definition must declare an output title")
        if definition.output.severity and definition.output.severity not in KNOWN_SEVERITIES:
            errors.append(
                f"output.severity '{definition.output.severity}' is not one of {sorted(KNOWN_SEVERITIES)}"
            )

        declared_aliases = {item.alias for item in definition.inputs}
        for item in definition.inputs:
            if not item.alias:
                errors.append("every input must declare a non-empty alias")
            if not item.metric_name:
                errors.append(f"input '{item.alias}' must declare a metric_name")
            if known_analyzer_ids is not None:
                unknown = [a for a in item.analyzers if a not in known_analyzer_ids]
                if unknown:
                    errors.append(f"input '{item.alias}' references unknown analyzer id(s): {unknown}")

        for group_name, conditions in definition.conditions.items():
            if group_name not in ("all", "any"):
                errors.append(f"condition group '{group_name}' must be 'all' or 'any'")
                continue
            for condition in conditions:
                if condition.operator not in SUPPORTED_OPERATORS:
                    errors.append(
                        f"condition on '{condition.fact}' uses unsupported operator '{condition.operator}' "
                        f"(supported: {sorted(SUPPORTED_OPERATORS)})"
                    )
                alias, _, rest = condition.fact.partition(".")
                if not rest:
                    errors.append(f"condition fact '{condition.fact}' must be in the form <alias>.<fact_path>")
                    continue
                if alias not in declared_aliases:
                    errors.append(f"condition references alias '{alias}', which is not declared in inputs")
                root = fact_root(condition.fact)
                if root not in FACT_KEYS:
                    errors.append(
                        f"condition fact '{condition.fact}' is not a known fact "
                        f"(see GET /api/behavior-definitions/facts for the full list)"
                    )

        if not definition.conditions.get("all") and not definition.conditions.get("any"):
            errors.append("definition must declare at least one condition, under 'all' or 'any'")

        return errors

    @staticmethod
    def warnings(definition: BehaviorDefinition) -> list[str]:
        warnings: list[str] = []
        if len(definition.inputs) < 2:
            warnings.append(
                "a behavior definition with only one input is really just re-labeling a single "
                "analyzer signal — behaviors are most useful when they correlate 2+ metrics"
            )
        if not definition.correlation.get("max_time_gap") and not definition.correlation.get("minimum_overlap"):
            warnings.append("no correlation window configured — inputs will only match if their signal windows overlap exactly")
        return warnings
