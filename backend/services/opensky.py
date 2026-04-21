"""
services/opensky.py
-------------------
ADS-B data ingestion from OpenSky Network and adsb.lol.

OpenSky Network: commercial + private flights (~5,000 aircraft globally)
adsb.lol:        military aircraft broadcasting ADS-B

OpenSky anonymous rate limit: 100 requests/day (one per ~15 minutes)
With credentials: higher limits available (free registration).

Data pipeline per cycle:
    1. Fetch raw state vectors from OpenSky REST API
    2. Fetch military tracks from adsb.lol
    3. Parse + validate via Pydantic schemas
    4. Pass to Kalman filter service for position smoothing
    5. Pass to clustering service for trajectory history
    6. Pass to anomaly service for observation recording
    7. Return enriched Aircraft list to main app state
"""

import httpx
import asyncio
import time
from typing import Optional
from models.schemas import (
    RawAircraftState, Aircraft, AircraftCategory,
    KalmanState
)


class OpenSkyRateLimitError(Exception):
    """Raised when OpenSky returns 429 (rate limited) or 503 (quota exhausted)."""
    pass


class OpenSkyFetchError(Exception):
    """Raised when OpenSky auth or response handling fails for non-rate-limit reasons."""
    pass


OPENSKY_URL = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
ADSB_LOL_MILITARY_URL = "https://api.adsb.lol/v2/mil"

# Meters to feet conversion
M_TO_FT = 3.28084
# m/s to knots conversion
MPS_TO_KTS = 1.94384
# m/s to ft/min conversion
MPS_TO_FPM = 196.85


def _categorize(raw: RawAircraftState, is_military: bool) -> AircraftCategory:
    """Heuristic aircraft categorization from ADS-B data alone."""
    if is_military:
        return AircraftCategory.MILITARY

    callsign = (raw.callsign or "").strip().upper()

    # ICAO airline callsigns are 3 alpha + digits (e.g., UAL123, DAL456)
    if len(callsign) >= 4 and callsign[:3].isalpha() and callsign[3:].isdigit():
        return AircraftCategory.COMMERCIAL

    # N-numbers (US civil registration) → private
    if callsign.startswith("N") and len(callsign) >= 3:
        return AircraftCategory.PRIVATE

    # Helicopter heuristic: very low altitude + low speed
    if (raw.baro_altitude is not None and raw.baro_altitude < 300 and
            raw.velocity is not None and raw.velocity < 50):
        return AircraftCategory.HELICOPTER

    return AircraftCategory.UNKNOWN


def _parse_raw_state(state_vector: list) -> Optional[RawAircraftState]:
    """
    Parse an OpenSky state vector array into a RawAircraftState.
    OpenSky returns states as arrays, not dicts.
    Array indices per OpenSky API docs:
        [0] icao24, [1] callsign, [2] origin_country,
        [3] time_position, [4] last_contact,
        [5] longitude, [6] latitude, [7] baro_altitude,
        [8] on_ground, [9] velocity, [10] true_track,
        [11] vertical_rate, [12] sensors, [13] geo_altitude,
        [14] squawk, [15] spi, [16] position_source
    """
    try:
        return RawAircraftState(
            icao24=state_vector[0],
            callsign=state_vector[1],
            origin_country=state_vector[2],
            time_position=state_vector[3],
            last_contact=state_vector[4] or time.time(),
            longitude=state_vector[5],
            latitude=state_vector[6],
            baro_altitude=state_vector[7],
            on_ground=state_vector[8] or False,
            velocity=state_vector[9],
            true_track=state_vector[10],
            vertical_rate=state_vector[11],
            geo_altitude=state_vector[13],
            squawk=state_vector[14],
            spi=state_vector[15] or False,
            position_source=state_vector[16],
        )
    except (IndexError, TypeError, ValueError):
        return None


def _raw_to_aircraft(raw: RawAircraftState,
                     is_military: bool = False,
                     kalman_state: Optional[KalmanState] = None) -> Aircraft:
    """
    Convert a validated RawAircraftState to an enriched Aircraft object.
    Applies unit conversions (m→ft, m/s→kts, m/s→fpm).
    Kalman-smoothed position used if available, raw otherwise.
    """
    # Unit conversions
    alt_ft = (raw.baro_altitude * M_TO_FT) if raw.baro_altitude else None
    speed_kts = (raw.velocity * MPS_TO_KTS) if raw.velocity else None
    vrate_fpm = (raw.vertical_rate * MPS_TO_FPM) if raw.vertical_rate else None

    # Position: prefer Kalman-smoothed
    lat = kalman_state.lat if kalman_state else raw.latitude
    lon = kalman_state.lon if kalman_state else raw.longitude

    return Aircraft(
        icao24=raw.icao24,
        callsign=(raw.callsign or "").strip() or None,
        origin_country=raw.origin_country,
        latitude=lat,
        longitude=lon,
        altitude_ft=round(alt_ft, 0) if alt_ft else None,
        velocity_kts=round(speed_kts, 1) if speed_kts else None,
        heading=raw.true_track,
        vertical_rate_fpm=round(vrate_fpm, 0) if vrate_fpm else None,
        raw_latitude=raw.latitude,
        raw_longitude=raw.longitude,
        category=_categorize(raw, is_military),
        on_ground=raw.on_ground,
        squawk=raw.squawk,
        kalman_state=kalman_state,
        last_contact=raw.last_contact,
        is_military=is_military,
    )


