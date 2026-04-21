"use client";

/**
 * components/Map.tsx
 * ------------------
 * MapLibre GL map with aircraft rendering layers.
 *
 * Layers (rendered in order):
 *   1. aircraft-base     — all aircraft as colored circles by category
 *   2. pattern-halos     — pulsing ring for holding/racetrack patterns
 *   3. anomaly-halos     — orange/red ring for anomalous aircraft
 *   4. aircraft-selected — highlight ring for selected aircraft
 *   5. aircraft-labels   — callsign text at zoom >= 7
 *
 * Performance:
 *   - setData() called directly on sources (bypasses React reconciliation)
 *   - Viewport culling handled by MapLibre internally
 *   - Position interpolation: MapLibre animates GeoJSON transitions
 */

import { useEffect, useRef, useCallback } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { AircraftFeature, ViewportBounds } from "@/lib/api";


// ── Color palette ─────────────────────────────────────────────────────────────
const COLORS = {
  commercial:  "#4a9eff",
  military:    "#ff4a4a",
  private:     "#c8c8c8",
  helicopter:  "#a0ff4a",
  unknown:     "#888888",
  holding:     "#ffb800",
  racetrack:   "#ff6b00",
  anomaly:     "#ff3300",
  selected:    "#00ff88",
  ground:      "#555566",
};

// CARTO Dark Matter basemap — free, no API key
const BASEMAP_STYLE =
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";


interface MapProps {
  features: AircraftFeature[];
  onAircraftClick: (f: AircraftFeature) => void;
  selectedIcao: string | null;
  showPatterns: boolean;
  showAnomalies: boolean;
  onViewportChange?: (bounds: ViewportBounds) => void;
}

export default function AeroMap({
  features,
  onAircraftClick,
  selectedIcao,
  showPatterns,
  showAnomalies,
  onViewportChange,
}: MapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const featuresRef = useRef<AircraftFeature[]>([]);
  const initializedRef = useRef(false);
  // Keep callback ref current to avoid stale closure in map event handlers
  const onViewportChangeRef = useRef(onViewportChange);
  onViewportChangeRef.current = onViewportChange;

  // Keep features ref current for click handler closure
  featuresRef.current = features;

  // ── Initialize map ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || initializedRef.current) return;
    initializedRef.current = true;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASEMAP_STYLE,
      center: [-40, 35],   // Atlantic — good initial view for global coverage
      zoom: 3,
      attributionControl: false,
    });
    mapRef.current = map;

    map.on("load", () => {
      // ── Sources ───────────────────────────────────────
      map.addSource("aircraft", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      // ── Layer: base aircraft circles ──────────────────
      map.addLayer({
        id: "aircraft-base",
        type: "circle",
        source: "aircraft",
        paint: {
          "circle-radius": [
            "case",
            ["==", ["get", "category"], "military"], 5,
            4
          ],
          "circle-color": [
            "case",
            ["==", ["get", "on_ground"], true],  COLORS.ground,
            ["==", ["get", "is_military"], true], COLORS.military,
            ["==", ["get", "category"], "commercial"], COLORS.commercial,
            ["==", ["get", "category"], "private"],    COLORS.private,
            ["==", ["get", "category"], "helicopter"], COLORS.helicopter,
            COLORS.unknown,
          ],
          "circle-opacity": [
            "case",
            ["==", ["get", "on_ground"], true], 0.4,
            0.85
          ],
          "circle-stroke-width": 0,
        },
      });

      // ── Layer: pattern halos (holding/racetrack) ──────
      map.addLayer({
        id: "pattern-halos",
        type: "circle",
        source: "aircraft",
        filter: ["!=", ["get", "pattern_label"], null],
        paint: {
          "circle-radius": 10,
          "circle-color": "transparent",
          "circle-stroke-width": 2,
          "circle-stroke-color": [
            "case",
            ["==", ["get", "pattern_label"], "racetrack"], COLORS.racetrack,
            COLORS.holding,
          ],
          "circle-stroke-opacity": 0.8,
          "circle-opacity": 0,
        },
      });

      // ── Layer: anomaly halos ───────────────────────────
      map.addLayer({
        id: "anomaly-halos",
        type: "circle",
        source: "aircraft",
        filter: ["==", ["get", "has_anomaly"], true],
        paint: {
          "circle-radius": 12,
          "circle-color": "transparent",
          "circle-stroke-width": 1.5,
          "circle-stroke-color": COLORS.anomaly,
          "circle-stroke-opacity": 0.7,
          "circle-opacity": 0,
        },
      });

      // ── Layer: selected aircraft highlight ────────────
      map.addLayer({
        id: "aircraft-selected",
        type: "circle",
        source: "aircraft",
        filter: ["==", ["get", "icao24"], ""],
        paint: {
          "circle-radius": 14,
          "circle-color": "transparent",
          "circle-stroke-width": 2,
          "circle-stroke-color": COLORS.selected,
          "circle-stroke-opacity": 1.0,
          "circle-opacity": 0,
        },
      });

      // ── Layer: callsign labels (zoom >= 7) ────────────
      map.addLayer({
        id: "aircraft-labels",
        type: "symbol",
        source: "aircraft",
        minzoom: 7,
        filter: ["!=", ["get", "on_ground"], true],
        layout: {
          "text-field": ["coalesce", ["get", "callsign"], ["get", "icao24"]],
          "text-font": ["Open Sans Regular"],
          "text-size": 9,
          "text-offset": [0, 1.2],
          "text-anchor": "top",
          "text-allow-overlap": false,
        },
        paint: {
          "text-color": "#8ab4d4",
          "text-halo-color": "#0a0c0f",
          "text-halo-width": 1,
          "text-opacity": 0.8,
        },
      });

      // ── Click handler ─────────────────────────────────
      map.on("click", "aircraft-base", (e) => {
        if (!e.features?.[0]) return;
        const icao = e.features[0].properties?.icao24;
        const feature = featuresRef.current.find(
          (f) => f.properties.icao24 === icao
        );
        if (feature) onAircraftClick(feature);
      });

      // Cursor pointer on hover
      map.on("mouseenter", "aircraft-base", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "aircraft-base", () => {
        map.getCanvas().style.cursor = "";
      });

      // Scale control
      map.addControl(new maplibregl.ScaleControl({ unit: "nautical" }), "bottom-right");

      // Report initial viewport bounds after map loads
      const reportBounds = () => {
        const b = map.getBounds();
        onViewportChangeRef.current?.({
          minLat: b.getSouth(),
          maxLat: b.getNorth(),
          minLon: b.getWest(),
          maxLon: b.getEast(),
        });
      };
      reportBounds();
      map.on("moveend", reportBounds);
    });

    return () => {
      map.remove();
      mapRef.current = null;
      initializedRef.current = false;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Update aircraft data ────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const source = map.getSource("aircraft") as maplibregl.GeoJSONSource;
    if (!source) return;

    source.setData({
      type: "FeatureCollection",
      features,
    });
  }, [features]);

  // ── Update selected aircraft highlight ─────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    map.setFilter("aircraft-selected", [
      "==", ["get", "icao24"], selectedIcao ?? "",
    ]);
  }, [selectedIcao]);

  // ── Toggle pattern/anomaly halos ───────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const vis = showPatterns ? "visible" : "none";
    map.setLayoutProperty("pattern-halos", "visibility", vis);
  }, [showPatterns]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const vis = showAnomalies ? "visible" : "none";
    map.setLayoutProperty("anomaly-halos", "visibility", vis);
  }, [showAnomalies]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full"
      style={{ background: "#0a0c0f" }}
    />
  );
}
