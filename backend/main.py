"""
main.py
-------
AeroIntel FastAPI backend.

Orchestrates the full data pipeline:
    OpenSky/adsb.lol → Kalman filter → DBSCAN clustering →
    IsolationForest anomaly detection → Aircraft state store

Exposes REST endpoints and a WebSocket for the Next.js frontend.

Endpoints:
    GET  /api/aircraft          All current aircraft (GeoJSON)
    GET  /api/aircraft/{icao}   Single aircraft detail
    POST /api/query             Natural language query → filter
    POST /api/summary           Region situation summary
    GET  /api/stats             Pipeline diagnostics
    WS   /ws/aircraft           WebSocket push (60s cycle)
"""

import asyncio
import time
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings

from models.schemas import (
    Aircraft, RegionQuery, NLQueryRequest, NLQueryResponse,
    SituationSummary, AircraftAnomaly
)
from services.opensky import (
    OpenSkyService,
    ADSBLolService,
    _raw_to_aircraft,
    OpenSkyRateLimitError,
    OpenSkyFetchError,
)
from services.kalman import KalmanFilterService
from services.clustering import TrajectoryClusteringService
from services.anomaly import AnomalyDetectionService
from services.llm import LLMService


# ── Settings ─────────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    anthropic_api_key: str = ""
    opensky_client_id: str = ""
    opensky_client_secret: str = ""
    opensky_username: str = ""
    opensky_password: str = ""
    cors_origins: str = "http://localhost:3000"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()


def _opensky_auth_mode() -> str:
    return "oauth" if (opensky_svc.client_id and opensky_svc.client_secret) else "anonymous"


# ── Application state ─────────────────────────────────────────────────────────

class AppState:
    """Thread-safe in-memory state store for the current aircraft snapshot."""

    def __init__(self):
        self.aircraft: dict[str, Aircraft] = {}       # icao24 → Aircraft
        self.anomaly_scores: dict[str, float] = {}    # icao24 → score (persists across cycles)
        self.pattern_labels: dict[str, str] = {}      # icao24 → pattern (persists across cycles)
        self.last_pipeline_run: float = 0.0
        self.pipeline_duration_s: float = 0.0
        self.pipeline_errors: list[str] = []
        self.pipeline_warning: Optional[str] = None   # rate-limit / degraded state
        self.ws_connections: list[WebSocket] = []

    def get_geojson(self) -> dict:
        """Serialize current aircraft to GeoJSON FeatureCollection."""
        features = []
        for ac in self.aircraft.values():
            if ac.latitude is None or ac.longitude is None:
                continue
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        round(ac.longitude, 5),
                        round(ac.latitude, 5),
                    ],
                },
                "properties": {
                    "icao24":          ac.icao24,
                    "callsign":        ac.callsign,
                    "category":        ac.category.value,
                    "altitude_ft":     ac.altitude_ft,
                    "velocity_kts":    ac.velocity_kts,
                    "heading":         ac.heading,
                    "vertical_rate_fpm": ac.vertical_rate_fpm,
                    "on_ground":       ac.on_ground,
                    "squawk":          ac.squawk,
                    "is_military":     ac.is_military,
                    "pattern_label":   ac.pattern_label,
                    "has_anomaly":     len(ac.anomalies) > 0,
                    "anomaly_severity": ac.anomalies[0].severity
                        if ac.anomalies else None,
                    "anomaly_score":   ac.anomaly_score,
                    "origin_country":  ac.origin_country,
                },
            })
        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "count": len(features),
                "generated_at": time.time(),
                "last_pipeline_run": self.last_pipeline_run,
                "pipeline_warning": self.pipeline_warning,
            }
        }


app_state = AppState()


# ── Services ──────────────────────────────────────────────────────────────────

opensky_svc = OpenSkyService(
    client_id=settings.opensky_client_id or settings.opensky_username,
    client_secret=settings.opensky_client_secret or settings.opensky_password,
)
adsb_lol_svc = ADSBLolService()
kalman_svc = KalmanFilterService()
cluster_svc = TrajectoryClusteringService()
anomaly_svc = AnomalyDetectionService()
llm_svc = LLMService()


# ── Data pipeline ─────────────────────────────────────────────────────────────

PIPELINE_INTERVAL_S = 60     # ADS-B poll interval
CLUSTER_INTERVAL_CYCLES = 2  # Run DBSCAN every 2 cycles (~2 min)
ANOMALY_INTERVAL_CYCLES = 3  # Run IsolationForest every 3 cycles (~3 min)

_cycle_count = 0


