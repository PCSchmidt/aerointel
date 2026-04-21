# AeroIntel — Progress

## Status: Phase 3 In Progress

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
- [ ] Push repo to GitHub (PCSchmidt/aerointel)
- [ ] Deploy backend to Railway
- [ ] Deploy frontend to Vercel
- [ ] Add card to `index.astro` (featured) — done, pending repo push
- [ ] Add full entry to `projects.astro` — done, pending repo push
- [ ] Pin repo in GitHub profile README
- [ ] Update "Currently Exploring" chip on portfolio
