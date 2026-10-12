from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .models import BehaviorCondition, BehaviorDefinition, BehaviorInput, BehaviorOutput
from .validator import BehaviorDefinitionValidator

logger = logging.getLogger(__name__)


def _parse_definitions(raw: dict, source_file: str) -> list[BehaviorDefinition]:
    defs = raw.get("behavior_definitions", {}) or {}
    out: list[BehaviorDefinition] = []
    for definition_id, details in defs.items():
        inputs = [
            BehaviorInput(
                alias=item["alias"],
                metric_name=item["metric_name"],
                analyzers=list(item.get("analyzers", [])),
                aliases=list(item.get("aliases", []) or []),
            )
            for item in details.get("inputs", [])
        ]
        conditions = {
            key: [BehaviorCondition(fact=cond["fact"], operator=cond["operator"], value=cond["value"]) for cond in details.get("conditions", {}).get(key, [])]
            for key in ("all", "any")
        }
        output = details.get("output", {})
        out.append(
            BehaviorDefinition(
                id=definition_id,
                enabled=bool(details.get("enabled", True)),
                version=int(details.get("version", 1)),
                title=details.get("title", definition_id),
                description=details.get("description", ""),
                scope=dict(details.get("scope", {})),
                inputs=inputs,
                conditions=conditions,
                correlation=dict(details.get("correlation", {})),
                output=BehaviorOutput(
                    category=output.get("category", "behavior"),
                    severity=output.get("severity", "medium"),
                    title=output.get("title", details.get("title", definition_id)),
                    summary=output.get("summary", ""),
                    evidence=list(output.get("evidence", [])),
                ),
                source_file=source_file,
            )
        )
    return out


def _load_file(path: Path) -> list[BehaviorDefinition]:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return _parse_definitions(raw, source_file=path.name)


def load_definitions(config_path: str | Path, *, validate: bool = True) -> list[BehaviorDefinition]:
    """Loads behavior definitions from either a single YAML file (backward-compatible) or a
    directory of *.yml/*.yaml "pack" files (see config/behavior_definitions.d/ — lets a user or a
    third-party pack drop in more patterns without editing one shared file). A definition that
    fails validation is skipped with a logged warning rather than crashing the whole app or
    silently loading something broken; a duplicate id across files is likewise skipped with a
    warning, keeping the first one loaded (directory iteration order)."""
    path = Path(config_path)
    if not path.exists():
        return []

    if path.is_dir():
        files = sorted([*path.glob("*.yml"), *path.glob("*.yaml")])
    else:
        files = [path]

    seen_ids: set[str] = set()
    out: list[BehaviorDefinition] = []
    for file_path in files:
        try:
            candidates = _load_file(file_path)
        except (yaml.YAMLError, OSError, KeyError) as exc:
            logger.warning("behavior_definitions: failed to load %s: %s", file_path, exc)
            continue
        for definition in candidates:
            if definition.id in seen_ids:
                logger.warning(
                    "behavior_definitions: duplicate id '%s' in %s — keeping the first one loaded, skipping this one",
                    definition.id,
                    file_path,
                )
                continue
            if validate:
                errors = BehaviorDefinitionValidator.validate(definition)
                if errors:
                    logger.warning(
                        "behavior_definitions: skipping invalid definition '%s' in %s: %s",
                        definition.id,
                        file_path,
                        "; ".join(errors),
                    )
                    continue
            seen_ids.add(definition.id)
            out.append(definition)
    return out
