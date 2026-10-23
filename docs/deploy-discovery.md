# Deploys found automatically

Findings and enriched alerts say what changed just before a problem: "started 4 min after deploy
`1.4.2`". Your CI can send deploys to `POST /api/events` ([alert-enrichment.md](alert-enrichment.md)).
Ops Signals also finds deploys in the metrics Prometheus already has, so this works before anyone
sets up CI.

## How it finds them

Every 5 minutes, Ops Signals looks at the last 6 hours on each Prometheus connection, in two ways:

1. **A new version on a `build_info` metric.** Most apps and exporters report their version as a
   metric, for example `checkout_build_info{version="1.4.2"} 1`. When a service reports a version it
   didn't report just before, that's a deploy, at the minute the new version first showed up.
   - Versions already there when the 6 hours start are not counted, since nothing says when they
     were deployed. A new install therefore doesn't fill up with old "deploys".
   - A pod restarting on the same version, or a gap in scraping, is not a deploy.
   - During a rollout old and new pods run side by side. That's one deploy.
   - Going back to an earlier version is a deploy too.
   - Works without Kubernetes.
2. **A new Kubernetes ReplicaSet** (needs kube-state-metrics). A Deployment rollout creates a new
   ReplicaSet, and `kube_replicaset_created` says when. The service is the Deployment's name. Scaling
   doesn't create a ReplicaSet, so it isn't counted. Rolling back to the previous revision reuses an
   old ReplicaSet, so the build_info way is the one that sees that.

Found deploys are stored with the deploys from CI and show in the same places: the finding's
**What changed**, the **After deploy** chip, enriched Slack alerts, and the pod breakdown. They
carry `source: ops-signals:build_info` or `ops-signals:kube_replicaset` and a description that
starts with "Found automatically". As with CI deploys, the wording says "after", never "caused by".

## Duplicates

- When the same rollout is seen both ways, it's stored once, with the app's version from build_info.
- A deploy CI already sent for the service within 10 minutes isn't stored again.
- When CI sends a deploy after one was found (CI ran late), CI's replaces it, because it says more:
  who deployed and a link.
- Two different versions found minutes apart are two deploys.
- Running every 5 minutes over the same 6 hours never stores a deploy twice.
- When the web UI and Grafana plugin backends share a database, only one of them looks at a time.

Service names come from the same labels alert enrichment uses (`service`, `job`, `app`,
`app_kubernetes_io_name`, set with `OPS_SIGNALS_ALERT_SERVICE_LABELS`). If the service name in
build_info differs from the one on your findings, list both in `OPS_SIGNALS_SERVICE_ALIASES`.

## Check it

**Settings → Setup check → Deploy events** says how many deploys were found in the last 7 days, or
that none were, or that the last search failed and why. `GET /api/events` lists them.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `OPS_SIGNALS_DEPLOY_DISCOVERY_ENABLED` | `true` | Look for deploys in Prometheus |
| `OPS_SIGNALS_DEPLOY_DISCOVERY_INTERVAL_MINUTES` | `5` | How often |
| `OPS_SIGNALS_DEPLOY_DISCOVERY_LOOKBACK_HOURS` | `6` | How far back each look goes |
| `OPS_SIGNALS_DEPLOY_DISCOVERY_VERSION_LABELS` | `version,app_version,service_version` | Labels that hold the version, tried in order |
| `OPS_SIGNALS_DEPLOY_DISCOVERY_KUBE_REPLICASETS` | `true` | Also use kube-state-metrics ReplicaSets |

Each look is two small queries per connection (one range query over `*_build_info`, grouped by
service and version, and one instant query over ReplicaSets). A query that returns more than 500
series is not used, and the Setup check says the look failed and why.

## Limits

- Only services that report a version metric, or run as Kubernetes Deployments, are covered.
  Config changes and feature flags still need CI to send them.
- The time is accurate to about a minute: when the new version was first scraped.
- Two deploys from different detectors within 10 minutes count as one.
- It doesn't know who deployed or where the pipeline run is. Send deploys from CI for that.
