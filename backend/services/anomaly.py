"""
services/anomaly.py
-------------------
IsolationForest-based behavioral anomaly detection for ADS-B tracks.

Squawk code checks (7700/7600/7500) catch declared emergencies.
This module catches *behavioral* anomalies — unusual combinations
of altitude change, speed delta, heading variance, and vertical rate
that precede or accompany events that don't generate a squawk.

Why IsolationForest:
    - Anomalies are rare events in high-dimensional feature space
    - No labeled "anomalous" examples available for supervised training
    - Isolation works by random recursive partitioning — anomalous
      observations require fewer splits to isolate from the population
    - Computationally efficient for streaming/incremental updates
    - Contamination parameter tunable for false positive/negative tradeoff

Feature vector per aircraft (5-minute rolling window):
    [0] altitude_delta_ft        change in altitude over window
    [1] speed_delta_kts          change in speed over window
    [2] heading_variance_deg     circular variance of heading readings
    [3] vertical_rate_fpm        current climb/descent rate
    [4] update_gap_s             seconds since last ADS-B contact
    [5] squawk_changed           0/1 — squawk code changed in window
"""

import numpy as np
import time
from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Optional
from sklearn.ensemble import IsolationForest

from models.schemas import AircraftAnomaly, AnomalyType


# ── Configuration ───────────────────────────────────────────────────────────

# Feature window: rolling observations used for feature extraction
FEATURE_WINDOW_S = 300          # 5 minutes

# Minimum observations before anomaly scoring begins
MIN_OBSERVATIONS = 6

# IsolationForest contamination: expected fraction of anomalies
# 0.02 = ~2% of aircraft expected to be anomalous at any time
CONTAMINATION = 0.02

# Minimum population for meaningful IsolationForest fit
MIN_POPULATION_FOR_FIT = 30

# Anomaly score threshold (IsolationForest returns [-1, 1], lower = more anomalous)
# Scores below this threshold trigger a behavioral anomaly flag
ANOMALY_SCORE_THRESHOLD = -0.15


@dataclass
class ObservationWindow:
    """Rolling window of recent observations for a single aircraft."""
    observations: deque  # deque of (timestamp, feature_dict)
    last_squawk: Optional[str] = None
    squawk_changed: bool = False


def _circular_variance(headings_deg: list[float]) -> float:
    """
    Circular variance of heading angles (0–360 degrees).

    Standard variance is wrong for angles because of the 359°→0° wraparound.
    Circular variance uses unit vectors on the unit circle, properly handling
    the periodic nature of heading measurements.

    Returns value in [0, 1]: 0 = all same heading, 1 = uniformly random.
    """
    if len(headings_deg) < 2:
        return 0.0
    rads = np.radians(headings_deg)
    # Mean resultant length R: 1 = concentrated, 0 = dispersed
    R = np.sqrt(np.mean(np.cos(rads)) ** 2 + np.mean(np.sin(rads)) ** 2)
    return float(1.0 - R)  # variance = 1 - R


def _extract_features(window: ObservationWindow,
                      now: float) -> Optional[np.ndarray]:
    """
    Extract 6-dimensional feature vector from observation window.
    Returns None if insufficient history exists.
    """
    # Filter to recent observations within the window
    recent = [
        (ts, obs) for ts, obs in window.observations
        if now - ts <= FEATURE_WINDOW_S
    ]

    if len(recent) < MIN_OBSERVATIONS:
        return None

    timestamps = [ts for ts, _ in recent]
    obs_list = [obs for _, obs in recent]

    # Feature 0: altitude delta (ft) over window
    alts = [o["alt"] for o in obs_list if o.get("alt") is not None]
    alt_delta = (alts[-1] - alts[0]) if len(alts) >= 2 else 0.0

    # Feature 1: speed delta (kts) over window
    speeds = [o["speed"] for o in obs_list if o.get("speed") is not None]
    speed_delta = (speeds[-1] - speeds[0]) if len(speeds) >= 2 else 0.0

    # Feature 2: heading circular variance
    headings = [o["heading"] for o in obs_list if o.get("heading") is not None]
    hdg_variance = _circular_variance(headings) if headings else 0.0

    # Feature 3: vertical rate (ft/min) — most recent observation
    vrate = obs_list[-1].get("vrate", 0.0) or 0.0

    # Feature 4: update gap (seconds since last contact)
    update_gap = now - max(timestamps)

    # Feature 5: squawk changed (binary)
    squawk_flag = 1.0 if window.squawk_changed else 0.0

    return np.array([
        alt_delta,
        speed_delta,
        hdg_variance,
        vrate,
        update_gap,
        squawk_flag,
    ], dtype=np.float32)


