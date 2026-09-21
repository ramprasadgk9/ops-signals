from __future__ import annotations

import re
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Protocol

import yaml

from backend.app.autonomous.schemas import (
    AnalysisScope,
    CustomMetricConstraints,
    DiscoveredMetric,
    ExecutionPolicy,
    MetricAnalysisPlan,
    MetricClassification,
    MetricConcept,
    MetricDiscoveryResult,
    MetricPlanItem,
    MonitoringCategory,
    PlannedAnalysisRequest,
    QueryStrategy,
    ResolvedAnalysisScope,
)

LABEL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class MetricMetadataProvider(Protocol):
    def discover_metric_metadata(
        self,
        *,
        service_label: str,
        namespace_label: str,
        environment_label: str,
        limit: int,
        scope_selector: str = "",
        max_series_per_metric: int = 10,
    ) -> list[DiscoveredMetric] | MetricDiscoveryResult:
        ...


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def validate_label_name(label: str | None, field_name: str = "label") -> str | None:
    if label is None or label == "":
        return None
    if not LABEL_NAME_RE.fullmatch(label):
        raise ValueError(f"{field_name} must be a valid Prometheus label name")
    return label


def escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def build_label_matcher(label: str | None, values: list[str], *, all_values: bool = False) -> str | None:
    label = validate_label_name(label)
    if not label or all_values or not values:
        return None
    deduped = sorted(dict.fromkeys(value for value in values if value))
    if not deduped:
        return None
    if len(deduped) == 1:
        return f'{label}="{escape_label_value(deduped[0])}"'
    escaped = "|".join(re.escape(value) for value in deduped)
    return f'{label}=~"{escape_label_value(escaped)}"'


def build_scope_selector(scope: AnalysisScope) -> str:
    matchers = [
        build_label_matcher(scope.environment_label, [scope.environment or ""], all_values=not scope.environment or scope.environment.lower() == "all"),
        build_label_matcher(scope.service_label, scope.services, all_values=scope.all_services),
        build_label_matcher(scope.namespace_label, scope.namespaces, all_values=scope.all_namespaces),
    ]
    return "{" + ",".join(matcher for matcher in matchers if matcher) + "}"


def _merge_selector_matchers(selector: str, matchers: list[str]) -> str:
    existing = selector[1:-1].strip() if selector.startswith("{") and selector.endswith("}") else ""
    parts = [part for part in [existing, *matchers] if part]
    return "{" + ",".join(parts) + "}"


def _enum_list(enum_cls, values: list[str]) -> list:
    result = []
    for value in values or []:
        try:
            result.append(enum_cls(value))
        except ValueError:
            continue
    return result


class AutonomousConfig:
    def __init__(
        self,
        taxonomy_path: Path | None = None,
        knowledge_path: Path | None = None,
    ) -> None:
        root = repo_root()
        self.taxonomy_path = taxonomy_path or root / "config" / "autonomous_metric_taxonomy.yaml"
        self.knowledge_path = knowledge_path or root / "config" / "prometheus_metric_knowledge.yaml"
        self.taxonomy = self._load_yaml(self.taxonomy_path)
        self.knowledge = self._load_yaml(self.knowledge_path)

    def concepts_for_categories(self, categories: list[MonitoringCategory]) -> list[MetricConcept]:
        concepts: list[MetricConcept] = []
        for category in categories:
            raw = self.taxonomy.get(category.value, {}).get("concepts", {})
            for concept_name in raw.keys():
                try:
                    concept = MetricConcept(concept_name)
                except ValueError:
                    continue
                if concept not in concepts:
                    concepts.append(concept)
        return concepts

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open() as handle:
            loaded = yaml.safe_load(handle) or {}
        return loaded if isinstance(loaded, dict) else {}


