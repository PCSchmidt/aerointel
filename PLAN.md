# AeroIntel — Build Plan

Real-time aviation intelligence dashboard. Public ADS-B telemetry processed
through a Kalman filter, DBSCAN pattern detector, and IsolationForest anomaly
scorer. Claude API surfaces natural language query parsing and situation summaries.

## Stack

- **Frontend**: Next.js 14 + MapLibre GL (CARTO Dark Matter basemap) + Tailwind CSS
- **Backend**: FastAPI + Python 3.11, async data pipeline
- **ML**: filterpy Kalman filter, scikit-learn DBSCAN + IsolationForest
- **LLM**: Anthropic Claude claude-sonnet-4-6
- **Data**: OpenSky Network REST (commercial/private), adsb.lol (military)
- **Deploy**: Vercel (frontend) + Fly.io (backend)

## Design Standard

Matches the portfolio at pcschmidt.github.io:
- Fonts: Manrope (UI/labels), Cormorant Garamond (display headings), JetBrains Mono (data values only)
- Canvas: #0a0c0f dark background
- Accent: #34d399 emerald (interactive elements, live indicators)
- Border radius: 0 everywhere except `.rounded-full` dot indicators
- No CRT effects, no monospace as primary font

## Phases

### Phase 0: Scaffold Resolution
Destination files were created as empty stubs. Source content lives in `files/`.
Task: copy 11 files from `files/` to their destinations, then create 6 missing
boilerplate config files from scratch.

**Files to copy (files/ → destination):**
- `files/main.py` → `backend/main.py`
- `files/kalman.py` → `backend/services/kalman.py`
- `files/clustering.py` → `backend/services/clustering.py`
- `files/anomaly.py` → `backend/services/anomaly.py`
- `files/opensky.py` → `backend/services/opensky.py`
- `files/llm.py` → `backend/services/llm.py`
- `files/schemas.py` → `backend/models/schemas.py`
- `files/requirements.txt` → `backend/requirements.txt`
- `files/Dockerfile` → `backend/Dockerfile`
- `files/docker-compose.yml` → `docker-compose.yml`
- `files/package.json` → `frontend/package.json`

**Files to create from scratch:**
- `backend/services/__init__.py` — empty Python package marker
- `frontend/next.config.js` — webpack canvas alias for MapLibre SSR
- `frontend/tailwind.config.js` — dark mode, border-radius 0, font family config
- `frontend/tsconfig.json` — Next.js standard with @/ path alias
- `frontend/postcss.config.js` — tailwindcss + autoprefixer
- `frontend/Dockerfile` — Node 20 Alpine multi-stage build

