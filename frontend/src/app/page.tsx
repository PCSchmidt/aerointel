"use client";

/**
 * app/page.tsx
 * ------------
 * AeroIntel main dashboard.
 *
 * Layout: full-screen dark map with floating HUD panels.
 * - Top bar: connection status, aircraft counts, pipeline stats
 * - Left panel: layer toggles, filter controls
 * - Right panel: Intel panel (NL query + situation summary)
 * - Bottom: selected aircraft detail
 * - Map: MapLibre GL with aircraft layer
 */

import { useState, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import { useAircraftWebSocket } from "@/hooks/useWebSocket";
import { AircraftFeature, ViewportBounds, applyFilters } from "@/lib/api";
import IntelPanel from "@/components/IntelPanel";
import StatusBar, { DetailPanel, AlertBanner } from "@/components/StatusBar";

// Map imported dynamically — MapLibre uses browser APIs
const AeroMap = dynamic(() => import("@/components/Map"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full flex items-center justify-center bg-[#0a0c0f]">
      <div className="text-[#34d399] font-mono text-sm tracking-widest animate-pulse">
        INITIALIZING RADAR...
      </div>
    </div>
  ),
});

export default function Dashboard() {
  const { data, connected, lastUpdate, error, pipelineWarning } = useAircraftWebSocket();

  // Active filters from NL query or manual controls
  const [activeFilters, setActiveFilters] = useState<Record<string, unknown>>({});
  const [filterExplanation, setFilterExplanation] = useState<string>("");

  // Selected aircraft for detail panel
  const [selectedAircraft, setSelectedAircraft] = useState<AircraftFeature | null>(null);

  // Current map viewport bounds (updated on every pan/zoom)
  const [viewportBounds, setViewportBounds] = useState<ViewportBounds | null>(null);

  // Layer visibility toggles
  const [showCommercial, setShowCommercial] = useState(true);
  const [showMilitary, setShowMilitary] = useState(true);
  const [showPrivate, setShowPrivate] = useState(true);
  const [showAnomalies, setShowAnomalies] = useState(true);
  const [showPatterns, setShowPatterns] = useState(true);
  const [intelPanelOpen, setIntelPanelOpen] = useState(false);

  // Apply filters + layer toggles to aircraft features
  const filteredFeatures = useMemo(() => {
    if (!data?.features) return [];
    let features = data.features;

    // Layer visibility
    features = features.filter((f) => {
      const p = f.properties;
      if (p.category === "commercial" && !showCommercial) return false;
      if (p.is_military && !showMilitary) return false;
      if ((p.category === "private" || p.category === "unknown") && !showPrivate) return false;
      return true;
    });

    // NL query filters
    if (Object.keys(activeFilters).length > 0) {
      features = applyFilters(features, activeFilters);
    }

    return features;
  }, [data, activeFilters, showCommercial, showMilitary, showPrivate]);

  // Critical anomalies for alert banner
  const criticalAnomalies = useMemo(
    () => filteredFeatures.filter(
      (f) => f.properties.anomaly_severity === "critical" ||
             f.properties.anomaly_severity === "high"
    ),
    [filteredFeatures]
  );

  const handleAircraftClick = useCallback((feature: AircraftFeature) => {
    setSelectedAircraft(feature);
  }, []);

  const handleFilterApply = useCallback(
    (filters: Record<string, unknown>, explanation: string) => {
      setActiveFilters(filters);
      setFilterExplanation(explanation);
    },
    []
  );

  const clearFilters = useCallback(() => {
    setActiveFilters({});
    setFilterExplanation("");
  }, []);

  const stats = data?.metadata;
  const totalCount = data?.features.length ?? 0;
  const militaryCount = data?.features.filter((f) => f.properties.is_military).length ?? 0;
  const anomalyCount = data?.features.filter((f) => f.properties.has_anomaly).length ?? 0;
  const patternCount = data?.features.filter((f) => f.properties.pattern_label).length ?? 0;

  return (
    <main className="relative w-screen h-screen overflow-hidden bg-[#0a0c0f]">

      {/* ── Full-screen map ── */}
      <div className="absolute inset-0">
        <AeroMap
          features={filteredFeatures}
          onAircraftClick={handleAircraftClick}
          selectedIcao={selectedAircraft?.properties.icao24 ?? null}
          showPatterns={showPatterns}
          showAnomalies={showAnomalies}
          onViewportChange={setViewportBounds}
        />
      </div>

      {/* ── Top status bar ── */}
      <StatusBar
        connected={connected}
        lastUpdate={lastUpdate}
        totalCount={totalCount}
        filteredCount={filteredFeatures.length}
        militaryCount={militaryCount}
        anomalyCount={anomalyCount}
        patternCount={patternCount}
        filterActive={Object.keys(activeFilters).length > 0}
        filterExplanation={filterExplanation}
        onClearFilter={clearFilters}
        onToggleIntel={() => setIntelPanelOpen((v) => !v)}
        intelOpen={intelPanelOpen}
        error={error}
        pipelineWarning={pipelineWarning}
      />

      {/* ── Alert banner (critical anomalies) ── */}
      {criticalAnomalies.length > 0 && (
        <AlertBanner
          alerts={criticalAnomalies}
          onSelect={(f) => { setSelectedAircraft(f); }}
        />
      )}

      {/* ── Left layer controls ── */}
      <div className="absolute left-4 top-20 z-10 flex flex-col gap-2">
        <div className="bg-[#0d1117]/90 border border-[#1e2a38] p-3 backdrop-blur-sm">
          <div className="text-[#4a7a9b] font-sans text-[10px] tracking-widest mb-3 uppercase">
            Layers
          </div>
          {[
            { label: "Commercial", value: showCommercial, setter: setShowCommercial, color: "#4a9eff" },
            { label: "Military",   value: showMilitary,   setter: setShowMilitary,   color: "#ff4a4a" },
            { label: "Private",    value: showPrivate,    setter: setShowPrivate,     color: "#b8b8b8" },
            { label: "Patterns",   value: showPatterns,   setter: setShowPatterns,    color: "#ffb800" },
            { label: "Anomalies",  value: showAnomalies,  setter: setShowAnomalies,   color: "#ff6b00" },
          ].map(({ label, value, setter, color }) => (
            <button
              key={label}
              onClick={() => setter((v: boolean) => !v)}
              className="flex items-center gap-2 w-full py-1 px-0 font-sans text-xs transition-opacity"
              style={{ opacity: value ? 1 : 0.35 }}
            >
              <span
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ backgroundColor: color, boxShadow: value ? `0 0 4px ${color}` : "none" }}
              />
              <span style={{ color: value ? color : "#4a7a9b" }}>{label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* ── Intel panel (right side, toggleable) ── */}
      <div
        className="absolute top-16 right-0 z-10 transition-transform duration-300"
        style={{ transform: intelPanelOpen ? "translateX(0)" : "translateX(100%)" }}
      >
        <IntelPanel
          aircraftCount={filteredFeatures.length}
          onFilterApply={handleFilterApply}
          onClose={() => setIntelPanelOpen(false)}
          viewportBounds={viewportBounds ?? undefined}
          aircraftFeatures={filteredFeatures}
        />
      </div>

      {/* ── Aircraft detail panel (bottom) ── */}
      {selectedAircraft && (
        <DetailPanel
          aircraft={selectedAircraft}
          onClose={() => setSelectedAircraft(null)}
        />
      )}

    </main>
  );
}