class MetricDiscoveryService:
    def __init__(self, provider: MetricMetadataProvider, metadata_limit: int = 5000) -> None:
        self.provider = provider
        self.metadata_limit = metadata_limit

    def discover(self, scope: AnalysisScope) -> tuple[ResolvedAnalysisScope, list[DiscoveredMetric]]:
        warnings: list[str] = []
        try:
            validate_label_name(scope.service_label, "service_label")
            validate_label_name(scope.namespace_label, "namespace_label")
            validate_label_name(scope.environment_label, "environment_label")
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        scope_selector = build_scope_selector(scope)
        effective_limit = scope.metadata_limit if scope.metadata_limit else self.metadata_limit
        max_series_per_metric = scope.max_series_per_metric if scope.max_series_per_metric else 10

        try:
            discovery_output = self.provider.discover_metric_metadata(
                service_label=scope.service_label,
                namespace_label=scope.namespace_label or "namespace",
                environment_label=scope.environment_label or "env",
                limit=effective_limit,
                scope_selector=scope_selector,
                max_series_per_metric=max_series_per_metric,
            )
        except TypeError:
            discovery_output = self.provider.discover_metric_metadata(
                service_label=scope.service_label,
                namespace_label=scope.namespace_label or "namespace",
                environment_label=scope.environment_label or "env",
                limit=effective_limit,
            )

        if isinstance(discovery_output, MetricDiscoveryResult):
            discovered = discovery_output.metrics
            series_discovered = discovery_output.series_discovered
            series_available = discovery_output.series_available
            truncated = discovery_output.truncated
            starved_metrics = discovery_output.starved_metrics
        else:
            discovered = discovery_output
            series_discovered = len(discovered)
            series_available = None
            truncated = len(discovered) >= effective_limit
            starved_metrics = []

        if truncated:
            if starved_metrics:
                warnings.append(
                    f"Metric discovery was truncated by the metadata safety limit ({effective_limit}). "
                    f"{len(starved_metrics)} metric names were excluded from discovery."
                )
            else:
                warnings.append(f"Metric discovery was truncated by the metadata safety limit ({effective_limit}).")

        if not discovered:
            return (
                ResolvedAnalysisScope(
                    discovered_metric_count=0,
                    series_discovered=series_discovered,
                    series_available=series_available,
                    truncated=truncated,
                    starved_metrics_count=len(starved_metrics),
                    starved_metrics=starved_metrics[:50],
                    warnings=warnings + ["No metric metadata was discovered for the selected datasource."],
                    filters_applied=self._filters(scope),
                    label_mapping=self._label_mapping(scope),
                    selector=scope_selector,
                ),
                [],
            )

        services = sorted({value for metric in discovered for value in (metric.services or ([metric.service] if metric.service else [])) if value})
        namespaces = sorted({value for metric in discovered for value in (metric.namespaces or ([metric.namespace] if metric.namespace else [])) if value})
        environments = sorted({value for metric in discovered for value in (metric.environments or ([metric.environment] if metric.environment else [])) if value})
        if not services:
            warnings.append(f'No services were found using label "{scope.service_label}".')
        if not namespaces and not scope.all_namespaces:
            warnings.append(f'No namespaces were found using label "{scope.namespace_label}".')
        if scope.environment and scope.environment.lower() != "all" and not environments:
            warnings.append(f'No environments were found using label "{scope.environment_label}".')

        filtered = discovered
        if scope.environment and scope.environment.lower() != "all":
            filtered = [metric for metric in filtered if not metric.environments or scope.environment in metric.environments]
        if not scope.all_services:
            selected_services = set(scope.services)
            filtered = [metric for metric in filtered if selected_services.intersection(metric.services or ([metric.service] if metric.service else []))]
        if not scope.all_namespaces:
            selected_namespaces = set(scope.namespaces)
            filtered = [metric for metric in filtered if selected_namespaces.intersection(metric.namespaces or ([metric.namespace] if metric.namespace else []))]

        filtered = self._deduplicate(filtered)
        if not filtered:
            warnings.append("No metrics matched the selected scope.")
        resolved_services = sorted({value for metric in filtered for value in (metric.services or ([metric.service] if metric.service else [])) if value})
        resolved_namespaces = sorted({value for metric in filtered for value in (metric.namespaces or ([metric.namespace] if metric.namespace else [])) if value})
        return (
            ResolvedAnalysisScope(
                resolved_services=resolved_services,
                resolved_namespaces=resolved_namespaces,
                resolved_environment=None if not scope.environment or scope.environment.lower() == "all" else scope.environment,
                discovered_metric_count=len(filtered),
                series_discovered=series_discovered,
                series_available=series_available,
                truncated=truncated,
                starved_metrics_count=len(starved_metrics),
                starved_metrics=starved_metrics[:50],
                warnings=warnings,
                filters_applied=self._filters(scope),
                label_mapping=self._label_mapping(scope),
                selector=scope_selector,
            ),
            filtered,
        )

    @staticmethod
    def _deduplicate(metrics: list[DiscoveredMetric]) -> list[DiscoveredMetric]:
        deduped: OrderedDict[tuple[str, str | None, str | None, str | None], DiscoveredMetric] = OrderedDict()
        for metric in metrics:
            key = (metric.metric_name, metric.service, metric.namespace, metric.environment)
            if key not in deduped:
                deduped[key] = metric
            else:
                existing = deduped[key]
                existing.estimated_series_count = (existing.estimated_series_count or 1) + (metric.estimated_series_count or metric.cardinality_estimate or 1)
                existing.cardinality_estimate = existing.estimated_series_count
        return list(deduped.values())

    @staticmethod
    def _filters(scope: AnalysisScope) -> dict[str, object]:
        return {
            "environment": scope.environment,
            "services": "all" if scope.all_services else scope.services,
            "namespaces": "all" if scope.all_namespaces else scope.namespaces,
        }

    @staticmethod
    def _label_mapping(scope: AnalysisScope) -> dict[str, str | None]:
        return {
            "environment": scope.environment_label,
            "service": scope.service_label,
            "namespace": scope.namespace_label,
        }


