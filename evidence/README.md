# AeroIntel Evidence

Artifacts captured during live system operation for portfolio documentation.

## Directory layout

```
evidence/
├── anomaly-explanations/   Raw JSON responses from /api/aircraft/{icao}/explain
├── screenshots/            Live map screenshots (anomaly overlay, pattern overlay)
├── pipeline-stats/         Snapshots of /api/stats JSON for card metrics
└── README.md               This file
```

## Capture procedure

### Anomaly explanations
Wait for IsolationForest to score 30+ aircraft (~3 pipeline cycles, ~9 min after server start).
For each anomalous aircraft you want to capture:

```bash
curl http://localhost:8000/api/aircraft/{icao24}/explain > evidence/anomaly-explanations/{icao24}.json
```

Save 3–5 representative examples covering different anomaly types
(altitude deviation, speed deviation, squawk change, combined signals).

### Pipeline stats snapshot
```bash
curl http://localhost:8000/api/stats | python -m json.tool > evidence/pipeline-stats/snapshot-$(date +%Y%m%d-%H%M).json
```

### Screenshots
Capture with browser DevTools (F12 → device toolbar → full page) or OS screenshot tool.
Name format: `screenshots/map-anomaly-overlay-YYYYMMDD.png`

## Usage in portfolio card

The `metrics[]` array in the portfolio card must be populated from real values
captured here — no placeholder numbers. Pull from `pipeline-stats/` snapshots.
