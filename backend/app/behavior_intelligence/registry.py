from __future__ import annotations

from .loader import load_definitions
from .models import BehaviorDefinition


class BehaviorDefinitionRegistry:
    def __init__(self, definitions: list[BehaviorDefinition]):
        self._definitions = {definition.id: definition for definition in definitions}

    @classmethod
    def from_file(cls, config_path: str) -> "BehaviorDefinitionRegistry":
        return cls(load_definitions(config_path))

    def list_enabled(self) -> list[BehaviorDefinition]:
        return [definition for definition in self._definitions.values() if definition.enabled]

    def get(self, definition_id: str) -> BehaviorDefinition | None:
        return self._definitions.get(definition_id)