async def run_pipeline() -> None:
    """
    Full data pipeline — runs every PIPELINE_INTERVAL_S seconds.

    Pipeline stages:
        1. Fetch ADS-B states (OpenSky + adsb.lol)
        2. Kalman filter update for each aircraft
        3. Clustering service: add position to history
        4. Anomaly service: record observation
        5. (every N cycles) Run DBSCAN pattern detection
        6. (every N cycles) Run IsolationForest scoring
        7. Build enriched Aircraft objects and update state
        8. Push GeoJSON to WebSocket clients
    """
    global _cycle_count
    _cycle_count += 1
    start_time = time.time()
    errors = []

    try:
        # ── Stage 1: Fetch ───────────────────────────────
        raw_commercial, raw_military = await asyncio.gather(
            opensky_svc.fetch_states(),
            adsb_lol_svc.fetch_military(),
            return_exceptions=True,
        )

        opensky_rate_limited = False
        opensky_fetch_failed = False
        if isinstance(raw_commercial, OpenSkyRateLimitError):
            opensky_rate_limited = True
            errors.append(str(raw_commercial))
            raw_commercial = []
        elif isinstance(raw_commercial, OpenSkyFetchError):
            opensky_fetch_failed = True
            errors.append(str(raw_commercial))
            print(f"[OpenSky] Fetch failed: {raw_commercial}")
            raw_commercial = []
        elif isinstance(raw_commercial, Exception):
            opensky_fetch_failed = True
            errors.append(f"OpenSky: {raw_commercial}")
            print(f"[OpenSky] Unexpected fetch exception: {raw_commercial}")
            raw_commercial = []
        if isinstance(raw_military, Exception):
            errors.append(f"adsb.lol: {raw_military}")
            raw_military = []

        print(
            f"[Pipeline] Source counts: commercial={len(raw_commercial)} "
            f"military={len(raw_military)} auth_mode={_opensky_auth_mode()}"
        )

        all_raw = [(r, False) for r in raw_commercial] + \
                  [(r, True)  for r in raw_military]

        active_icao24s = {r.icao24 for r, _ in all_raw}

        # ── Stages 2-4: Per-aircraft processing ─────────
        new_aircraft: dict[str, Aircraft] = {}

        for raw, is_mil in all_raw:
            icao = raw.icao24
            if not raw.latitude or not raw.longitude:
                continue

            # Kalman filter update
            kalman_state = kalman_svc.update(
                icao, raw.latitude, raw.longitude, raw.last_contact
            )

            # Trajectory history for clustering
            alt_ft = (raw.baro_altitude * 3.28084) if raw.baro_altitude else None
            cluster_svc.add_position(
                icao, raw.latitude, raw.longitude,
                raw.last_contact, alt_ft, raw.true_track
            )

            # Anomaly observation recording
            vel_kts = (raw.velocity * 1.94384) if raw.velocity else None
            vrate_fpm = (raw.vertical_rate * 196.85) if raw.vertical_rate else None
            anomaly_svc.observe(
                icao, raw.last_contact, alt_ft, vel_kts,
                raw.true_track, vrate_fpm, raw.squawk
            )

            # Build enriched Aircraft object
            ac = _raw_to_aircraft(raw, is_mil, kalman_state)
            new_aircraft[icao] = ac

        # ── Stage 5: DBSCAN pattern detection ────────────
        if _cycle_count % CLUSTER_INTERVAL_CYCLES == 0:
            for icao in active_icao24s:
                pattern = cluster_svc.detect_pattern(icao)
                if icao in new_aircraft:
                    if pattern:
                        new_aircraft[icao].pattern_label = pattern.pattern_type
                        app_state.pattern_labels[icao] = pattern.pattern_type
                    else:
                        # Pattern no longer detected — clear from persistent store
                        app_state.pattern_labels.pop(icao, None)
        else:
            # Non-cluster cycle: carry over last known patterns
            for icao, label in app_state.pattern_labels.items():
                if icao in new_aircraft:
                    new_aircraft[icao].pattern_label = label

        # ── Stage 6: IsolationForest anomaly scoring ─────
        if _cycle_count % ANOMALY_INTERVAL_CYCLES == 0:
            scores = anomaly_svc.fit_and_score()
            app_state.anomaly_scores = scores

        # Apply stored anomaly scores to all aircraft every cycle so that
        # anomaly_score / has_anomaly persist between IsolationForest runs.
        for icao, score in app_state.anomaly_scores.items():
            if icao not in new_aircraft:
                continue
            ac = new_aircraft[icao]
            ac.anomaly_score = round(score, 4)

            # Check squawk emergency (rule-based — runs every cycle)
            squawk_anomaly = anomaly_svc.check_squawk(icao, ac.squawk)
            if squawk_anomaly:
                ac.anomalies.append(squawk_anomaly)

            # Check behavioral anomaly (ML-based — uses latest stored score)
            behavioral = anomaly_svc.build_anomaly(icao, score)
            if behavioral:
                ac.anomalies.append(behavioral)

        # ── Stage 7: Update state ────────────────────────
        if opensky_rate_limited:
            # Keep cached commercial aircraft; overlay fresh military data
            merged = {
                icao: ac
                for icao, ac in app_state.aircraft.items()
                if not ac.is_military
            }
            merged.update({
                icao: ac
                for icao, ac in new_aircraft.items()
                if ac.is_military
            })
            app_state.aircraft = merged
            app_state.pipeline_warning = (
                "OpenSky rate limited — serving cached aircraft data"
            )
            print(f"[Pipeline] Warning: {app_state.pipeline_warning}")
        elif opensky_fetch_failed:
            cached_commercial = {
                icao: ac
                for icao, ac in app_state.aircraft.items()
                if not ac.is_military
            }
            if cached_commercial:
                cached_commercial.update({
                    icao: ac
                    for icao, ac in new_aircraft.items()
                    if ac.is_military
                })
                app_state.aircraft = cached_commercial
                app_state.pipeline_warning = (
                    "OpenSky unavailable — serving cached aircraft data"
                )
            else:
                app_state.aircraft = {
                    icao: ac
                    for icao, ac in new_aircraft.items()
                    if ac.is_military
                }
                app_state.pipeline_warning = (
                    "OpenSky unavailable — serving military-only data"
                )
            print(f"[Pipeline] Warning: {app_state.pipeline_warning}")
        else:
            app_state.aircraft = new_aircraft
            app_state.pipeline_warning = None

        # Prune stale data from all services
        kalman_svc.prune_stale()
        cluster_svc.prune_stale(active_icao24s)
        anomaly_svc.prune_stale(active_icao24s)
        app_state.anomaly_scores = {
            icao: score
            for icao, score in app_state.anomaly_scores.items()
            if icao in active_icao24s
        }
        app_state.pattern_labels = {
            icao: label
            for icao, label in app_state.pattern_labels.items()
            if icao in active_icao24s
        }

    except Exception as e:
        errors.append(f"Pipeline error: {e}")
        import traceback
        traceback.print_exc()

    app_state.last_pipeline_run = time.time()
    app_state.pipeline_duration_s = round(time.time() - start_time, 2)
    app_state.pipeline_errors = errors

    # ── Stage 8: Push to WebSocket clients ───────────────
    if app_state.ws_connections:
        geojson = app_state.get_geojson()
        payload = json.dumps(geojson)
        dead_connections = []
        for ws in app_state.ws_connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead_connections.append(ws)
        for ws in dead_connections:
            app_state.ws_connections.remove(ws)

    count = len(app_state.aircraft)
    dur = app_state.pipeline_duration_s
    print(f"[Pipeline] Cycle {_cycle_count}: {count} aircraft in {dur}s"
          + (f" | errors: {errors}" if errors else ""))


