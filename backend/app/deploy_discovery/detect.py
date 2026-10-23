"""Turn Prometheus answers into deploys. No database and no network here: service.py queries, and
these functions only read the answers.

Two ways to see a deploy:

- **build_info**: most apps and exporters report `<name>_build_info{version="1.4.2"} 1`. A version
  that shows up where another one was before is a deploy. Versions already there when the window
  starts are not: nothing says when they started.
- **ReplicaSets** (kube-state-metrics): a Deployment rollout creates a new ReplicaSet, and
  `kube_replicaset_created` is its creation time. Scaling doesn't create one, so it isn't counted.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

SOURCE_PREFIX = "ops-signals:"
BUILD_INFO_SOURCE = f"{SOURCE_PREFIX}build_info"
REPLICASET_SOURCE = f"{SOURCE_PREFIX}kube_replicaset"


@dataclass(frozen=True)
class DetectedDeploy:
    service: str
    timestamp: datetime
    version: str | None
    cluster: str | None
    source: str
    description: str
    attributes: dict = field(default_factory=dict, compare=False)


def build_info_query(service_labels: list[str], version_labels: list[str], cluster_label: str | None) -> str:
    """One series per service, version and cluster, whatever the number of pods. Labels a series
    doesn't have come back empty, so listing extra ones is harmless."""
    labels = list(dict.fromkeys([*service_labels, *version_labels, *([cluster_label] if cluster_label else [])]))
    return f'max by ({", ".join(labels)}) ({{__name__=~".+_build_info"}})'


def replicaset_query(cluster_label: str | None) -> str:
    by = "namespace, replicaset" + (f", {cluster_label}" if cluster_label else "")
    return (
        f"max by ({by}, owner_name) (kube_replicaset_created * on ({by}) group_left (owner_name) "
        f'max by ({by}, owner_name) (kube_replicaset_owner{{owner_kind="Deployment"}}))'
    )


def _first(labels: dict[str, str], keys: list[str]) -> str | None:
    for key in keys:
        value = (labels.get(key) or "").strip()
        if value:
            return value
    return None


def _time(value: object) -> datetime:
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def build_info_deploys(
    result: list[dict],
    *,
    service_labels: list[str],
    version_labels: list[str],
    cluster_label: str | None,
) -> list[DetectedDeploy]:
    """Deploys in a range query's result (build_info_query). A version is deployed at the first step
    it is reported while it wasn't among the versions reported at the step before (gaps skipped). So a pod restarting on the same
    version, or a scrape gap, is not a deploy, and a rollout where old and new run side by side is one."""
    present: dict[tuple[str, str | None], dict[datetime, set[str]]] = defaultdict(lambda: defaultdict(set))
    for series in result:
        labels = series.get("metric") or {}
        service = _first(labels, service_labels)
        version = _first(labels, version_labels)
        if not service or not version:
            continue
        cluster = _first(labels, [cluster_label]) if cluster_label else None
        for timestamp, _ in series.get("values") or []:
            present[(service, cluster)][_time(timestamp)].add(version)

    deploys: list[DetectedDeploy] = []
    for (service, cluster), by_time in present.items():
        times = sorted(by_time)
        # The first versions seen are where the window starts (or where a new service or scrape
        # config started reporting): nothing says when they were deployed.
        last = by_time[times[0]]
        for moment in times[1:]:
            current = by_time[moment]
            for version in sorted(current - last):
                previous = sorted(last)
                deploys.append(DetectedDeploy(
                    service=service,
                    timestamp=moment,
                    version=version,
                    cluster=cluster,
                    source=BUILD_INFO_SOURCE,
                    description=f"Found automatically: version changed from {', '.join(previous)} to {version} (build_info metric).",
                    attributes={"previous_versions": previous},
                ))
            last = current
    return sorted(deploys, key=lambda deploy: deploy.timestamp)


def replicaset_deploys(result: list[dict], *, cluster_label: str | None, since: datetime, until: datetime) -> list[DetectedDeploy]:
    """New ReplicaSets in an instant query's result (replicaset_query), created between since and until."""
    deploys: list[DetectedDeploy] = []
    for series in result:
        labels = series.get("metric") or {}
        owner = (labels.get("owner_name") or "").strip()
        replicaset = (labels.get("replicaset") or "").strip()
        value = series.get("value") or []
        if not owner or not replicaset or len(value) != 2:
            continue
        try:
            created = _time(value[1])
        except (TypeError, ValueError):
            continue
        if not since <= created <= until:
            continue
        namespace = (labels.get("namespace") or "").strip()
        where = f" in namespace {namespace}" if namespace else ""
        deploys.append(DetectedDeploy(
            service=owner,
            timestamp=created,
            version=replicaset,
            cluster=_first(labels, [cluster_label]) if cluster_label else None,
            source=REPLICASET_SOURCE,
            description=f"Found automatically: Kubernetes rolled out a new ReplicaSet {replicaset}{where}.",
            attributes={"namespace": namespace or None, "replicaset": replicaset},
        ))
    return sorted(deploys, key=lambda deploy: deploy.timestamp)
