"""
services/clustering.py
----------------------
DBSCAN-based trajectory pattern detection.

Holding patterns and ISR racetrack orbits manifest as
density clusters in geographic space — the aircraft repeatedly
visits the same coordinates. DBSCAN (Density-Based Spatial
Clustering of Applications with Noise) identifies these without
requiring a known number of patterns and naturally handles
the noise of normal transiting flight paths.

Why DBSCAN over K-means:
    - No need to specify k (number of clusters) in advance
    - Handles arbitrary cluster shapes (circles, ovals, figure-8s)
    - Points not in any cluster are labeled "noise" — correct
      behavior for non-loitering aircraft
    - Works with Haversine distance metric for geographic accuracy

Pattern types detected:
    HOLDING   — circular path, ~1–5 nm radius, consistent altitude
    RACETRACK — elongated oval path, ISR/surveillance signature
    ORBIT     — tight circle, common for helicopter operations

References:
    Ester et al. (1996) "A Density-Based Algorithm for Discovering
    Clusters in Large Spatial Databases with Noise" (original DBSCAN)
"""

import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import Optional
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler


# ── Configuration ───────────────────────────────────────────────────────────

# Minimum position history required before pattern analysis
MIN_HISTORY_POINTS = 12

# Maximum history kept per aircraft (at ~10s intervals = ~10 minutes)
MAX_HISTORY_POINTS = 60

# DBSCAN parameters
# eps: neighborhood radius in degrees (~0.05 deg ≈ 5.5 km at mid-latitudes)
DBSCAN_EPS = 0.05
DBSCAN_MIN_SAMPLES = 4

# Pattern classification thresholds
HOLDING_MAX_RADIUS_DEG = 0.08      # ~8km — typical holding fix radius
RACETRACK_ASPECT_RATIO = 2.0       # length/width ratio for racetrack ID


@dataclass
class TrajectoryPoint:
    lat: float
    lon: float
    timestamp: float
    altitude_ft: Optional[float] = None
    heading: Optional[float] = None


@dataclass
class DetectedPattern:
    pattern_type: str                           # "holding", "racetrack", "orbit"
    confidence: float                           # 0.0–1.0
    center_lat: float
    center_lon: float
    radius_deg: Optional[float] = None          # for circular patterns
    aspect_ratio: Optional[float] = None        # for racetrack patterns
    point_count: int = 0


def _haversine_deg(lat1: float, lon1: float,
                   lat2: float, lon2: float) -> float:
    """
    Great-circle distance in degrees between two points.
    Used as DBSCAN distance metric for geographic clustering.
    1 degree ≈ 111 km at equator.
    """
    R = 6371.0  # km
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = (np.sin(dlat / 2) ** 2 +
         np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) *
         np.sin(dlon / 2) ** 2)
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    km = R * c
    return km / 111.0  # convert to approximate degrees


def _classify_cluster(points: np.ndarray) -> DetectedPattern:
    """
    Given a set of lat/lon points forming a DBSCAN cluster,
    classify what flight pattern they represent.

    Classification logic:
        1. Compute bounding box → aspect ratio
        2. Compute centroid and max radius from centroid
        3. Aspect ratio > RACETRACK_ASPECT_RATIO → racetrack
        4. Otherwise → holding/orbit (circular)
    """
    center_lat = float(np.mean(points[:, 0]))
    center_lon = float(np.mean(points[:, 1]))

    # Bounding box dimensions (degrees)
    lat_span = float(np.max(points[:, 0]) - np.min(points[:, 0]))
    lon_span = float(np.max(points[:, 1]) - np.min(points[:, 1]))

    # Aspect ratio: avoid div-by-zero on degenerate clusters
    if min(lat_span, lon_span) < 1e-6:
        aspect_ratio = 1.0
    else:
        aspect_ratio = max(lat_span, lon_span) / min(lat_span, lon_span)

    # Max radius from centroid
    radii = [
        _haversine_deg(center_lat, center_lon, p[0], p[1])
        for p in points
    ]
    radius_deg = float(np.max(radii))

    # Coverage fraction: what fraction of the circle is covered?
    # Low coverage = partial arc (just passing through), not a pattern
    coverage = min(1.0, len(points) / MAX_HISTORY_POINTS)

    if aspect_ratio >= RACETRACK_ASPECT_RATIO:
        # Elongated cluster → racetrack / ISR orbit pattern
        confidence = min(0.95, coverage * 1.2 * (aspect_ratio / 3.0))
        return DetectedPattern(
            pattern_type="racetrack",
            confidence=round(confidence, 3),
            center_lat=center_lat,
            center_lon=center_lon,
            radius_deg=radius_deg,
            aspect_ratio=round(aspect_ratio, 2),
            point_count=len(points),
        )
    elif radius_deg <= HOLDING_MAX_RADIUS_DEG:
        # Tight circular cluster → holding pattern or helicopter orbit
        confidence = min(0.95, coverage * 1.3)
        return DetectedPattern(
            pattern_type="holding",
            confidence=round(confidence, 3),
            center_lat=center_lat,
            center_lon=center_lon,
            radius_deg=round(radius_deg, 4),
            aspect_ratio=round(aspect_ratio, 2),
            point_count=len(points),
        )
    else:
        # Larger circular cluster → wide orbit
        confidence = min(0.85, coverage)
        return DetectedPattern(
            pattern_type="orbit",
            confidence=round(confidence, 3),
            center_lat=center_lat,
            center_lon=center_lon,
            radius_deg=round(radius_deg, 4),
            aspect_ratio=round(aspect_ratio, 2),
            point_count=len(points),
        )