### Phase 1: Design Language Alignment
Scaffold uses terminal/CRT aesthetic (JetBrains Mono everywhere, #00ff88 neon, scanlines).
Portfolio standard is clean dark-mode UI (Manrope primary, emerald accent, square corners).

**Files to update:**
- `frontend/src/app/globals.css` — replace fonts, update accent color, remove CRT
- `frontend/src/app/layout.tsx` — swap JetBrains Mono import for Manrope + Cormorant
- `frontend/src/app/page.tsx` — remove `rounded-lg`, update loading indicator color
- `frontend/src/components/StatusBar.tsx` — font-sans for UI labels, emerald accent
- `frontend/src/components/IntelPanel.tsx` — same treatment, remove rounded from inputs

### Phase 2: Wiring + Smoke Test — DONE
- Both files already existed in scaffold
- `requirements.txt` pinned versions changed to `>=` to support Python 3.13
- Missing packages installed: `filterpy anthropic apscheduler pyproj shapely`
- Smoke test confirmed: 7,865 aircraft, 114 military, 5.3s pipeline, 0 errors
- Frontend: Next.js 14.2.5 ready in 2.4s at http://localhost:3000

### Phase 3: Feature Completion — DONE
- Added `GET /api/aircraft/{icao24}/explain` endpoint (on-demand, not pipeline-integrated)
  - Rationale: pipeline-level LLM calls per anomalous aircraft every 60s would be slow and costly;
    on-demand is faster for the user and only triggers when they inspect an aircraft
- Added `AnomalyDetectionService.get_feature_dict()` to expose feature vector for LLM prompt
- Viewport bounds threaded: Map `moveend` → page.tsx state → IntelPanel props → `fetchRegionSummary`
- `DetailPanel` auto-fetches explanation on mount when `has_anomaly` is true

### Phase 4: Portfolio Integration

Phase 4 is the difference between a working app and a portfolio signal. Every other featured
project at pcschmidt.github.io has quantitative evidence, a problem/approach/impact write-up,
and a scripted demo. AeroIntel needs the same.

**4.1 — Evidence Capture** *(must happen before card goes live — no placeholder metrics)*
- Run live system 30+ min until IsolationForest has 30+ aircraft in state
- Capture 3–5 anomaly explanation JSON responses from `/api/aircraft/{icao24}/explain`
  → save to `evidence/anomaly-explanations/`
- Screenshot live map with pattern + anomaly layers both visible
- Record pipeline stats snapshot (aircraft_count, anomaly_count, pipeline_duration_s)

**4.2 — README Enhancements**
- Add Mermaid architecture diagram: OpenSky/adsb.lol → FastAPI pipeline →
  Kalman → DBSCAN → IsolationForest → WebSocket → Next.js → Claude API
- Add "Performance" section with measured numbers from evidence capture
- Fix: duplicate "OpenSky rate limit" entry in Known Limitations
- Clarify rate limit math: 100 anon req/day at 60s polling ≈ 90 min before exhaustion;
  free registered account gives 400/day — worth doing before live demo

**4.3 — Rate Limit Graceful Degradation** *(removes demo-killing failure mode)*
- Backend: detect OpenSky 429/503, emit `pipeline_warning` in WebSocket message,
  continue serving cached aircraft state instead of crashing
- Frontend: show subtle "Airspace data cached (OpenSky rate limited)" banner
  when `pipeline_warning` is present in WebSocket state

**4.4 — DEMO_GUIDE.md** *(scripted 5-minute narrative, not just setup docs)*
- Step 1: Map loads → 8,000+ aircraft visible, explain color coding
- Step 2: Toggle anomaly overlay → red markers appear
- Step 3: Click anomalous aircraft → DetailPanel → Claude explanation loads
- Step 4: IntelPanel NL query: "Show military aircraft above FL300"
- Step 5: Situation Summary → Claude narrates current airspace in viewport
- Step 6: Pipeline stats callout (cycle time, aircraft count, anomaly rate)

**4.5 — Portfolio Card Copy** *(draft content, then add to site)*
- Card for `index.astro` (featured) and full entry for `projects.astro`
- Tags: Python, FastAPI, Kalman Filter, DBSCAN, IsolationForest, Claude API,
  Next.js, MapLibre GL, WebSocket
- Metrics: populate from Phase 4.1 (real numbers, not placeholders)
- problem: ADS-B telemetry is noisy and high-volume; anomaly detection without
  ground-truth labels requires unsupervised approaches
- approach: constant-velocity Kalman filter → DBSCAN haversine clustering →
  IsolationForest multivariate scoring → Claude synthesizes weak signals
  into plain-English explanations
- impact: live demo + pipeline throughput + example anomaly explanations from evidence/
- Honest framing: IsolationForest "flags X% of aircraft for review" — no ground truth

**4.6 — Deploy + Portfolio Integration** *(last step)*
- Push repo to GitHub (PCSchmidt/aerointel)
- Deploy backend to Railway; deploy frontend to Vercel
- Add card to `index.astro` + full entry to `projects.astro` with live demo URL
- Pin aerointel in GitHub profile README
- Update "Currently Exploring" chip on portfolio (open item 3.2)

**Stretch goal:** "Kalman filtering for noisy ADS-B telemetry" Thinking article —
the README Engineering Decisions section is already an outline; bridges applied
math background to ML engineering with concrete code examples.

## Environment Variables

```
# backend/.env
ANTHROPIC_API_KEY=sk-ant-...
OPENSKY_USERNAME=           # optional — higher rate limits
OPENSKY_PASSWORD=           # optional
CORS_ORIGINS=http://localhost:3000
```

## Known Limitations (as built)

- OpenSky anonymous rate limit: 100 requests/day; at 60s polling that is ~90 min of live data
  before exhaustion — a free registered account gives 400/day and removes this as a demo risk
- adsb.lol military data can go stale during low activity periods
- IsolationForest needs 30+ aircraft in the fleet before meaningful anomaly scoring starts
- LLM explanation is on-demand via `/api/aircraft/{icao}/explain` (not pipeline-integrated)
