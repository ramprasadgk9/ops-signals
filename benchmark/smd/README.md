# SMD harness

Scores Ops Signals on the [Server Machine Dataset](https://github.com/NetManAIOps/OmniAnomaly)
(Su et al., KDD 2019): 28 real servers from a large internet company, 38 metrics each, 5 weeks at
one-minute intervals, with every incident in the second half labeled, and for each incident the
metrics involved.

```bash
.venv/bin/python -m benchmark.run_all --suites smd
```

The first run clones the OmniAnomaly repository into `benchmark/.cache/omnianomaly` (gitignored) at
the pinned commit `7fb0e0acf89ea49908896bcc9f9e80fcfff6baf4`. Only `ServerMachineDataset/` is read;
none of OmniAnomaly's code is run. The repository is MIT-licensed.

## What runs

Each of a server's 38 metrics runs through Ops Signals on its own, as a monitored server's metrics
would, with the four methods in `benchmark/methods.py`: router picks, all analyzers, z-score only,
and a static threshold (each metric's lowest and highest value in the first half). Analyzers see the
whole series at once (batch mode), with the first half as history; alarms count only in the second
half. Replaying it causally like the NAB suite would take hundreds of thousands of pipeline runs.

The metrics are unnamed, so they're called `metric_01`..`metric_38`, numbered as the labels number
them. Behavior Intelligence's named rules can't apply; this dataset tests detection and which
metrics were involved.

## Scoring

Per incident, the way an on-call engineer would judge it (`metrics.py`):

- Alarms from any of a server's metrics within 15 minutes of each other are one alert.
- An incident is caught when an alert starts inside it. Any other alert is a false alert.
- For caught incidents, HitRate@100% and @150% (the OmniAnomaly paper's measure) check whether the
  top-ranked alarming metrics are the ones listed for the incident.
- Headline confidence threshold 0.5, fixed before scoring; the report shows every threshold.

No "point-adjust": much published SMD work counts a whole incident as detected once any minute of it
is, which lets even random scores look strong (Kim et al., AAAI 2022). Scores here aren't comparable
with point-adjusted ones.

## Label notes

Incidents come from `test_label` (per minute), as in the published evaluations.
`interpretation_label`'s ranges normally end one minute past the labeled incident. On 5 servers they
disagree beyond that (a shifted range, a labeled incident missing from the list, extra overlapping
ranges), so each incident takes the metrics of every range that overlaps it.
The dataset doesn't say the first half is incident-free.
