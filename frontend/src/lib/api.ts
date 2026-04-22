/**
 * lib/api.ts
 * ----------
 * Typed API client for AeroIntel backend.
 * All backend calls go through this module — never raw fetch in components.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

// ── Types (mirrors backend schemas) ──────────────────────────────────────────

export type AircraftCategory =
  | "commercial" | "private" | "military" | "helicopter" | "unknown";

export type AnomalySeverity = "low" | "medium" | "high" | "critical";

export interface AircraftProperties {
  icao24: string;
  callsign: string | null;
  category: AircraftCategory;
  altitude_ft: number | null;
  velocity_kts: number | null;
  heading: number | null;
  vertical_rate_fpm: number | null;
  on_ground: boolean;
  squawk: string | null;
  is_military: boolean;
  pattern_label: "holding" | "racetrack" | "orbit" | null;
  has_anomaly: boolean;
  anomaly_severity: AnomalySeverity | null;
  anomaly_score: number | null;
  origin_country: string | null;
}

export interface AircraftFeature {
  type: "Feature";
  geometry: {
    type: "Point";
    coordinates: [number, number]; // [lon, lat]
  };
  properties: AircraftProperties;
}

export interface AircraftGeoJSON {
  type: "FeatureCollection";
  features: AircraftFeature[];
  metadata: {
    count: number;
    generated_at: number;
    last_pipeline_run: number;
    pipeline_warning: string | null;
  };
}

export interface NLQueryResponse {
  filter_params: Record<string, unknown>;
  explanation: string;
  result_count: number | null;
}

export interface SituationSummary {
  region_label: string;
  aircraft_count: number;
  summary: string;
  notable_items: string[];
  generated_at: number;
}

export interface PipelineStats {
  aircraft_count: number;
  military_count: number;
  anomaly_count: number;
  pattern_count: number;
  kalman_tracked: number;
  cluster_tracked: number;
  last_pipeline_run: number;
  pipeline_duration_s: number;
  pipeline_warning: string | null;
  ws_connections: number;
}

export interface ViewportBounds {
  minLat: number;
  maxLat: number;
  minLon: number;
  maxLon: number;
}

export interface AnomalyExplanation {
  icao24: string;
  callsign: string | null;
  explanation: string;
  anomaly_score: number | null;
  features: Record<string, unknown>;
}

// ── API calls ─────────────────────────────────────────────────────────────────

export async function fetchAircraft(): Promise<AircraftGeoJSON> {
  const res = await fetch(`${API_BASE}/api/aircraft`);
  if (!res.ok) throw new Error(`Aircraft fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchAircraftDetail(icao24: string) {
  const res = await fetch(`${API_BASE}/api/aircraft/${icao24}`);
  if (!res.ok) throw new Error(`Detail fetch failed: ${res.status}`);
  return res.json();
}

export async function submitNLQuery(
  query: string,
  contextCount: number
): Promise<NLQueryResponse> {
  const res = await fetch(`${API_BASE}/api/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, context_aircraft_count: contextCount }),
  });
  if (!res.ok) throw new Error(`Query failed: ${res.status}`);
  return res.json();
}

export async function fetchRegionSummary(
  minLat: number, maxLat: number,
  minLon: number, maxLon: number,
  label?: string
): Promise<SituationSummary> {
  const res = await fetch(`${API_BASE}/api/summary`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ min_lat: minLat, max_lat: maxLat,
                           min_lon: minLon, max_lon: maxLon, label }),
  });
  if (!res.ok) throw new Error(`Summary failed: ${res.status}`);
  return res.json();
}

export async function fetchStats(): Promise<PipelineStats> {
  const res = await fetch(`${API_BASE}/api/stats`);
  if (!res.ok) throw new Error(`Stats fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchAnomalyExplanation(
  icao24: string
): Promise<AnomalyExplanation> {
  const res = await fetch(`${API_BASE}/api/aircraft/${icao24}/explain`);
  if (!res.ok) throw new Error(`Explain fetch failed: ${res.status}`);
  return res.json();
}

// ── Filter helpers ────────────────────────────────────────────────────────────

/**
 * Apply a structured filter dict (from NL query parser) to a GeoJSON
 * feature list. Handles numeric ranges and exact matches.
 */
export function applyFilters(
  features: AircraftFeature[],
  filters: Record<string, unknown>
): AircraftFeature[] {
  return features.filter((f) => {
    const props = f.properties;
    for (const [field, value] of Object.entries(filters)) {
      const prop = props[field as keyof AircraftProperties];

      if (typeof value === "object" && value !== null) {
        // Range filter: { min?: number, max?: number }
        const range = value as { min?: number; max?: number };
        if (typeof prop !== "number") return false;
        if (range.min !== undefined && prop < range.min) return false;
        if (range.max !== undefined && prop > range.max) return false;
      } else {
        // Exact match
        if (prop !== value) return false;
      }
    }
    return true;
  });
}
