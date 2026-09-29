"""Fixed subsets of the public datasets for fast runs while developing a change.

    .venv/bin/python -m benchmark.run_all --sample dev     # minutes: try an idea
    .venv/bin/python -m benchmark.run_all --sample check   # ~1 hour: does it hold on data it wasn't designed on?

- dev: the data a change may be designed and tuned on.
- check: held out. Never used to design a change - only to confirm one - so a fix can't be shaped
  to fit it.

Final evidence always comes from a full run (no --sample). The lists were drawn once, with a
seeded random choice (random.Random(2026)), and frozen here so they can never drift towards cases a
change happens to do well on. TCPD, the router scenarios and the behavior scenarios are small and
always run in full.
"""

from __future__ import annotations

SAMPLES: dict[str, dict[str, list]] = {
    "dev": {
        "nab": [
            "artificialWithAnomaly/art_daily_jumpsup.csv",
            "realAWSCloudwatch/ec2_disk_write_bytes_c0d644.csv",
            "realAdExchange/exchange-4_cpc_results.csv",
            "realTraffic/TravelTime_387.csv",
            "realTweets/Twitter_volume_KO.csv",
        ],
        # SMD's group 1 servers are the design servers.
        "smd": ["machine-1-1", "machine-1-2", "machine-1-3"],
        "ucr": [3, 26, 74, 116, 126, 174, 176, 209, 210, 229],
    },
    "check": {
        "nab": [
            "artificialWithAnomaly/art_daily_jumpsdown.csv",
            "realAWSCloudwatch/ec2_cpu_utilization_825cc2.csv",
            "realAdExchange/exchange-2_cpc_results.csv",
            "realKnownCause/ambient_temperature_system_failure.csv",
            "realKnownCause/nyc_taxi.csv",
            "realKnownCause/rogue_agent_key_hold.csv",
            "realKnownCause/rogue_agent_key_updown.csv",
            "realTraffic/TravelTime_451.csv",
            "realTraffic/occupancy_6005.csv",
            "realTweets/Twitter_volume_FB.csv",
        ],
        # Drawn from SMD's groups 2 and 3 only, so no design server is in it.
        "smd": ["machine-2-1", "machine-2-3", "machine-2-4", "machine-2-8", "machine-3-4"],
        "ucr": [
            8, 21, 24, 25, 32, 39, 56, 67, 69, 77, 78, 83, 84, 91, 93, 95, 97, 98, 100, 105, 106, 111, 112, 122, 123,
            128, 131, 133, 135, 137, 140, 143, 147, 148, 150, 153, 155, 159, 169, 171, 188, 189, 191, 193, 198, 200,
            216, 218, 241, 248,
        ],
    },
}


def subset(sample: str | None, suite: str) -> list | None:
    """The series to run for `suite` under `sample`, or None for every series."""
    if not sample:
        return None
    if sample not in SAMPLES:
        raise ValueError(f"unknown sample {sample!r}; expected one of {sorted(SAMPLES)}")
    return SAMPLES[sample].get(suite)
