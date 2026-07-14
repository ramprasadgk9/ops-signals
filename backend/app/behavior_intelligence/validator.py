from __future__ import annotations

from .models import BehaviorDefinition


class BehaviorDefinitionValidator:
    @staticmethod
    def validate(definition: BehaviorDefinition) -> list[str]:
        errors: list[str] = []
        if not definition.inputs:
            errors.append("definition must declare at least one input")
        if not definition.output.title:
            errors.append("definition must declare an output title")
        return errors
