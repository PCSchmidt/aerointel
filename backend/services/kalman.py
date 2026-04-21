"""
services/kalman.py
------------------
Kalman filter for ADS-B position smoothing and velocity estimation.

ADS-B position updates arrive every 5–10 seconds with ~10m accuracy.
Raw interpolation between updates produces jerky motion artifacts.
This module maintains a constant-velocity Kalman filter per aircraft,
producing smooth position estimates and velocity predictions between
update intervals.

State vector:  x = [lat, lon, dlat, dlon]
               where dlat/dlon are degrees-per-second velocity components

Measurement:   z = [lat_measured, lon_measured]

This is the same family of estimation algorithms used in avionics
navigation systems (INS/GPS sensor fusion), operating here on
public ADS-B telemetry rather than onboard sensor data.

References:
    Welch & Bishop (2006) "An Introduction to the Kalman Filter"
    Zarchan & Musoff (2009) "Fundamentals of Kalman Filtering"
"""

import numpy as np
import time
from typing import Optional
from models.schemas import KalmanState


# ── Noise tuning parameters ─────────────────────────────────────────────────

# Process noise (Q): how much we trust the constant-velocity model.
# Higher = filter reacts faster to maneuvers, more noise in output.
# Lower = smoother output, slower response to direction changes.
# Tuned empirically for ADS-B 5-10s update rate.
PROCESS_NOISE_POS = 1e-8      # position component (degrees^2/s)
PROCESS_NOISE_VEL = 1e-9      # velocity component (degrees^2/s^3)

# Measurement noise (R): ADS-B positional accuracy ~10m ≈ 9e-5 degrees
MEASUREMENT_NOISE = 9e-5


def _build_Q(dt: float) -> np.ndarray:
    """
    Discrete process noise matrix using piecewise white noise model.
    
    This formulation (Singer model variant) correctly scales process
    noise with the timestep dt, preventing the filter from becoming
    overconfident during long intervals between measurements.
    """
    q_pos = PROCESS_NOISE_POS
    q_vel = PROCESS_NOISE_VEL
    dt2 = dt ** 2
    dt3 = dt ** 3

    # 4x4 Q matrix for [lat, lon, dlat, dlon] state
    Q = np.array([
        [q_pos * dt3 / 3, 0,               q_pos * dt2 / 2, 0              ],
        [0,               q_pos * dt3 / 3, 0,               q_pos * dt2 / 2],
        [q_pos * dt2 / 2, 0,               q_vel * dt,      0              ],
        [0,               q_pos * dt2 / 2, 0,               q_vel * dt     ],
    ])
    return Q


def _build_F(dt: float) -> np.ndarray:
    """
    State transition matrix for constant-velocity model.
    
    Propagates state forward by dt seconds:
        lat_new  = lat  + dlat * dt
        lon_new  = lon  + dlon * dt
        dlat_new = dlat  (constant velocity)
        dlon_new = dlon  (constant velocity)
    """
    return np.array([
        [1, 0, dt, 0 ],
        [0, 1, 0,  dt],
        [0, 0, 1,  0 ],
        [0, 0, 0,  1 ],
    ])


# Measurement matrix H: we observe [lat, lon] from ADS-B
H = np.array([
    [1, 0, 0, 0],
    [0, 1, 0, 0],
])

# Measurement noise covariance R
R = np.eye(2) * MEASUREMENT_NOISE