class TrajectoryClusteringService:
    """
    Manages rolling position history per aircraft and
    runs DBSCAN pattern detection on each update cycle.

    The service is intentionally stateless between aircraft —
    each ICAO24 address maintains its own trajectory deque,
    and pattern detection runs independently per aircraft.
    """

    def __init__(self):
        # Rolling trajectory history: icao24 → deque of TrajectoryPoints
        self.histories: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=MAX_HISTORY_POINTS)
        )
        # Most recent detected pattern per aircraft
        self.patterns: dict[str, Optional[DetectedPattern]] = {}

    def add_position(self, icao24: str, lat: float, lon: float,
                     timestamp: float,
                     altitude_ft: Optional[float] = None,
                     heading: Optional[float] = None) -> None:
        """Add a new position observation to an aircraft's history."""
        self.histories[icao24].append(TrajectoryPoint(
            lat=lat, lon=lon, timestamp=timestamp,
            altitude_ft=altitude_ft, heading=heading,
        ))

    def detect_pattern(self, icao24: str) -> Optional[DetectedPattern]:
        """
        Run DBSCAN on this aircraft's position history.
        Returns a DetectedPattern if a loitering pattern is found,
        None if the aircraft appears to be in normal transit.

        The result is cached in self.patterns[icao24] and returned.
        """
        history = self.histories.get(icao24)
        if not history or len(history) < MIN_HISTORY_POINTS:
            self.patterns[icao24] = None
            return None

        points = np.array([[p.lat, p.lon] for p in history])

        # Run DBSCAN with Haversine-like metric
        # We use euclidean on lat/lon as an approximation (valid at small scales)
        db = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLES,
                    metric="euclidean").fit(points)

        labels = db.labels_
        unique_labels = set(labels) - {-1}  # -1 = noise in DBSCAN

        if not unique_labels:
            # No clusters found — aircraft is transiting normally
            self.patterns[icao24] = None
            return None

        # Find the largest cluster
        largest_label = max(unique_labels,
                            key=lambda l: np.sum(labels == l))
        cluster_points = points[labels == largest_label]

        # Only classify if the cluster is substantial
        cluster_fraction = len(cluster_points) / len(points)
        if cluster_fraction < 0.4:
            self.patterns[icao24] = None
            return None

        pattern = _classify_cluster(cluster_points)
        self.patterns[icao24] = pattern
        return pattern

    def get_pattern(self, icao24: str) -> Optional[DetectedPattern]:
        """Return the last detected pattern without re-running DBSCAN."""
        return self.patterns.get(icao24)

    def prune_stale(self, active_icao24s: set[str]) -> int:
        """Remove histories for aircraft no longer in the active set."""
        stale = set(self.histories.keys()) - active_icao24s
        for icao in stale:
            del self.histories[icao]
            self.patterns.pop(icao, None)
        return len(stale)

    @property
    def tracked_count(self) -> int:
        return len(self.histories)