async def pipeline_loop() -> None:
    """Background task: run pipeline on interval."""
    while True:
        await run_pipeline()
        await asyncio.sleep(PIPELINE_INTERVAL_S)


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(
        "[Startup] OpenSky auth mode="
        f"{_opensky_auth_mode()} configured="
        f"{bool(opensky_svc.client_id and opensky_svc.client_secret)}"
    )
    # Run one cycle immediately on startup, then start loop
    asyncio.create_task(run_pipeline())
    task = asyncio.create_task(pipeline_loop())
    yield
    task.cancel()


app = FastAPI(
    title="AeroIntel API",
    description="Real-time aviation intelligence — Kalman filtering, DBSCAN pattern detection, LLM analysis",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/api/aircraft")
async def get_aircraft():
    """All current aircraft as GeoJSON FeatureCollection."""
    return app_state.get_geojson()


@app.get("/api/aircraft/{icao24}")
async def get_aircraft_detail(icao24: str):
    """Full detail for a single aircraft including anomaly data."""
    ac = app_state.aircraft.get(icao24.lower())
    if not ac:
        raise HTTPException(status_code=404, detail="Aircraft not found")
    return ac.model_dump()


@app.post("/api/query")
async def nl_query(request: NLQueryRequest) -> NLQueryResponse:
    """Parse a natural language query into structured filter parameters."""
    result = llm_svc.parse_nl_query(
        request.query,
        request.context_aircraft_count,
    )
    if not result:
        return NLQueryResponse(
            filter_params={},
            explanation="Could not parse query. Try: 'Show military aircraft above 30,000 feet'",
        )
    return NLQueryResponse(
        filter_params=result.get("filters", {}),
        explanation=result.get("explanation", ""),
        result_count=None,
    )


@app.post("/api/summary")
async def region_summary(region: RegionQuery) -> SituationSummary:
    """Generate an LLM intelligence summary for a geographic region."""
    # Filter aircraft to bounding box
    in_region = [
        ac for ac in app_state.aircraft.values()
        if (ac.latitude and ac.longitude and
            region.min_lat <= ac.latitude <= region.max_lat and
            region.min_lon <= ac.longitude <= region.max_lon)
    ]

    aircraft_data = [
        {
            "callsign":      ac.callsign,
            "category":      ac.category.value,
            "altitude_ft":   ac.altitude_ft,
            "velocity_kts":  ac.velocity_kts,
            "heading":       ac.heading,
            "is_military":   ac.is_military,
            "pattern_label": ac.pattern_label,
            "anomalies":     [a.anomaly_type.value for a in ac.anomalies],
            "origin_country": ac.origin_country,
        }
        for ac in in_region
    ]

    label = region.label or f"({region.min_lat:.1f}°,{region.min_lon:.1f}°)→({region.max_lat:.1f}°,{region.max_lon:.1f}°)"
    summary_text = llm_svc.generate_situation_summary(label, aircraft_data)

    return SituationSummary(
        region_label=label,
        aircraft_count=len(in_region),
        summary=summary_text or "Summary unavailable.",
        notable_items=[
            f"{ac.callsign or ac.icao24}: {ac.pattern_label}"
            for ac in in_region if ac.pattern_label
        ][:5],
        generated_at=time.time(),
    )


@app.get("/api/aircraft/{icao24}/explain")
async def explain_aircraft_anomaly(icao24: str, force: bool = False):
    """
    On-demand LLM explanation for an anomalous aircraft.

    Calls `llm_svc.explain_anomaly()` with the aircraft's current feature
    vector. Uses asyncio.to_thread() since the Anthropic client is synchronous.

    Only available for aircraft that have been flagged with at least one anomaly.
    Use ?force=true to generate an explanation for any scored aircraft regardless
    of threshold (useful for evidence capture and debugging).
    Returns 404 if the aircraft is not tracked or has no anomaly flags.
    """
    ac = app_state.aircraft.get(icao24.lower())
    if not ac:
        raise HTTPException(status_code=404, detail="Aircraft not found")
    if not ac.anomalies and not force:
        raise HTTPException(
            status_code=404,
            detail="No anomalies detected for this aircraft"
        )
    if not ac.anomaly_score:
        raise HTTPException(
            status_code=404,
            detail="Aircraft has no anomaly score yet — wait for scoring cycle"
        )

    feature_dict = anomaly_svc.get_feature_dict(icao24.lower()) or {}

    explanation = await asyncio.to_thread(
        llm_svc.explain_anomaly,
        ac.callsign,
        icao24.lower(),
        ac.anomaly_score or 0.0,
        feature_dict,
        ac.pattern_label,
    )

    return {
        "icao24":        icao24.lower(),
        "callsign":      ac.callsign,
        "explanation":   explanation or "Explanation unavailable — ANTHROPIC_API_KEY may not be set.",
        "anomaly_score": ac.anomaly_score,
        "features":      feature_dict,
    }


@app.get("/health")
async def health_check():
    """Railway / Vercel health probe — returns 200 when the app is running."""
    return {"status": "ok"}


@app.get("/api/stats")
async def get_stats():
    """Pipeline diagnostics and service health."""
    return {
        "aircraft_count":      len(app_state.aircraft),
        "military_count":      sum(1 for a in app_state.aircraft.values() if a.is_military),
        "anomaly_count":       sum(1 for a in app_state.aircraft.values() if a.anomalies),
        "pattern_count":       sum(1 for a in app_state.aircraft.values() if a.pattern_label),
        "kalman_tracked":      kalman_svc.tracked_count,
        "cluster_tracked":     cluster_svc.tracked_count,
        "last_pipeline_run":   app_state.last_pipeline_run,
        "pipeline_duration_s": app_state.pipeline_duration_s,
        "pipeline_warning":    app_state.pipeline_warning,
        "pipeline_errors":     app_state.pipeline_errors,
        "opensky_auth_mode":   _opensky_auth_mode(),
        "opensky_configured":  bool(opensky_svc.client_id and opensky_svc.client_secret),
        "llm_stats":           llm_svc.stats,
        "ws_connections":      len(app_state.ws_connections),
        "pipeline_cycle":      _cycle_count,
    }


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/aircraft")
async def aircraft_websocket(ws: WebSocket):
    """
    WebSocket endpoint — pushes updated GeoJSON on each pipeline cycle.
    Frontend connects once and receives live updates without polling.
    """
    await ws.accept()
    app_state.ws_connections.append(ws)

    # Send current state immediately on connect
    try:
        await ws.send_text(json.dumps(app_state.get_geojson()))
        while True:
            # Keep alive — actual data pushed by pipeline_loop
            await asyncio.sleep(30)
            await ws.send_text(json.dumps({"type": "ping"}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if ws in app_state.ws_connections:
            app_state.ws_connections.remove(ws)