class MetricClassificationService:
    def __init__(self, config: AutonomousConfig | None = None) -> None:
        self.config = config or AutonomousConfig()
        self.knowledge = self.config.knowledge

    def classify(
        self,
        metric: DiscoveredMetric,
        selected_categories: list[MonitoringCategory],
        custom_constraints: CustomMetricConstraints,
    ) -> MetricClassification:
        exclusion, exclusion_matched_rule = self._exclusion_reason(metric, custom_constraints)
        required_ok = self._required_labels_match(metric, custom_constraints)
        categories: list[MonitoringCategory] = []
        concepts: list[MetricConcept] = []
        confidence = 0.0
        reason: str | None = None
        matched_rule: str | None = None
        query = QueryStrategy()

        custom_include_pattern = self._matching_custom_include(metric, custom_constraints)
        if metric.metric_name in custom_constraints.explicit_metrics:
            categories = [MonitoringCategory.custom]
            concepts = [MetricConcept.custom]
            confidence = 0.99
            reason = "custom_explicit_metric"
            matched_rule = f"custom.explicit.{metric.metric_name}"
            query = QueryStrategy(aggregation=custom_constraints.aggregation or "avg", group_by=custom_constraints.group_by or ["service"])
        elif custom_include_pattern and MonitoringCategory.custom in set(selected_categories):
            categories = [MonitoringCategory.custom]
            concepts = [MetricConcept.custom]
            confidence = 0.9
            reason = "custom_include_pattern"
            matched_rule = f"custom.include.{custom_include_pattern}"
            query = QueryStrategy(aggregation=custom_constraints.aggregation or "avg", group_by=custom_constraints.group_by or ["service"])
        elif not exclusion:
            exact = self.knowledge.get("exact_metrics", {}).get(metric.metric_name)
            if isinstance(exact, dict):
                categories, concepts, query, confidence = self._classification_from_rule(exact, metric, default_confidence=1.0)
                reason = "exact_metric_mapping"
                matched_rule = f"exact_metrics.{metric.metric_name}"
            else:
                for pattern_rule in self.knowledge.get("patterns", []) or []:
                    pattern = str(pattern_rule.get("pattern", ""))
                    if pattern and (re.fullmatch(pattern, metric.metric_name) or re.search(pattern, metric.metric_name)):
                        categories, concepts, query, confidence = self._classification_from_rule(pattern_rule, metric, default_confidence=0.75)
                        reason = "metric_name_pattern"
                        matched_rule = f"patterns.{pattern}"
                        break

        if not reason and not exclusion and custom_include_pattern:
            categories = [MonitoringCategory.custom]
            concepts = [MetricConcept.custom]
            confidence = 0.9
            reason = "custom_include_pattern"
            matched_rule = f"custom.include.{custom_include_pattern}"
            query = QueryStrategy(aggregation=custom_constraints.aggregation or "avg", group_by=custom_constraints.group_by or ["service"])

        selected_categories_set = set(selected_categories)
        category_intersection = [category for category in categories if category in selected_categories_set]
        if MonitoringCategory.custom in selected_categories_set and reason in {"custom_explicit_metric", "custom_include_pattern"}:
            category_intersection = [MonitoringCategory.custom]
        selected = bool(category_intersection) and exclusion is None and required_ok
        if not required_ok:
            exclusion = "missing_required_label"
        elif not category_intersection and exclusion is None:
            # A metric matched a known rule (categories non-empty) but that category
            # isn't enabled in this policy - toggling it on would select the metric.
            # No rule matched at all - toggling a category can't fix this; the metric
            # name isn't recognized by any exact-metric or pattern rule.
            exclusion = "category_disabled" if categories else "no_matching_rule"

        return MetricClassification(
            metric_name=metric.metric_name,
            categories=category_intersection,
            would_be_category=categories,
            concepts=concepts,
            confidence=confidence if selected or categories else 0.0,
            selection_reason=reason,
            # An exclude match always wins here even if an include pattern also matched
            # (that combination is itself why the metric was excluded) - showing the
            # include pattern instead would misname the actual reason.
            matched_rule=exclusion_matched_rule if exclusion else matched_rule,
            suggested_query_strategy=query,
            selected=selected,
            exclusion_reason=exclusion,
        )

    def _classification_from_rule(
        self,
        rule: dict[str, Any],
        metric: DiscoveredMetric,
        default_confidence: float,
    ) -> tuple[list[MonitoringCategory], list[MetricConcept], QueryStrategy, float]:
        categories = _enum_list(MonitoringCategory, rule.get("categories", []))
        concepts = _enum_list(MetricConcept, rule.get("concepts", []))
        query_data = rule.get("query", {}) or {}
        query = QueryStrategy(
            transformation=str(query_data.get("transformation", "raw")),
            range=query_data.get("range"),
            quantile=query_data.get("quantile"),
            aggregation=str(query_data.get("aggregation", "avg")),
            group_by=list(query_data.get("group_by", ["service"]) or ["service"]),
        )
        metric_type = metric.metric_type or rule.get("metric_type") or rule.get("metric_type_hint")
        if metric_type == "gauge" and query.transformation == "rate":
            query.transformation = "raw"
        return categories, concepts, query, float(rule.get("confidence", default_confidence))

    def _exclusion_reason(self, metric: DiscoveredMetric, custom_constraints: CustomMetricConstraints) -> tuple[str | None, str | None]:
        """Returns (reason, matched_rule) - matched_rule names exactly which configured
        pattern/value caused the exclusion, so the UI can show it instead of just the
        generic reason category."""
        for pattern in custom_constraints.exclude_patterns:
            if re.fullmatch(pattern, metric.metric_name) or re.search(pattern, metric.metric_name):
                return "custom_exclude_pattern", f"custom.exclude.{pattern}"
        exclusions = self.knowledge.get("exclude", {})
        if metric.metric_name in set(exclusions.get("exact", []) or []):
            return "static_metadata_metric", f"static.exact.{metric.metric_name}"
        for suffix in exclusions.get("suffixes", []) or []:
            if metric.metric_name.endswith(str(suffix)):
                reason = "created_timestamp" if str(suffix) == "_created" else "static_metadata_metric"
                return reason, f"static.suffix.{suffix}"
        for pattern in exclusions.get("patterns", []) or []:
            if re.fullmatch(pattern, metric.metric_name) or re.search(pattern, metric.metric_name):
                return "static_metadata_metric", f"static.pattern.{pattern}"
        return None, None

    @staticmethod
    def _matching_custom_include(metric: DiscoveredMetric, custom_constraints: CustomMetricConstraints) -> str | None:
        for pattern in custom_constraints.include_patterns:
            if re.fullmatch(pattern, metric.metric_name) or re.search(pattern, metric.metric_name):
                return pattern
        return None

    @staticmethod
    def _required_labels_match(metric: DiscoveredMetric, custom_constraints: CustomMetricConstraints) -> bool:
        return all(metric.labels.get(key) == value for key, value in custom_constraints.required_labels.items())


