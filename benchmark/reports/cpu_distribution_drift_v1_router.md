# Router Benchmark Report: cpu_distribution_drift_v1

- Status: `GAP`
- Recommended: `[]`
- Optional: `[]`
- Not recommended: `['ruptures', 'stumpy', 'prophet', 'river', 'kats', 'darts', 'alibi_detect', 'trend_regression', 'adtk', 'pyod']`

## Checks

- FAIL `required_recommended_present`
- PASS `forbidden_recommended_absent`
- PASS `required_analyzers_eligible`
- FAIL `required_detected_profiles_present`
- PASS `forbidden_detected_profiles_absent`

Missing required recommendations: `['alibi_detect']`

Missing detected profiles: `['distribution_drift']`

Documented gap: `Router does not yet extract distribution_drift/drift profiles, so Alibi Detect cannot be uniquely validated from this batch CSV.`
