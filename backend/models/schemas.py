"""
models/schemas.py
-----------------
Pydantic data models for AeroIntel.

All ADS-B state vectors flow through these schemas, keeping the
ML pipeline and API layer decoupled from raw OpenSky JSON.
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum


class AircraftCategory(str, Enum):
    COMMERCIAL = "commercial"
    PRIVATE = "private"
    MILITARY = "military"
    HELICOPTER = "helicopter"
    UNKNOWN = "unknown"


class AnomalyType(str, Enum):
    SQUAWK_EMERGENCY = "squawk_emergency"       # 7700
    SQUAWK_COMMS = "squawk_comms"               # 7600
    SQUAWK_HIJACK = "squawk_hijack"             # 7500
    BEHAVIORAL = "behavioral"                   # IsolationForest flagged
    HOLDING_PATTERN = "holding_pattern"         # DBSCAN detected
    RACETRACK = "racetrack"                     # ISR pattern
    RAPID_DESCENT = "rapid_descent"
    ALTITUDE_ANOMALY = "altitude_anomaly"


class RawAircraftState(BaseModel):
    """Raw state vector from OpenSky Network API."""
    icao24: str
    callsign: Optional[str] = None
    origin_country: Optional[str] = None
    time_position: Optional[float] = None
    last_contact: float
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    baro_altitude: Optional[float] = None      # meters
    on_ground: bool = False
    velocity: Optional[float] = None           # m/s
    true_track: Optional[float] = None         # degrees, 0=N, clockwise
    vertical_rate: Optional[float] = None      # m/s
    geo_altitude: Optional[float] = None       # meters
    squawk: Optional[str] = None
    spi: bool = False
    position_source: Optional[int] = None


class KalmanState(BaseModel):
    """
    Smoothed position + velocity estimate from Kalman filter.
    
    State vector: [lat, lon, dlat/dt, dlon/dt]
    Covariance matrix stored as flat list (4x4 = 16 elements).
    """
    lat: float
    lon: float
    dlat: float = 0.0                          # deg/s northward velocity
    dlon: float = 0.0                          # deg/s eastward velocity
    covariance: list[float] = Field(           # 4x4 flattened
        default_factory=lambda: [1.0] * 16
    )
    last_update: float = 0.0


class AircraftAnomaly(BaseModel):
    """Detected anomaly on a tracked aircraft."""
    anomaly_type: AnomalyType
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: Optional[str] = None          # LLM-generated explanation
    detected_at: float


class Aircraft(BaseModel):
    """
    Fully enriched aircraft state — the core domain object.
    
    Combines raw ADS-B state, Kalman-smoothed position,
    ML-derived classification, and any detected anomalies.
    """
    icao24: str
    callsign: Optional[str] = None
    origin_country: Optional[str] = None

    # Kalman-smoothed position (use these for rendering, not raw)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_ft: Optional[float] = None        # converted from meters
    velocity_kts: Optional[float] = None       # converted from m/s
    heading: Optional[float] = None            # true track degrees
    vertical_rate_fpm: Optional[float] = None  # ft/min

    # Raw values preserved for ML feature computation
    raw_latitude: Optional[float] = None
    raw_longitude: Optional[float] = None

    category: AircraftCategory = AircraftCategory.UNKNOWN
    on_ground: bool = False
    squawk: Optional[str] = None

    # ML outputs
    kalman_state: Optional[KalmanState] = None
    anomalies: list[AircraftAnomaly] = []
    pattern_label: Optional[str] = None        # "holding", "racetrack", None
    anomaly_score: Optional[float] = None      # IsolationForest score

    # FAA enrichment (populated on-demand)
    owner: Optional[str] = None
    aircraft_type: Optional[str] = None
    registration: Optional[str] = None

    last_contact: float = 0.0
    is_military: bool = False


class RegionQuery(BaseModel):
    """Bounding box for LLM situation summary."""
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    label: Optional[str] = None               # e.g. "Eastern Mediterranean"


class NLQueryRequest(BaseModel):
    """Natural language query from the user."""
    query: str
    context_aircraft_count: int = 0


class NLQueryResponse(BaseModel):
    """Structured filter + explanation from Claude."""
    filter_params: dict                        # Applied to aircraft list
    explanation: str                           # What Claude understood
    result_count: Optional[int] = None


class SituationSummary(BaseModel):
    """LLM-generated intelligence summary for a region."""
    region_label: str
    aircraft_count: int
    summary: str
    notable_items: list[str] = []
    generated_at: float
