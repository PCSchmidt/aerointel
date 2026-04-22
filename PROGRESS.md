# AeroIntel — Progress

## Status: Phase 5 In Progress (Phase 4 complete)

**Backend:** Fly.io (`aerointel-backend.fly.dev`) — migrated from Railway April 2026
**Frontend:** Vercel (`aerointel-git-main-chris-schmidts-projects.vercel.app`)

> Railway project deleted (April 22, 2026). CI/CD now via GitHub Actions → Fly.io on push to main.

---

## Phase 0: Scaffold Resolution — DONE

- [x] Copied `files/main.py` → `backend/main.py`
- [x] Copied `files/kalman.py` → `backend/services/kalman.py`
- [x] Copied `files/clustering.py` → `backend/services/clustering.py`
- [x] Copied `files/anomaly.py` → `backend/services/anomaly.py`
- [x] Copied `files/opensky.py` → `backend/services/opensky.py`
- [x] Copied `files/llm.py` → `backend/services/llm.py`
- [x] Copied `files/schemas.py` → `backend/models/schemas.py`
- [x] Copied `files/requirements.txt` → `backend/requirements.txt`
- [x] Copied `files/Dockerfile` → `backend/Dockerfile`
- [x] Copied `files/docker-compose.yml` → `docker-compose.yml`
- [x] Copied `files/package.json` → `frontend/package.json`
- [x] Created `backend/services/__init__.py`
- [x] Created `frontend/next.config.js`
- [x] Created `frontend/tailwind.config.js`
- [x] Created `frontend/tsconfig.json`
- [x] Created `frontend/postcss.config.js`
- [x] Created `frontend/Dockerfile`

## Phase 1: Design Language — DONE

- [x] `globals.css` — Manrope as body font, emerald accent #34d399, removed CRT scanline overlay
- [x] `layout.tsx` — Manrope + Cormorant Garamond + JetBrains Mono imports wired
- [x] `page.tsx` — removed `rounded-lg` from layer controls, updated loading indicator
- [x] `StatusBar.tsx` — font-sans on UI labels, emerald accent, square button corners
- [x] `IntelPanel.tsx` — font-sans on section headers, emerald accent, square inputs

## Phase 2: Wiring + Smoke Test — DONE

- [x] `backend/.env.example` already present in scaffold
- [x] `backend/models/__init__.py` already present in scaffold
- [x] Updated `backend/requirements.txt` to `>=` version pins (Python 3.13 compatibility)
- [x] Install backend dependencies: `pip install filterpy anthropic apscheduler pyproj shapely`
- [x] Install frontend dependencies: `npm install` (468 packages)
- [x] Backend smoke test: `uvicorn main:app --reload --port 8000`
- [x] Frontend smoke test: `npm run dev` (Next.js 14.2.5 ready in 2.4s)
- [x] Confirmed data flow: 7,865 aircraft tracked, 114 military, 0 errors
- [x] WebSocket push confirmed (pipeline cycle 2, 5.3s duration)

**Smoke test results (April 20, 2026):**
```json
{
  "aircraft_count": 7865,
  "military_count": 114,
  "anomaly_count": 0,
  "pipeline_duration_s": 5.3,
  "pipeline_errors": []
}
```

## Phase 3: Feature Completion — DONE

- [x] Add `get_feature_dict()` to `AnomalyDetectionService` (exposes feature vector per aircraft)
- [x] Add `GET /api/aircraft/{icao24}/explain` endpoint — on-demand LLM explanation via `asyncio.to_thread()`
- [x] Add `fetchAnomalyExplanation()` to `frontend/src/lib/api.ts`
- [x] Wire viewport bounds through Map → page.tsx → IntelPanel (real bounds replace hardcoded region)
- [x] `DetailPanel` auto-fetches LLM explanation when anomalous aircraft is selected

## Phase 4: Portfolio Integration — IN PROGRESS

### 4.1 Evidence Capture
- [ ] Run live system 30+ min (wait for IsolationForest to reach 30+ aircraft)
- [ ] Capture 3–5 anomaly explanation JSON responses → `evidence/anomaly-explanations/`
- [ ] Screenshot live map with pattern + anomaly layers visible
- [ ] Record pipeline stats snapshot for card metrics

### 4.2 README Enhancements
- [x] Add Mermaid architecture diagram
- [x] Add "Performance" section with measured numbers from evidence capture
- [x] Fix duplicate "OpenSky rate limit" entry in Known Limitations

### 4.3 Rate Limit Graceful Degradation
- [x] Backend: detect OpenSky 429/503, emit `pipeline_warning`, serve cached state
- [x] Frontend: show "Airspace data cached" banner when `pipeline_warning` present

### 4.4 DEMO_GUIDE.md
- [x] Write scripted 5-minute demo walk-through (map → anomalies → DetailPanel → NL query → Situation Summary)

### 4.5 Portfolio Card Copy
- [x] Draft card entry for `index.astro` (title, tags, metrics, description)
- [x] Draft full entry for `projects.astro` (problem, approach, impact)
- [ ] Verify all metrics match evidence (run 4.1 evidence capture, then confirm counts)

### 4.6 Deploy + Portfolio Integration
- [x] Create `backend/railway.toml` (startCommand, healthcheck, restart policy)
- [x] Create `frontend/vercel.json` (env var declarations)
- [x] Populate `frontend/.env.local.example` with local/production URL instructions
- [x] Add `/health` endpoint to backend
- [x] Push repo to GitHub (PCSchmidt/aerointel)
- [x] Deploy backend to Railway ~~(deprecated — migrated to Fly.io)~~
- [x] Migrate backend from Railway to Fly.io (OpenSky ConnectTimeout fix)
- [x] Disable Vercel Authentication (demo is public)
- [x] Deploy frontend to Vercel
- [x] Add card to `index.astro` (featured)
- [x] Add full entry to `projects.astro`
- [ ] Pin repo in GitHub profile README
- [ ] Update "Currently Exploring" chip on portfolio

## Phase 5: Intel Panel Enhancements — IN PROGRESS

### 5.1 Fleet Analytics (A1) — DONE
- [x] Poll `/api/stats` every 30s in IntelPanel
- [x] Show aircraft / military / anomaly / pattern counts with color coding
- [x] Show Kalman-tracked count and pipeline duration
- [x] Show pipeline warning banner when backend sets `pipeline_warning`
- [x] Add `cluster_tracked` and `pipeline_warning` fields to `PipelineStats` interface

### 5.2 IsolationForest Feature Vector (A2) — DONE
- [x] Store full `AnomalyExplanation` response in DetailPanel (was: explanation string only)
- [x] Display 6 feature rows (altitude delta, speed delta, heading variance, vertical rate, update gap, squawk changed) above Claude narrative
- [x] Update DEMO_GUIDE.md with Fleet Analytics and feature vector walk-through

### 5.3 Evidence Capture (A4) — DONE
- [x] Run live system 30+ min and capture anomaly explanation JSON responses
- [x] Saved 4 explanation JSONs to `evidence/anomaly-explanations/` (adff72, 480446/GRZLY71, 3b75f1/MET51, 3b776d/CVEX28)
- [x] Saved 7 pipeline stats snapshots to `evidence/pipeline-stats/`
- [x] Added `?force=true` param to `/api/aircraft/{icao24}/explain` for evidence capture on sub-threshold aircraft
- [ ] Screenshot map with Fleet Analytics panel visible
- [ ] Confirm portfolio card metrics match evidence

### 5.4 Pattern Drill-Down (A3)
- [ ] Make pattern count in Fleet Analytics clickable
- [ ] Filter aircraft list to `pattern_label !== null` and display in panel
