# Anomaly Explanation Samples

JSON responses from `GET /api/aircraft/{icao24}/explain`.
Each file is named `{icao24}.json`.

Capture format:
```json
{
  "icao24": "abc123",
  "callsign": "UAL1234",
  "explanation": "...",
  "anomaly_score": -0.142,
  "features": {
    "alt_delta_ft": 2400,
    "speed_delta_kts": 87,
    "heading_variance_deg": 34.2,
    "squawk_changes": 2,
    "time_since_contact_s": 45
  }
}
```
