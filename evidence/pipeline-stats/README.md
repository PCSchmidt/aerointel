# Pipeline Stats Snapshots

JSON responses from `GET /api/stats`, captured during live system runs.
Populate portfolio card `metrics[]` from these values.

Key fields for the card:
- `aircraft_count` — total aircraft tracked
- `military_count` — military aircraft visible
- `anomaly_count` — aircraft flagged by IsolationForest
- `pattern_count` — DBSCAN-detected patterns
- `pipeline_duration_s` — full pipeline cycle time
- `pipeline_cycle` — cycle number (use as denominator for anomaly rate)

Naming convention: `snapshot-YYYYMMDD-HHMM.json`
