# AeroIntel — Demo Guide

A scripted 5-minute walk-through for a live demo or screenshare.
Covers every major capability in a natural flow with no backtracking.

---

## Prerequisites

Both servers must be running before the demo starts.

```bash
# Terminal 1 — backend
cd aerointel/backend
source venv/bin/activate       # Windows: venv\Scripts\activate
uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd aerointel/frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) and wait for the map
to populate (about 5 seconds on first WebSocket push).

**Tip:** IsolationForest needs 30+ aircraft in state before meaningful
anomaly scoring begins. Wait at least 3 pipeline cycles (~3 min) before
demoing anomaly detection. The cycle counter is visible at `/api/stats`.

---

## Demo Script

### 1. Map loads — 8,000+ aircraft globally (0:00 – 0:45)

The map opens on a dark globe with colored aircraft markers.

**Say:** "This is a live view of global airspace right now. The data
comes directly from ADS-B transponders via the OpenSky Network — roughly
8,000 aircraft in flight at any given time."

Point out the color coding in the Layers panel (left):
- Blue dots: commercial airline traffic
- Red dots: military aircraft (sourced separately from adsb.lol)
- Gray: private / general aviation
- Green/teal: helicopters

**Say:** "The pipeline runs every 60 seconds: fetch raw ADS-B
state vectors, run them through a Kalman filter for position smoothing,
cluster trajectories with DBSCAN, then score every aircraft with
IsolationForest."

**Status bar callouts:**
- `LIVE` indicator and timestamp show last WebSocket push
- Aircraft count, military count on the right side of the bar

---

### 2. Toggle anomaly overlay — red markers appear (0:45 – 1:30)

Make sure the "Anomalies" layer toggle is on (left panel).
Red/orange markers appear over aircraft flagged by IsolationForest.

**Say:** "IsolationForest is an unsupervised anomaly detector. It has no
labeled examples of 'bad' behavior. Instead, it scores aircraft based on
how hard they are to isolate from the population using random
partitioning — the harder to isolate, the more normal. Anomalies isolate
quickly."

**Say:** "The features it scores are: altitude delta, speed delta,
heading variance over a 5-minute window, time since last telemetry
contact, and squawk code change frequency."

**Honest framing:** "These aren't necessarily emergencies — IsolationForest
flags the statistically unusual. It's a signal for further inspection,
not an alarm. We'd need domain-labeled data to measure precision/recall.
What the system does is surface candidates a human analyst would want to
look at."

---

### 3. Click an anomalous aircraft — DetailPanel opens (1:30 – 2:30)

Click any aircraft with an anomaly marker (orange/red badge).
The DetailPanel slides up from the bottom.

**Walk through the telemetry row:**
- ALT, SPD, HDG, V/S, SQUAWK, STATUS, ANOMALY SCORE, PATTERN

**Say:** "The anomaly score is the IsolationForest decision score —
lower is more anomalous. Values below 0 are flagged."

**Wait for the Claude explanation to load** (~2–4 seconds):

**Say:** "The 'Asking Claude...' indicator means the frontend just called
`GET /api/aircraft/{icao}/explain`. The backend retrieves the raw feature
vector for this aircraft and sends it to Claude with a structured prompt
that asks for a plain-English interpretation of why the combination of
signals is unusual."

**Read the explanation aloud** or let it speak for itself.

**Say:** "This is the key architectural decision: rule-based systems catch
known patterns. Claude catches unknown unknowns — it can synthesize
'unusual altitude + unusual routing + squawk code that changed twice in
90 seconds' into something a domain expert can act on."

---

### 4. IntelPanel — natural language query (2:30 – 3:30)

Click the **AI INTEL** button (top-right of status bar).
The IntelPanel slides in from the right.

Type in the query box:

```
Show military aircraft above 30,000 feet
```

Press Enter or click the filter button.

**Say:** "The query goes to `POST /api/query`. Claude parses the intent
and returns structured filter parameters — min altitude, category filter,
etc. — and the frontend applies them client-side so it's instant."

The map and aircraft count update immediately. The active filter strip
appears in the status bar showing the parsed filter explanation.

Try a second query:

```
Show aircraft with unusual flight paths
```

**Say:** "This filters to aircraft with a pattern label — DBSCAN found
them executing holding patterns or racetrack orbits instead of direct
routing."

Clear the filter with the `[×]` button.

---

### 5. Situation Summary — Claude narrates the viewport (3:30 – 4:30)

Pan/zoom the map to a region of interest (a busy corridor like the
North Atlantic, or a militarily active area).

In the IntelPanel, click **Situation Summary**.

**Say:** "The summary endpoint pulls all aircraft in the current map
viewport — the bounds update on every pan and zoom — and sends them
as a JSON array to Claude. Claude narrates what it sees: traffic
density, notable patterns, any anomalies, military activity."

**While it loads (~3–5 seconds):**

**Say:** "This is not a canned summary. The content depends on what's
actually visible in the viewport right now. Every time you move the map,
you'd get a different summary."

Read the summary aloud or let the audience read it.

---

### 6. Pipeline stats callout (4:30 – 5:00)

Navigate to [http://localhost:8000/api/stats](http://localhost:8000/api/stats)
or read the values off the status bar.

**Call out:**
- `aircraft_count`: total aircraft in state (~7,000–9,000 depending on time of day)
- `pipeline_duration_s`: full pipeline cycle time (typically 4–6 seconds)
- `anomaly_count`: aircraft flagged by IsolationForest (grows after cycle 3)
- `pattern_count`: DBSCAN-detected patterns (holding, racetrack, orbit)
- `pipeline_cycle`: number of complete cycles since server start

**Say:** "7,000+ aircraft. Full pipeline — Kalman, DBSCAN, IsolationForest — in under 6 seconds.
That's the throughput story: we're not sampling, we're scoring the whole fleet every 3 minutes."

---

## Talking Points by Audience

### For ML-focused interviewers

- Kalman filter: constant-velocity model with `[lat, lon, dlat, dlon]` state vector.
  Covariance matrix handles dropped packets without extrapolating stale positions.
- DBSCAN over K-means: no k to specify, Haversine metric handles geographic distances,
  identifies arbitrary shapes (holding ovals, racetracks).
- IsolationForest: no labeled anomalies required. Efficient for streaming data.
  Scores are population-relative — anomaly rate is meaningful as a percentage of fleet,
  not as an absolute recall metric.

### For full-stack / systems interviewers

- FastAPI + asyncio: pipeline runs on a background task, WebSocket push on the same
  event loop. No threads blocked.
- WebSocket push vs. polling: 60-second polling would mean a round trip per client
  per cycle. WebSocket push decouples delivery from fetch frequency.
- Rate limit handling: OpenSky 429/503 emits `pipeline_warning` in WebSocket metadata,
  cached state served so frontend never goes blank.

### For applied AI / LLM interviewers

- On-demand explain vs. pipeline-integrated: calling Claude for every anomalous aircraft
  every 60 seconds would cost ~$0.10/cycle and add 3s to pipeline latency. On-demand
  means Claude only runs when a human is actually looking at the aircraft.
- Structured JSON prompting: the LLM receives a typed feature dict, not free text.
  This makes outputs more consistent and easier to evaluate.
- No hallucination risk in NL query path: Claude returns structured filter params,
  which are validated against known fields before being applied. A hallucinated field
  name is just a no-op filter, not a UI crash.

---

## Known Demo Risks

| Risk | Mitigation |
|------|------------|
| OpenSky rate limit during demo | Register a free account; set `OPENSKY_USERNAME` / `OPENSKY_PASSWORD` in `.env` (400 req/day vs. 100) |
| IsolationForest shows 0 anomalies | Start servers 5+ min before demo; check cycle count via `/api/stats` |
| Claude explanation slow | Expected 2–4s; reassure audience this is on-demand only, not per-aircraft per-cycle |
| adsb.lol returns empty military | Low-activity periods happen; toggle military layer off and focus on commercial anomalies |
| No anomalies visible | Use NL query "Show aircraft with unusual flight paths" to demo pattern detection instead |

---

## Quick Reference

| URL | Purpose |
|-----|---------|
| `http://localhost:3000` | Frontend dashboard |
| `http://localhost:8000/api/stats` | Pipeline diagnostics (JSON) |
| `http://localhost:8000/api/aircraft` | Full GeoJSON snapshot |
| `http://localhost:8000/docs` | FastAPI auto-docs (Swagger UI) |
| `ws://localhost:8000/ws/aircraft` | WebSocket endpoint |