class MetricQueryStrategyResolver:
    def build_promql(
        self,
        *,
        metric: DiscoveredMetric,
        classification: MetricClassification,
        resolved_scope: ResolvedAnalysisScope,
    ) -> tuple[str, str, str, list[str]]:
        strategy = classification.suggested_query_strategy
        metric_name = self._logical_metric_name(metric.metric_name, strategy.transformation)
        selector = self._selector(metric_name, self._item_scope_selector(metric, resolved_scope))
        group_by = [label for label in strategy.group_by if validate_label_name(label)]
        if not group_by:
            group_by = ["service"]
        aggregation = self._aggregation_name(strategy.aggregation, group_by)
        transformation = self._resolve_transformation(strategy.transformation, metric)

        if transformation == "histogram_quantile":
            quantile = strategy.quantile or 0.95
            bucket_selector = self._selector(self._bucket_metric_name(metric.metric_name), resolved_scope.selector)
            promql = (
                f"histogram_quantile({quantile}, "
                f"sum by (le, {', '.join(group_by)}) (rate({bucket_selector}[{strategy.range or '5m'}])))"
            )
        elif transformation == "rate":
            promql = f"{strategy.aggregation} by ({', '.join(group_by)}) (rate({selector}[{strategy.range or '5m'}]))"
        elif transformation == "increase":
            promql = f"{strategy.aggregation} by ({', '.join(group_by)}) (increase({selector}[{strategy.range or '5m'}]))"
        elif strategy.aggregation == "service_level":
            promql = f"avg by ({', '.join(group_by)}) ({selector})"
            aggregation = self._aggregation_name("avg", group_by)
        else:
            promql = f"{strategy.aggregation} by ({', '.join(group_by)}) ({selector})"

        return promql, transformation, aggregation, group_by

    @staticmethod
    def _item_scope_selector(metric: DiscoveredMetric, resolved_scope: ResolvedAnalysisScope) -> str:
        labels = resolved_scope.label_mapping
        matchers: list[str] = []
        service_label = labels.get("service")
        namespace_label = labels.get("namespace")
        environment_label = labels.get("environment")
        if service_label and metric.service and metric.labels.get(service_label) == metric.service:
            matchers.append(f'{service_label}="{escape_label_value(metric.service)}"')
        if namespace_label and metric.namespace and metric.labels.get(namespace_label) == metric.namespace:
            matchers.append(f'{namespace_label}="{escape_label_value(metric.namespace)}"')
        if environment_label and metric.environment and metric.labels.get(environment_label) == metric.environment:
            matchers.append(f'{environment_label}="{escape_label_value(metric.environment)}"')
        return _merge_selector_matchers(resolved_scope.selector, matchers)

    @staticmethod
    def _selector(metric_name: str, scope_selector: str) -> str:
        if scope_selector == "{}":
            return metric_name
        return f"{metric_name}{scope_selector}"

    @staticmethod
    def _bucket_metric_name(metric_name: str) -> str:
        if metric_name.endswith("_bucket"):
            return metric_name
        if metric_name.endswith("_seconds"):
            return f"{metric_name}_bucket"
        return f"{metric_name}_bucket"

    @staticmethod
    def _logical_metric_name(metric_name: str, transformation: str) -> str:
        if transformation == "histogram_quantile_if_bucket_else_raw" and metric_name.endswith("_bucket"):
            return metric_name
        return metric_name

    @staticmethod
    def _resolve_transformation(transformation: str, metric: DiscoveredMetric) -> str:
        metric_type = (metric.metric_type or "").lower()
        if transformation == "rate_if_counter_else_raw":
            return "rate" if metric_type == "counter" or metric.metric_name.endswith("_total") else "raw"
        if transformation == "histogram_quantile_if_bucket_else_raw":
            return "histogram_quantile" if metric.metric_name.endswith("_bucket") or "histogram" in metric_type else "raw"
        if transformation == "rate" and metric_type == "gauge":
            return "raw"
        return transformation

    @staticmethod
    def _aggregation_name(aggregation: str, group_by: list[str]) -> str:
        return f"{aggregation}_by_{'_'.join(group_by)}"