class AnomalyDetectionService:
    """
    Fleet-level anomaly detection using IsolationForest.

    The model is fit on the population of current feature vectors,
    then used to score each aircraft. This population-relative approach
    means "anomalous" is defined relative to what the rest of the fleet
    is doing right now — a sudden climb is only anomalous if nobody else
    is climbing.

    The model is re-fit on each pipeline cycle (~60s), keeping it
    calibrated to current flight conditions (weather, traffic density).
    """

    def __init__(self):
        self.windows: dict[str, ObservationWindow] = {}
        self.model: Optional[IsolationForest] = None
        self.last_fit_time: float = 0.0
        self.feature_matrix: dict[str, np.ndarray] = {}  # icao24 → features

    def observe(self, icao24: str,
                timestamp: float,
                altitude_ft: Optional[float],
                velocity_kts: Optional[float],
                heading: Optional[float],
                vertical_rate_fpm: Optional[float],
                squawk: Optional[str]) -> None:
        """
        Record a new ADS-B observation for an aircraft.
        Updates the rolling observation window and tracks squawk changes.
        """
        if icao24 not in self.windows:
            self.windows[icao24] = ObservationWindow(
                observations=deque(maxlen=60),  # ~10 min at 10s intervals
                last_squawk=squawk,
            )

        w = self.windows[icao24]

        # Track squawk changes
        if squawk and squawk != w.last_squawk and w.last_squawk is not None:
            w.squawk_changed = True
        w.last_squawk = squawk

        w.observations.append((timestamp, {
            "alt":     altitude_ft,
            "speed":   velocity_kts,
            "heading": heading,
            "vrate":   vertical_rate_fpm,
        }))

    def fit_and_score(self) -> dict[str, float]:
        """
        Fit IsolationForest on current fleet feature vectors and
        return anomaly scores per aircraft.

        Called once per pipeline cycle. Returns dict of icao24 → score,
        where lower scores indicate more anomalous behavior.
        Scores below ANOMALY_SCORE_THRESHOLD are flagged.
        """
        now = time.time()
        self.feature_matrix = {}

        # Extract features for all tracked aircraft
        for icao24, window in self.windows.items():
            features = _extract_features(window, now)
            if features is not None:
                self.feature_matrix[icao24] = features

        if len(self.feature_matrix) < MIN_POPULATION_FOR_FIT:
            return {}

        icao_list = list(self.feature_matrix.keys())
        X = np.stack([self.feature_matrix[i] for i in icao_list])

        # Fit IsolationForest on current population
        self.model = IsolationForest(
            contamination=CONTAMINATION,
            n_estimators=100,
            random_state=42,
            n_jobs=-1,
        )
        self.model.fit(X)
        self.last_fit_time = now

        # Score all aircraft (returns array of shape [n_samples])
        raw_scores = self.model.decision_function(X)

        return {icao: float(score)
                for icao, score in zip(icao_list, raw_scores)}

    def check_squawk(self, icao24: str,
                     squawk: Optional[str]) -> Optional[AircraftAnomaly]:
        """
        Check for declared emergency squawk codes.
        These are rule-based, not ML-based — no ambiguity needed.

        7700 = General emergency
        7600 = Radio communication failure
        7500 = Unlawful interference (hijacking)
        """
        if not squawk:
            return None

        EMERGENCY_SQUAWKS = {
            "7700": (AnomalyType.SQUAWK_EMERGENCY, "critical",
                     "Aircraft has declared a general emergency (squawk 7700)."),
            "7600": (AnomalyType.SQUAWK_COMMS, "high",
                     "Aircraft has declared radio communications failure (squawk 7600)."),
            "7500": (AnomalyType.SQUAWK_HIJACK, "critical",
                     "Aircraft has declared unlawful interference / hijacking (squawk 7500)."),
        }

        if squawk in EMERGENCY_SQUAWKS:
            anomaly_type, severity, explanation = EMERGENCY_SQUAWKS[squawk]
            return AircraftAnomaly(
                anomaly_type=anomaly_type,
                severity=severity,
                confidence=1.0,
                explanation=explanation,
                detected_at=time.time(),
            )
        return None

    def build_anomaly(self, icao24: str,
                      score: float) -> Optional[AircraftAnomaly]:
        """
        Convert an IsolationForest anomaly score into an AircraftAnomaly.
        Only called when score < ANOMALY_SCORE_THRESHOLD.
        """
        if score >= ANOMALY_SCORE_THRESHOLD:
            return None

        # Severity based on how far below threshold
        gap = ANOMALY_SCORE_THRESHOLD - score
        if gap > 0.3:
            severity = "high"
            confidence = min(0.95, 0.7 + gap)
        elif gap > 0.15:
            severity = "medium"
            confidence = min(0.85, 0.55 + gap)
        else:
            severity = "low"
            confidence = min(0.70, 0.4 + gap)

        return AircraftAnomaly(
            anomaly_type=AnomalyType.BEHAVIORAL,
            severity=severity,
            confidence=round(confidence, 3),
            explanation=None,  # LLM layer fills this in
            detected_at=time.time(),
        )

    def get_feature_dict(self, icao24: str) -> Optional[dict]:
        """
        Return the last computed feature vector for an aircraft as a named dict.
        Suitable for passing directly to LLMService.explain_anomaly().
        Returns None if the aircraft has not been scored yet.
        """
        vec = self.feature_matrix.get(icao24)
        if vec is None:
            return None
        return {
            "altitude_delta_ft": float(vec[0]),
            "speed_delta_kts":   float(vec[1]),
            "heading_variance":  float(vec[2]),
            "vertical_rate_fpm": float(vec[3]),
            "update_gap_s":      float(vec[4]),
            "squawk_changed":    bool(vec[5] > 0.5),
        }

    def prune_stale(self, active_icao24s: set[str]) -> int:
        stale = set(self.windows.keys()) - active_icao24s
        for icao in stale:
            del self.windows[icao]
        return len(stale)
