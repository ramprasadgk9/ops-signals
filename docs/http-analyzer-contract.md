# HTTP Analyzers: Connect Your Own Model

An HTTP analyzer is a detector that runs as your own web service instead of as Python code inside
Ops Signals. Ops Signals sends it the metric data, and it replies with what it found. The findings
then appear next to those from the built-in analyzers.

**You don't need this to use Ops Signals.** The built-in analyzers work out of the box, and nothing
here changes them. Use an HTTP analyzer when you already have a model or detection service, such as
a forecasting model, an internal ML service or a vendor API, and want its results in Ops Signals
without adding its code or dependencies to Ops Signals.

**You run the service.** Ops Signals doesn't host, download or install any model. It only calls the
URL you give it. A heavy model (for example one that needs PyTorch) stays in its own container, and
only people who want it run it.

## Try it in 5 minutes

1. Start the example service. It uses only the Python standard library:

   ```bash
   python examples/http_analyzer/service.py --port 9100
   ```

2. In the web UI, open **Experiments → Add Analyzer → Add Analyzer** and choose **I have a hosted
   API or model**.
3. Fill in:
   - **Analyzer ID**: `example_remote`
   - **Analyze URL**: `http://localhost:9100/analyze`
   - **Health Check URL**: `http://localhost:9100/health`
   - **Supported profiles** and **scoring rules**: when the router should pick it (see
     [Choosing when it runs](#choosing-when-it-runs)).
4. **Save Draft**, then **Promote**. File writes must be enabled
   (`OPS_SIGNALS_ALLOW_FILE_WRITES=true`).
5. Run the **Execution Test**. It calls the health check, then sends sample data to the Analyze URL
   and reports how many signals came back, or exactly what went wrong.

If Ops Signals runs in Docker, `localhost` is the container itself. Use the service's name on the
Docker network, or `host.docker.internal` for a service on your machine.

## How it works

1. During an analysis the router decides which analyzers to run, using the profiles and scoring rules
   you set. An HTTP analyzer competes for a slot like any other analyzer.
2. When it's picked, Ops Signals sends one `POST` to the Analyze URL with every series in the
   analysis window.
3. Your service replies with a list of findings.
4. Each finding becomes a signal. It is scored, grouped into findings, shown in the UI and
   remembered, exactly like a built-in analyzer's signal.

**When the service is down, slow or replies badly**, that run lists the analyzer as failed, with
the reason (for example `Could not reach HTTP analyzer 'example_remote' at http://…: Connection
refused`). The other analyzers still run and their findings are kept. Nothing retries
automatically; the next run tries again.

Ops Signals makes no network call when it starts or when it lists analyzers, only when an analysis
runs or you press Execution Test.

## Request

`POST <analyze_url>` with `Content-Type: application/json`:

```json
{
  "contract_version": 1,
  "analyzer_id": "example_remote",
  "params": {"threshold": 6},
  "series": [
    {
      "series_id": "0",
      "metric_name": "http_request_duration_ms",
      "service": "checkout",
      "env": "prod",
      "timestamps": ["2026-10-01T00:00:00Z", "2026-10-01T00:05:00Z"],
      "values": [101.2, null]
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `contract_version` | Always `1` for this format. A future breaking change would use a new number. |
| `analyzer_id` | The ID you registered, so one service can serve several analyzers. |
| `params` | The analyzer's `runtime_params` from its registration, if any. |
| `series` | One entry per metric, service and environment, in time order. |
| `series[].series_id` | `"0"`, `"1"`, …; echo it back on each finding. |
| `series[].timestamps` | ISO 8601, UTC. |
| `series[].values` | Numbers. `null` means the value was missing at that time. |

If an API key is configured, it is sent as `Authorization: Bearer <key>`.

## Reply

HTTP `200` with a JSON object that has a `findings` list. An empty list means "nothing found".
Return only real detections: every finding you return is treated as one.

```json
{
  "findings": [
    {
      "series_id": "0",
      "signal_type": "anomaly",
      "severity": "high",
      "confidence": 0.9,
      "start_time": "2026-10-01T04:10:00Z",
      "end_time": "2026-10-01T04:25:00Z",
      "summary": "Latency reached 400 ms against a typical 100 ms.",
      "evidence": {"max_abs_zscore": 7.4, "model": "my-model-v2"}
    }
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `start_time` | Yes | ISO 8601. A time without a zone is read as UTC. |
| `summary` | Yes | One sentence shown to users. Say what happened, with numbers. |
| `series_id` | When more than one series was sent | Which series the finding is about. |
| `end_time` | No | Defaults to `start_time`. |
| `signal_type` | No | `anomaly` (default), `baseline_shift`, `trend`, `forecast` or `pattern_discovery`. Behavior rules and finding categories use this. |
| `severity` | No | `low`, `medium` (default) or `high`. |
| `confidence` | No | 0 to 1, default 0.5. Values outside the range are clipped. |
| `evidence` | No | Any JSON object, shown with the finding. |

Some `evidence` keys also feed the importance score the same way built-in analyzers' do:
`max_abs_zscore` for `anomaly`, `percent_change` for `baseline_shift`, and `slope_percent` for
`trend`. Without them a finding still appears, with a middle importance.

A reply that breaks these rules fails the run for this analyzer, with a message naming the finding
and the field, for example `finding 0: severity 'urgent' is not one of ['high', 'low', 'medium']`.

**Health check** (optional): `GET <health_check_url>` should return any `2xx`. Execution Test calls
it first.

## Registering without the UI

Add a file to `config/analyzer_registry.d/`, then restart the backend:

```yaml
analyzers:
  example_remote:
    display_name: Example Remote Analyzer
    http:
      analyze_url: http://models.internal:9100/analyze
      health_check_url: http://models.internal:9100/health
      timeout_seconds: 30
      api_key_env: EXAMPLE_REMOTE_API_KEY
    runtime_params:
      threshold: 6
    router:
      supported_profiles: [anomaly, spike]
      eligibility_rules: {min_samples: 30}
      scoring_rules:
        base: 0.3
        rules:
          - {metric: spikiness, gte: 0.4, add: 0.4}
```

| Setting | Default | Meaning |
|---|---|---|
| `analyze_url` | required | Must start with `http://` or `https://`. |
| `health_check_url` | none | Used by Execution Test. |
| `timeout_seconds` | 30 | How long one call may take. Analyzers run one after another, so a slow service delays the whole analysis. |
| `api_key_env` | none | Name of an environment variable on the Ops Signals server that holds the key. Preferred: the key never goes into a file. |
| `api_key` | none | The key itself, in the file. Avoid unless the file is protected. |

## Choosing when it runs

The router only runs your analyzer when its profiles and scoring rules make it one of the top picks
for a series. This is the same mechanism as for every other analyzer; see
[`analyzer-recommendation.md`](analyzer-recommendation.md). Two things to know:

- Adding an analyzer can change which analyzers run. A high-scoring HTTP analyzer may take a slot
  that a built-in analyzer used to get. Use **Which analyzer fits?** to check this on your own
  metrics before relying on it.
- To run it on every analysis regardless of score, set `always_run: true`. Do this only for a
  fast, cheap service.

## Things to check before production

- **Speed.** Each analysis waits for the reply. Keep the service well under `timeout_seconds` for a
  full window of data.
- **Network access.** Only people who can write files on the Ops Signals server (or use the wizard
  with file writes enabled) can register an analyzer, and therefore choose which URL the backend
  calls. Keep `OPS_SIGNALS_ALLOW_FILE_WRITES` off in production unless you need it.
- **Data leaving the server.** The service receives your metric names, service names and values.
  Point it only at a service you trust with that data.
- **False alarms.** A new detector can add noise. Compare its findings with what you know happened
  before you let it page anyone.