class AircraftKalmanFilter:
    """
    Single-aircraft Kalman filter instance.
    
    One of these lives in KalmanFilterService.filters[icao24].
    Maintains the full filter state between ADS-B updates,
    allowing prediction (interpolation) at any intermediate time.
    """

    def __init__(self, lat: float, lon: float, timestamp: float):
        # Initial state: observed position, zero velocity
        self.x = np.array([lat, lon, 0.0, 0.0])

        # Initial covariance: high position confidence, uncertain velocity
        self.P = np.diag([1e-6, 1e-6, 1e-4, 1e-4])

        self.last_update = timestamp

    def predict(self, dt: float) -> np.ndarray:
        """
        Kalman predict step — propagate state forward by dt seconds.
        Returns predicted state vector (does NOT update internal state).
        Called by the API layer to smooth position between ADS-B updates.
        """
        F = _build_F(dt)
        return F @ self.x

    def update(self, lat: float, lon: float, timestamp: float) -> None:
        """
        Kalman update step — incorporate new ADS-B measurement.
        
        Two-step process:
          1. Predict: propagate state to current time using motion model
          2. Update: correct prediction with new observation via Kalman gain
        """
        dt = max(timestamp - self.last_update, 0.1)  # prevent dt=0
        F = _build_F(dt)
        Q = _build_Q(dt)

        # ── Predict step ─────────────────────────────────
        x_pred = F @ self.x
        P_pred = F @ self.P @ F.T + Q

        # ── Update step ──────────────────────────────────
        z = np.array([lat, lon])                    # measurement
        y = z - H @ x_pred                          # innovation
        S = H @ P_pred @ H.T + R                    # innovation covariance
        K = P_pred @ H.T @ np.linalg.inv(S)         # Kalman gain

        self.x = x_pred + K @ y
        self.P = (np.eye(4) - K @ H) @ P_pred
        self.last_update = timestamp

    def get_smoothed_state(self) -> tuple[float, float, float, float]:
        """Return (lat, lon, dlat, dlon) from current filter state."""
        return float(self.x[0]), float(self.x[1]), float(self.x[2]), float(self.x[3])

    def to_schema(self) -> KalmanState:
        return KalmanState(
            lat=float(self.x[0]),
            lon=float(self.x[1]),
            dlat=float(self.x[2]),
            dlon=float(self.x[3]),
            covariance=self.P.flatten().tolist(),
            last_update=self.last_update,
        )


class KalmanFilterService:
    """
    Manages a pool of per-aircraft Kalman filters.
    
    Called by the data pipeline on every OpenSky update cycle.
    New aircraft get initialized; existing aircraft get their
    filter updated. Stale aircraft (no update > 5 min) are pruned.
    """

    STALE_THRESHOLD_S = 300  # 5 minutes

    def __init__(self):
        self.filters: dict[str, AircraftKalmanFilter] = {}

    def update(self, icao24: str, lat: float, lon: float,
               timestamp: Optional[float] = None) -> KalmanState:
        """
        Update (or initialize) the filter for an aircraft.
        Returns the smoothed KalmanState after the update.
        """
        t = timestamp or time.time()

        if icao24 not in self.filters:
            self.filters[icao24] = AircraftKalmanFilter(lat, lon, t)
        else:
            self.filters[icao24].update(lat, lon, t)

        return self.filters[icao24].to_schema()

    def predict_position(self, icao24: str,
                         predict_time: Optional[float] = None
                         ) -> Optional[tuple[float, float]]:
        """
        Predict current position for an aircraft based on its last
        Kalman state. Used to smooth rendering between API polls.
        Returns (lat, lon) or None if aircraft not tracked.
        """
        if icao24 not in self.filters:
            return None
        kf = self.filters[icao24]
        t = predict_time or time.time()
        dt = t - kf.last_update
        if dt > self.STALE_THRESHOLD_S:
            return None
        predicted = kf.predict(dt)
        return float(predicted[0]), float(predicted[1])

    def prune_stale(self) -> int:
        """Remove filters for aircraft not seen in STALE_THRESHOLD_S seconds."""
        now = time.time()
        stale = [
            icao for icao, kf in self.filters.items()
            if now - kf.last_update > self.STALE_THRESHOLD_S
        ]
        for icao in stale:
            del self.filters[icao]
        return len(stale)

    @property
    def tracked_count(self) -> int:
        return len(self.filters)