class MetricPlanBuilder:
    def __init__(self, query_resolver: MetricQueryStrategyResolver | None = None, config: AutonomousConfig | None = None) -> None:
        self.query_resolver = query_resolver or MetricQueryStrategyResolver()
        self.config = config or AutonomousConfig()

    def build(
        self,
        *,
        resolved_scope: ResolvedAnalysisScope,
        discovered_metrics: list[DiscoveredMetric],
        selected_categories: list[MonitoringCategory],
        execution: ExecutionPolicy,
        custom_constraints: CustomMetricConstraints,
        classifier: MetricClassificationService,
        datasource: str = "prometheus",
        backend: str = "grafana-stack",
    ) -> MetricAnalysisPlan:
        classified_rows: list[tuple[DiscoveredMetric, MetricClassification]] = [
            (metric, classifier.classify(metric, selected_categories, custom_constraints)) for metric in discovered_metrics
        ]
        selected_rows = [(metric, classification) for metric, classification in classified_rows if classification.selected]
        selected_rows = self._rank_and_dedupe(selected_rows)
        planned_row_ids = {
            self._row_id(metric, classification)
            for metric, classification in selected_rows[: execution.max_metrics_per_run]
        }
        selected_row_ids = {self._row_id(metric, classification) for metric, classification in selected_rows}
        selected_rank = {
            self._row_id(metric, classification): index
            for index, (metric, classification) in enumerate(selected_rows)
        }
        ordered_rows = sorted(classified_rows, key=lambda row: self._item_order(row, selected_rank, planned_row_ids))

        items: list[MetricPlanItem] = []
        budget_used = 0
        for metric, classification in ordered_rows:
            logical_key = self._logical_key(metric, classification)
            planned = False
            exclusion_reason = classification.exclusion_reason
            row_id = self._row_id(metric, classification)
            if classification.selected and row_id in selected_row_ids:
                if row_id in planned_row_ids:
                    planned = True
                    budget_used += 1
                else:
                    exclusion_reason = "budget_limit"
            elif classification.selected:
                exclusion_reason = "duplicate_lower_rank"

            promql, transformation, aggregation, group_by = self.query_resolver.build_promql(
                metric=metric,
                classification=classification,
                resolved_scope=resolved_scope,
            )
            category = classification.categories[0] if classification.categories else None
            concept = classification.concepts[0] if classification.concepts else None
            planned_request = self._planned_request(
                metric=metric,
                category=category,
                concept=concept,
                promql=promql,
                transformation=transformation,
                aggregation=aggregation,
                execution=execution,
                datasource=datasource,
                backend=backend,
                confidence=classification.confidence,
                selection_reason=classification.selection_reason,
            ) if planned else None
            items.append(
                MetricPlanItem(
                    service=metric.service,
                    namespace=metric.namespace,
                    environment=metric.environment or resolved_scope.resolved_environment,
                    metric_name=metric.metric_name,
                    category=category,
                    concept=concept,
                    concepts=classification.concepts,
                    would_be_category=classification.would_be_category,
                    metric_type=metric.metric_type,
                    selector=resolved_scope.selector,
                    transformation=transformation,
                    aggregation=aggregation,
                    aggregation_strategy=aggregation,
                    group_by=group_by,
                    promql=promql,
                    confidence=classification.confidence,
                    selection_reason=classification.selection_reason,
                    matched_rule=classification.matched_rule,
                    estimated_series_count=metric.estimated_series_count or metric.cardinality_estimate or 1,
                    planned=planned,
                    exclusion_reason=exclusion_reason,
                    analysis_window=execution.analysis_window,
                    explanation=self._explain(planned, classification.selection_reason, exclusion_reason, transformation, aggregation),
                    planned_request=planned_request,
                )
            )

        planned_count = sum(1 for item in items if item.planned)
        budget_limited = sum(1 for item in items if item.exclusion_reason == "budget_limit")
        budget_excluded = sorted(list({item.metric_name for item in items if item.exclusion_reason == "budget_limit"}))
        concepts = self.config.concepts_for_categories(selected_categories)
        warnings = list(resolved_scope.warnings)
        if budget_limited > 0:
            sample_excluded = ", ".join(budget_excluded[:5])
            more_suffix = f" (and {len(budget_excluded) - 5} more)" if len(budget_excluded) > 5 else ""
            warnings.append(
                f"Execution budget limited: {planned_count} of {len(selected_rows)} selected metric jobs planned "
                f"({budget_limited} excluded by max_metrics_per_run={execution.max_metrics_per_run}). "
                f"Excluded metrics: {sample_excluded}{more_suffix}. "
                "Every run is independent; budget-excluded metrics are not deferred to future runs."
            )
        return MetricAnalysisPlan(
            scope_summary={
                "environment": resolved_scope.resolved_environment,
                "services_resolved": resolved_scope.resolved_services,
                "namespaces_resolved": resolved_scope.resolved_namespaces,
                "services": len(resolved_scope.resolved_services),
                "namespaces": len(resolved_scope.resolved_namespaces),
                "label_mapping": resolved_scope.label_mapping,
                "selector": resolved_scope.selector,
                "series_discovered": resolved_scope.series_discovered,
                "series_available": resolved_scope.series_available,
                "truncated": resolved_scope.truncated,
                "starved_metrics_count": resolved_scope.starved_metrics_count,
                "starved_metrics": resolved_scope.starved_metrics,
                "budget_limited_jobs": budget_limited,
                "budget_excluded_metrics_count": len(budget_excluded),
                "budget_excluded_metrics": budget_excluded[:50],
            },
            monitoring_summary={
                "categories": [category.value for category in selected_categories],
                "concepts": [concept.value for concept in concepts],
            },
            total_metrics_discovered=len(discovered_metrics),
            total_metrics_classified=sum(1 for _, classification in classified_rows if classification.categories),
            total_metrics_selected=sum(1 for _, classification in classified_rows if classification.selected),
            total_metrics_excluded=max(len(items) - planned_count, 0),
            planned_jobs=planned_count,
            budget_limited_jobs=budget_limited,
            budget_excluded_metrics_count=len(budget_excluded),
            budget_excluded_metrics=budget_excluded,
            warnings=warnings,
            items=items,
        )

    def _rank_and_dedupe(
        self,
        selected_rows: list[tuple[DiscoveredMetric, MetricClassification]],
    ) -> list[tuple[DiscoveredMetric, MetricClassification]]:
        by_key: dict[tuple, list[tuple[DiscoveredMetric, MetricClassification]]] = defaultdict(list)
        for metric, classification in selected_rows:
            by_key[self._logical_key(metric, classification)].append((metric, classification))
        winners = []
        for rows in by_key.values():
            winners.append(sorted(rows, key=self._ranking_score, reverse=True)[0])
        return sorted(winners, key=self._ranking_score, reverse=True)

    @staticmethod
    def _logical_key(metric: DiscoveredMetric, classification: MetricClassification) -> tuple:
        concept = classification.concepts[0].value if classification.concepts else metric.metric_name
        category = classification.categories[0].value if classification.categories else "unclassified"
        return (metric.environment, metric.namespace, metric.service, category, concept)

    @staticmethod
    def _row_id(metric: DiscoveredMetric, classification: MetricClassification) -> tuple:
        return (
            metric.metric_name,
            metric.environment,
            metric.namespace,
            metric.service,
            tuple(category.value for category in classification.categories),
            tuple(concept.value for concept in classification.concepts),
        )

    @staticmethod
    def _ranking_score(row: tuple[DiscoveredMetric, MetricClassification]) -> tuple:
        metric, classification = row
        return (
            classification.confidence,
            MetricPlanBuilder._demo_signal_priority(metric),
            1 if metric.referenced_by_recording_rule else 0,
            1 if metric.referenced_by_alert_rule else 0,
            1 if metric.referenced_by_dashboard else 0,
            -int(metric.estimated_series_count or metric.cardinality_estimate or 1),
        )

    @staticmethod
    def _item_order(
        row: tuple[DiscoveredMetric, MetricClassification],
        selected_rank: dict[tuple, int],
        planned_row_ids: set[tuple],
    ) -> tuple[int, int]:
        row_id = MetricPlanBuilder._row_id(row[0], row[1])
        if row_id in planned_row_ids:
            return (0, selected_rank.get(row_id, 0))
        if row_id in selected_rank:
            return (1, selected_rank[row_id])
        return (2, 0)

    @staticmethod
    def _demo_signal_priority(metric: DiscoveredMetric) -> int:
        # Local demo metrics are intentionally shaped to produce visible findings
        # across rolling windows. Prefer them when a tiny preview budget is used.
        service = (metric.service or "").lower()
        if service in {"spike-lab", "trend-lab", "mixed-lab", "ruptures-lab"}:
            return 1
        return 0

    @staticmethod
    def _planned_request(
        *,
        metric: DiscoveredMetric,
        category: MonitoringCategory | None,
        concept: MetricConcept | None,
        promql: str,
        transformation: str,
        aggregation: str,
        execution: ExecutionPolicy,
        datasource: str,
        backend: str,
        confidence: float,
        selection_reason: str | None,
    ) -> PlannedAnalysisRequest:
        logical_parts = [part for part in [metric.service, concept.value if concept else None] if part]
        return PlannedAnalysisRequest(
            datasource=datasource,
            backend=backend,
            metric_identity={
                "metric_family": metric.metric_name,
                "logical_name": "_".join(logical_parts) or metric.metric_name,
                "category": category.value if category else None,
                "concept": concept.value if concept else None,
                "environment": metric.environment,
                "service": metric.service,
                "namespace": metric.namespace,
            },
            query={
                "promql": promql,
                "aggregation": aggregation,
                "transformation": transformation,
            },
            analysis_window=execution.analysis_window,
            classification_confidence=confidence,
            selection_reason=selection_reason,
            execution_options={
                "interval": execution.interval,
                "max_parallel_jobs": execution.max_parallel_jobs,
            },
        )

    @staticmethod
    def _explain(planned: bool, reason: str | None, exclusion: str | None, transformation: str, aggregation: str) -> str:
        if planned:
            if reason == "exact_metric_mapping":
                return f"Selected because this is an exact known operational metric. It will use {transformation} and {aggregation}."
            if reason == "metric_name_pattern":
                return f"Selected because the metric name matched a configured operational pattern. It will use {transformation} and {aggregation}."
            if reason and reason.startswith("custom"):
                return "Selected by custom metric constraints."
            return "Selected because it matches the selected monitoring intent."
        if exclusion == "static_metadata_metric":
            return "Excluded because this is a static metadata metric."
        if exclusion == "created_timestamp":
            return "Excluded because creation timestamps are not operational signals."
        if exclusion == "category_disabled":
            return "Matches a known operational pattern, but that monitoring category isn't enabled."
        if exclusion == "no_matching_rule":
            return "Excluded because no monitoring rule recognizes this metric name."
        if exclusion == "duplicate_lower_rank":
            return "Excluded because a higher-confidence metric represents the same logical concept."
        if exclusion == "budget_limit":
            return "Excluded because the preview budget was reached."
        if exclusion == "missing_required_label":
            return "Excluded because required labels were missing."
        if exclusion == "custom_exclude_pattern":
            return "Excluded by custom exclude pattern."
        return "Excluded from the current autonomous preview."
