"""
services/llm.py
---------------
Claude API integration for AeroIntel's intelligence layer.

Three capabilities:

1. SITUATION SUMMARY
   User selects a region or bounding box. We pass all aircraft in that
   region as structured JSON. Claude returns a plain-English intelligence
   summary of what's happening — patterns, anomalies, notable activity.

2. NATURAL LANGUAGE QUERY
   User types: "Show me military aircraft above 30,000 feet in the last hour"
   Claude parses this into a structured filter dict that the API applies
   to the aircraft list. LLM-as-query-parser pattern.

3. ANOMALY EXPLANATION
   When IsolationForest or DBSCAN flags an aircraft, we pass the feature
   vector and pattern data to Claude for a plain-English explanation of
   WHY it's anomalous. Closes the interpretability loop.

All prompts use structured JSON for both input and output where possible,
with explicit XML tags to reliably extract structured data from responses.
"""

import json
import time
import re
from typing import Optional
import anthropic
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""

    class Config:
        env_file = "backend/.env"
        extra = "ignore"


settings = Settings()

# Model to use — Sonnet 4.6 is fast and cost-effective for structured tasks
MODEL = "claude-sonnet-4-6"


# ── System prompts ───────────────────────────────────────────────────────────

SYSTEM_SITUATION = """You are an aviation intelligence analyst assistant integrated into a real-time OSINT dashboard called AeroIntel.

You receive live ADS-B telemetry data including aircraft positions, callsigns, altitudes, speeds, headings, and behavioral flags from an ML pipeline (Kalman filtering, DBSCAN pattern detection, IsolationForest anomaly scoring).

Your job is to synthesize this data into concise, factual intelligence summaries. You work strictly from public, open-source data. Do not speculate beyond what the data supports. Be specific about callsigns, altitudes, and patterns when relevant. Use aviation terminology appropriately.

Respond in plain English. Be concise but substantive. Avoid dramatic language — this is an analytical tool, not entertainment."""

SYSTEM_QUERY = """You are a query parser for an aviation intelligence dashboard called AeroIntel.

The user will provide a natural language query about aircraft data. Your job is to parse that query into a structured JSON filter object that can be applied to a list of aircraft objects.

Aircraft object fields available for filtering:
- callsign (string)
- altitude_ft (number)
- velocity_kts (number)
- heading (number, 0-360)
- category (string: "commercial", "private", "military", "helicopter", "unknown")
- is_military (boolean)
- on_ground (boolean)
- squawk (string)
- origin_country (string)
- has_anomaly (boolean)
- pattern_label (string: "holding", "racetrack", "orbit", null)

Output ONLY a JSON object with this exact structure, no other text:
{
  "filters": {
    "field": "value or range object"
  },
  "explanation": "one sentence explaining what the query will show"
}

For numeric ranges use: {"min": X, "max": Y}
Example: altitude_ft >= 30000 → {"min": 30000}
"""

SYSTEM_ANOMALY = """You are an aviation safety analyst assistant. You will receive behavioral data about an aircraft flagged as anomalous by a machine learning system (IsolationForest anomaly detection).

Your job is to provide a brief, plain-English explanation of why this aircraft's behavior appears anomalous based on the feature data provided. Be specific about which features are unusual. Acknowledge uncertainty appropriately — ML anomaly detection produces false positives.

Keep your explanation to 2-3 sentences. Be factual and analytical, not alarming."""


# ── Service class ─────────────────────────────────────────────────────────────

