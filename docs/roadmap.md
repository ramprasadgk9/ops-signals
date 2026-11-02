# Roadmap

What's planned, nearest first. For where this is all heading and why, see [`vision.md`](vision.md).

## Near-Term

- add and update analyzers from feedback: missed problems, false alarms and symptoms teams had to
  spot by hand
- refine case lifecycle UX
- improve retrieval filtering
- expand documentation around evaluation and releases

## Mid-Term

- more reusable operational memory patterns
- richer case comparison
- better review flows for investigation and RCA
- multi-source Prometheus backends (Mimir, Thanos):
  - ~~scope analysis by cluster, and tell apart series that differ only by `cluster` or other external labels~~ (done)
  - ~~ignore HA replica labels (`__replica__`, `prometheus_replica`) so duplicated series aren't counted twice~~ (done)
  - ~~several connections, one per Mimir tenant, with a connection picker in the Configure panel~~ (done)

- adoption by companies with many teams: ~~Setup check~~ (done), plugin sign-in through Grafana,
  roles, login modes, team ownership (see [`adoption-roadmap.md`](adoption-roadmap.md))

- Grafana plugin in Grafana's plugin catalog: create-plugin build, signing, submission (see
  [`grafana-plugin-roadmap.md`](grafana-plugin-roadmap.md))

## Long-Term

- deeper evaluation tooling
- richer extensibility for analyzers and capabilities
- better support for iterative operational learning
- suggested playbooks built from the steps that fixed past cases, with a person approving each step
- warn when a known problem starts to look like it's happening again, before anyone is paged
- share what one team learned with other teams that hit the same problem
- Kubernetes and cloud-provider ingestion; ITSM/automation and generic external-system consumers -
  see [Roadmap (Not Yet Implemented)](architecture.md#roadmap-not-yet-implemented)
