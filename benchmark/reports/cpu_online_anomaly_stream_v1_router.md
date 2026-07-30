# Router Benchmark Report: cpu_online_anomaly_stream_v1

- Status: `GAP`
- Recommended: `['stumpy', 'prophet', 'darts', 'adtk', 'pyod']`
- Optional: `['ruptures', 'river', 'kats']`
- Not recommended: `['alibi_detect', 'trend_regression']`

## Checks

- FAIL `required_recommended_present`
- FAIL `forbidden_recommended_absent`
- PASS `required_analyzers_eligible`
- PASS `required_detected_profiles_present`
- PASS `forbidden_detected_profiles_absent`

Missing required recommendations: `['river']`

Incorrectly recommended analyzers: `['stumpy', 'prophet', 'darts']`

Unexpected optional analyzers: `['kats', 'river', 'ruptures']`

Documented gap: `Router input does not yet support execution_mode=streaming or online update requirements, so River cannot be required from batch values alone.`