class LLMService:
    """
    Wraps Anthropic Claude API for AeroIntel's three intelligence tasks.
    Handles prompt construction, API calls, and response parsing.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._request_count = 0
        self._last_request_time = 0.0

    def _call(self, system: str, user: str,
              max_tokens: int = 512) -> Optional[str]:
        """
        Make a single Claude API call with basic error handling.
        Returns the text response or None on failure.
        """
        try:
            self._request_count += 1
            self._last_request_time = time.time()

            message = self.client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return message.content[0].text if message.content else None
        except anthropic.APIError as e:
            print(f"[LLM] Anthropic API error: {e}")
            return None
        except Exception as e:
            print(f"[LLM] Unexpected error: {e}")
            return None

    # ── Capability 1: Situation Summary ────────────────────────────────────

    def generate_situation_summary(self,
                                   region_label: str,
                                   aircraft_data: list[dict]) -> Optional[str]:
        """
        Generate a plain-English intelligence summary for a region.

        aircraft_data: list of dicts with keys:
            callsign, category, altitude_ft, velocity_kts, heading,
            is_military, pattern_label, anomalies, origin_country
        """
        if not aircraft_data:
            return f"No aircraft currently tracked in {region_label}."

        # Summarize the data to keep prompt size manageable
        total = len(aircraft_data)
        military = sum(1 for a in aircraft_data if a.get("is_military"))
        commercial = sum(1 for a in aircraft_data
                         if a.get("category") == "commercial")
        patterns = [a for a in aircraft_data if a.get("pattern_label")]
        anomalies = [a for a in aircraft_data if a.get("anomalies")]

        # Notable aircraft: military, anomalous, or loitering
        notable = [
            a for a in aircraft_data
            if a.get("is_military") or a.get("pattern_label") or a.get("anomalies")
        ][:10]  # cap at 10 for prompt size

        prompt = f"""Region: {region_label}
Total aircraft: {total} ({military} military, {commercial} commercial)
Aircraft with loitering patterns: {len(patterns)}
Aircraft with behavioral anomalies: {len(anomalies)}

Notable aircraft data:
{json.dumps(notable, indent=2)}

Please provide an intelligence summary of current aviation activity in this region. Focus on anything operationally significant: military activity, loitering patterns, anomalous behavior, or unusual traffic density."""

        return self._call(SYSTEM_SITUATION, prompt, max_tokens=400)

    # ── Capability 2: Natural Language Query ───────────────────────────────

    def parse_nl_query(self, query: str,
                       aircraft_count: int) -> Optional[dict]:
        """
        Parse a natural language query into a structured filter dict.

        Returns a dict with keys:
            filters: dict of field → value/range
            explanation: str
        Returns None on parse failure.
        """
        prompt = f"""User query: "{query}"
Current aircraft in view: {aircraft_count}

Parse this into a JSON filter object."""

        response = self._call(SYSTEM_QUERY, prompt, max_tokens=300)
        if not response:
            return None

        # Extract JSON from response
        try:
            # Strip any markdown code fences if present
            cleaned = re.sub(r"```(?:json)?|```", "", response).strip()
            parsed = json.loads(cleaned)
            return parsed
        except json.JSONDecodeError:
            print(f"[LLM] Failed to parse query response as JSON: {response}")
            return None

    # ── Capability 3: Anomaly Explanation ──────────────────────────────────

    def explain_anomaly(self,
                        callsign: Optional[str],
                        icao24: str,
                        anomaly_score: float,
                        features: dict,
                        pattern_label: Optional[str] = None) -> Optional[str]:
        """
        Generate a plain-English explanation for a behavioral anomaly.

        features dict should contain:
            altitude_delta_ft, speed_delta_kts, heading_variance,
            vertical_rate_fpm, update_gap_s, squawk_changed
        """
        aircraft_id = callsign or icao24

        prompt = f"""Aircraft: {aircraft_id}
Anomaly score: {anomaly_score:.3f} (threshold: -0.15, lower = more anomalous)
Detected pattern: {pattern_label or "none"}

Feature vector (5-minute rolling window):
- Altitude change: {features.get("altitude_delta_ft", 0):.0f} ft
- Speed change: {features.get("speed_delta_kts", 0):.1f} kts
- Heading variance (0=steady, 1=random): {features.get("heading_variance", 0):.3f}
- Vertical rate: {features.get("vertical_rate_fpm", 0):.0f} ft/min
- Update gap: {features.get("update_gap_s", 0):.0f} seconds
- Squawk changed: {features.get("squawk_changed", False)}

In 2-3 sentences, explain which of these features appear anomalous and what flight behavior they might indicate. Acknowledge uncertainty."""

        return self._call(SYSTEM_ANOMALY, prompt, max_tokens=200)

    @property
    def stats(self) -> dict:
        return {
            "total_requests": self._request_count,
            "last_request": self._last_request_time,
        }