class OpenSkyService:
    """
    Fetches and parses ADS-B state vectors from OpenSky Network.
    Optionally authenticated for higher rate limits.
    """

    def __init__(self, client_id: str = "", client_secret: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret
        self._last_fetch_time: float = 0.0
        self._fetch_count: int = 0
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

    async def _get_access_token(self) -> Optional[str]:
        """Return a cached OAuth token, refreshing when near expiry."""
        now = time.time()
        if self._access_token and now < self._token_expires_at - 30:
            return self._access_token

        if not (self.client_id and self.client_secret):
            return None

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    OPENSKY_TOKEN_URL,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                )
                resp.raise_for_status()
                try:
                    data = resp.json()
                except ValueError as e:
                    raise OpenSkyFetchError(
                        "OpenSky token endpoint returned a non-JSON response"
                    ) from e

            self._access_token = data.get("access_token", "")
            if not self._access_token:
                raise OpenSkyFetchError("OpenSky token response did not include an access token")
            expires_in = int(data.get("expires_in", 1800))
            self._token_expires_at = now + expires_in
            return self._access_token or None

        except httpx.HTTPStatusError as e:
            raise OpenSkyFetchError(
                f"OpenSky token request failed (HTTP {e.response.status_code})"
            ) from e
        except OpenSkyFetchError:
            raise
        except Exception as e:
            raise OpenSkyFetchError(
                f"OpenSky token request error [{type(e).__name__}]: {e!r}"
            ) from e

    async def fetch_states(self,
                           bbox: Optional[tuple] = None) -> list[RawAircraftState]:
        """
        Fetch current ADS-B state vectors from OpenSky.

        bbox: optional (min_lat, max_lat, min_lon, max_lon) to limit scope.
              None = global fetch (larger response, ~2-5MB).

        Returns list of validated RawAircraftState objects.
        Positions without lat/lon are excluded (aircraft on ground w/ no GPS).
        """
        params = {}
        if bbox:
            params = {
                "lamin": bbox[0], "lamax": bbox[1],
                "lomin": bbox[2], "lomax": bbox[3],
            }

        try:
            headers = {}
            token = await self._get_access_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

            async with httpx.AsyncClient(timeout=15.0) as client:
                kwargs = {"params": params, "headers": headers}

                resp = await client.get(OPENSKY_URL, **kwargs)
                resp.raise_for_status()
                try:
                    data = resp.json()
                except ValueError as e:
                    raise OpenSkyFetchError(
                        "OpenSky returned a non-JSON response; upstream may be blocking the request"
                    ) from e

            self._last_fetch_time = time.time()
            self._fetch_count += 1

            states = data.get("states") or []
            parsed = []
            for sv in states:
                raw = _parse_raw_state(sv)
                if raw and raw.latitude and raw.longitude:
                    parsed.append(raw)

            print(f"[OpenSky] Retrieved {len(parsed)} aircraft states")

            return parsed

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 503):
                raise OpenSkyRateLimitError(
                    f"OpenSky rate limit hit (HTTP {e.response.status_code})"
                ) from e
            raise OpenSkyFetchError(
                f"OpenSky request failed (HTTP {e.response.status_code})"
            ) from e
        except httpx.TimeoutException:
            raise OpenSkyFetchError("OpenSky request timed out")
        except OpenSkyFetchError:
            raise
        except Exception as e:
            raise OpenSkyFetchError(
                f"OpenSky unexpected error [{type(e).__name__}]: {e!r}"
            ) from e


class ADSBLolService:
    """
    Fetches military aircraft from adsb.lol — no API key required.
    Returns in a compatible format with OpenSky data.
    """

    async def fetch_military(self) -> list[RawAircraftState]:
        """Fetch military ADS-B tracks from adsb.lol."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(ADSB_LOL_MILITARY_URL)
                resp.raise_for_status()
                data = resp.json()

            aircraft_list = data.get("ac") or []
            results = []

            for ac in aircraft_list:
                try:
                    lat = ac.get("lat")
                    lon = ac.get("lon")
                    if lat is None or lon is None:
                        continue

                    raw = RawAircraftState(
                        icao24=ac.get("hex", ""),
                        callsign=(ac.get("flight") or "").strip() or None,
                        origin_country=None,
                        last_contact=time.time(),
                        latitude=float(lat),
                        longitude=float(lon),
                        baro_altitude=float(ac["alt_baro"]) / M_TO_FT
                            if ac.get("alt_baro") and ac["alt_baro"] != "ground" else None,
                        on_ground=ac.get("alt_baro") == "ground",
                        velocity=float(ac["gs"]) / MPS_TO_KTS
                            if ac.get("gs") else None,
                        true_track=float(ac["track"]) if ac.get("track") else None,
                        vertical_rate=float(ac["baro_rate"]) / MPS_TO_FPM
                            if ac.get("baro_rate") else None,
                        squawk=ac.get("squawk"),
                    )
                    results.append(raw)
                except (KeyError, ValueError, TypeError):
                    continue

            return results

        except Exception as e:
            print(f"[adsb.lol] Error fetching military data: {e}")
            return []
