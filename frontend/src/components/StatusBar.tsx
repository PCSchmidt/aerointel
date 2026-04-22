"use client";

/**
 * components/StatusBar.tsx
 */

import { useState, useEffect } from "react";
import { AircraftFeature, AnomalyExplanation, fetchAnomalyExplanation } from "@/lib/api";

interface StatusBarProps {
  connected: boolean;
  lastUpdate: Date | null;
  totalCount: number;
  filteredCount: number;
  militaryCount: number;
  anomalyCount: number;
  patternCount: number;
  filterActive: boolean;
  filterExplanation: string;
  onClearFilter: () => void;
  onToggleIntel: () => void;
  intelOpen: boolean;
  error: string | null;
  pipelineWarning: string | null;
}

export function StatusBar({
  connected, lastUpdate, totalCount, filteredCount,
  militaryCount, anomalyCount, patternCount,
  filterActive, filterExplanation, onClearFilter,
  onToggleIntel, intelOpen, error, pipelineWarning,
}: StatusBarProps) {
  return (
    <div className="absolute top-0 left-0 right-0 z-20 h-14 bg-[#0a0c0f]/95 border-b border-[#1e2a38] backdrop-blur-sm flex items-center px-4 gap-4">

      {/* Logo */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <div className="w-2 h-2 rounded-full bg-[#34d399]"
             style={{ boxShadow: connected ? "0 0 6px #34d399" : "none" }} />
        <span className="text-[#34d399] font-sans text-sm tracking-[0.3em] uppercase font-bold">
          AeroIntel
        </span>
      </div>

      <div className="w-px h-6 bg-[#1e2a38]" />

      {/* Connection status */}
      <div className="font-mono text-[10px] flex-shrink-0">
        <span className={connected ? "text-[#34d399]" : "text-[#ff4a4a]"}>
          {connected ? "LIVE" : "OFFLINE"}
        </span>
        {lastUpdate && (
          <span className="text-[#3a5a6a] ml-2">
            {lastUpdate.toLocaleTimeString()}
          </span>
        )}
      </div>

      <div className="w-px h-6 bg-[#1e2a38]" />

      {/* Stats */}
      <div className="flex items-center gap-4 font-mono text-[10px]">
        <span>
          <span className="text-[#4a9eff]">{filterActive ? filteredCount : totalCount}</span>
          <span className="text-[#3a5a6a]"> aircraft</span>
          {filterActive && totalCount !== filteredCount && (
            <span className="text-[#3a5a6a]"> / {totalCount}</span>
          )}
        </span>
        {militaryCount > 0 && (
          <span>
            <span className="text-[#ff4a4a]">{militaryCount}</span>
            <span className="text-[#3a5a6a]"> mil</span>
          </span>
        )}
        {anomalyCount > 0 && (
          <span>
            <span className="text-[#ff6600]">{anomalyCount}</span>
            <span className="text-[#3a5a6a]"> anomaly</span>
          </span>
        )}
        {patternCount > 0 && (
          <span>
            <span className="text-[#ffb800]">{patternCount}</span>
            <span className="text-[#3a5a6a]"> pattern</span>
          </span>
        )}
      </div>

      {/* Active filter indicator */}
      {filterActive && (
        <>
          <div className="w-px h-6 bg-[#1e2a38]" />
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-[#34d399] font-sans text-[9px] uppercase tracking-wider flex-shrink-0">
              FILTER:
            </span>
            <span className="text-[#4a9eff] font-mono text-[9px] truncate">
              {filterExplanation}
            </span>
            <button
              onClick={onClearFilter}
              className="text-[#3a5a6a] hover:text-[#ff4a4a] font-mono text-[9px] flex-shrink-0 ml-1"
            >
              [×]
            </button>
          </div>
        </>
      )}

      {error && (
        <>
          <div className="w-px h-6 bg-[#1e2a38]" />
          <span className="text-[#ff4a4a] font-mono text-[9px]">{error}</span>
        </>
      )}

      {pipelineWarning && !error && (
        <>
          <div className="w-px h-6 bg-[#1e2a38]" />
          <span className="text-[#f59e0b] font-mono text-[9px]">
            ⚠ {pipelineWarning}
          </span>
        </>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Intel panel toggle */}
      <button
        onClick={onToggleIntel}
        className={`font-sans text-[10px] tracking-widest uppercase px-3 py-1.5 border transition-all ${
          intelOpen
            ? "border-[#34d399]/60 text-[#34d399] bg-[#042a1a]"
            : "border-[#1e2a38] text-[#4a7a9b] hover:border-[#34d399]/30 hover:text-[#34d399]"
        }`}
      >
        AI INTEL
      </button>
    </div>
  );
}

export default StatusBar;


/**
 * components/DetailPanel.tsx — Aircraft detail panel (bottom bar)
 */

interface DetailPanelProps {
  aircraft: AircraftFeature;
  onClose: () => void;
}

export function DetailPanel({ aircraft, onClose }: DetailPanelProps) {
  const p = aircraft.properties;

  // Fetch LLM explanation + feature vector when an anomalous aircraft is selected
  const [explainData, setExplainData] = useState<AnomalyExplanation | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);

  useEffect(() => {
    if (!p.has_anomaly) {
      setExplainData(null);
      return;
    }
    setExplainData(null);
    setExplainLoading(true);
    fetchAnomalyExplanation(p.icao24)
      .then((r) => setExplainData(r))
      .catch(() => setExplainData(null))
      .finally(() => setExplainLoading(false));
  }, [p.icao24, p.has_anomaly]);

  const categoryColor = {
    commercial: "#4a9eff",
    military:   "#ff4a4a",
    private:    "#c8c8c8",
    helicopter: "#a0ff4a",
    unknown:    "#888888",
  }[p.category] ?? "#888888";

  return (
    <div className="absolute bottom-0 left-0 right-0 z-20 bg-[#0a0c0f]/97 border-t border-[#1e2a38] backdrop-blur-sm">
      <div className="flex items-start gap-6 px-5 py-3">

        {/* Identity */}
        <div className="flex-shrink-0">
          <div className="font-mono text-base font-bold" style={{ color: categoryColor }}>
            {p.callsign || p.icao24.toUpperCase()}
          </div>
          <div className="text-[#3a5a6a] font-mono text-[9px] mt-0.5">
            {p.icao24.toUpperCase()} · {p.category.toUpperCase()}
            {p.is_military && " · MILITARY"}
          </div>
          {p.origin_country && (
            <div className="text-[#4a7a9b] font-mono text-[9px]">{p.origin_country}</div>
          )}
        </div>

        <div className="w-px self-stretch bg-[#1e2a38]" />

        {/* Telemetry */}
        <div className="grid grid-cols-4 gap-x-6 gap-y-1">
          {[
            { label: "ALT",    value: p.altitude_ft     ? `${p.altitude_ft.toLocaleString()} ft`   : "—" },
            { label: "SPD",    value: p.velocity_kts    ? `${p.velocity_kts} kts`                  : "—" },
            { label: "HDG",    value: p.heading         ? `${Math.round(p.heading)}°`               : "—" },
            { label: "V/S",    value: p.vertical_rate_fpm ? `${p.vertical_rate_fpm > 0 ? "+" : ""}${p.vertical_rate_fpm} fpm` : "—" },
            { label: "SQUAWK", value: p.squawk || "—" },
            { label: "STATUS", value: p.on_ground ? "GROUND" : "AIRBORNE" },
            { label: "SCORE",  value: p.anomaly_score !== null ? p.anomaly_score?.toFixed(3) : "—" },
            { label: "PATTERN", value: p.pattern_label?.toUpperCase() || "—" },
          ].map(({ label, value }) => (
            <div key={label}>
              <div className="text-[#3a5a6a] font-mono text-[8px] uppercase tracking-wider">{label}</div>
              <div className={`font-mono text-[11px] mt-0.5 ${
                label === "SQUAWK" && ["7700","7600","7500"].includes(value)
                  ? "text-[#ff3300]"
                  : label === "PATTERN" && value !== "—"
                  ? "text-[#ffb800]"
                  : label === "SCORE" && p.has_anomaly
                  ? "text-[#ff6600]"
                  : "text-[#8ab4d4]"
              }`}>
                {value}
              </div>
            </div>
          ))}
        </div>

        {/* Anomaly detail */}
        {p.has_anomaly && (
          <>
            <div className="w-px self-stretch bg-[#1e2a38]" />
            <div className="flex-shrink-0 max-w-xs">
              <div className="text-[#ff6600] font-mono text-[9px] uppercase tracking-widest mb-1">
                ⚠ ANOMALY DETECTED
              </div>
              <div className="text-[#3a5a6a] font-mono text-[9px]">
                Severity: <span className={
                  p.anomaly_severity === "critical" ? "text-[#ff3300]" :
                  p.anomaly_severity === "high"     ? "text-[#ff6600]" :
                  p.anomaly_severity === "medium"   ? "text-[#ffb800]" :
                  "text-[#8ab4d4]"
                }>{p.anomaly_severity?.toUpperCase()}</span>
              </div>
              {explainLoading && (
                <div className="text-[#34d399] font-mono text-[9px] mt-1.5 animate-pulse">
                  Asking Claude...
                </div>
              )}
              {explainData && !explainLoading && (
                <>
                  {/* IsolationForest feature vector */}
                  <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5">
                    {[
                      { label: "ALT Δ",   value: `${(explainData.features.altitude_delta_ft  as number ?? 0).toFixed(0)} ft` },
                      { label: "SPD Δ",   value: `${(explainData.features.speed_delta_kts     as number ?? 0).toFixed(1)} kts` },
                      { label: "HDG VAR", value:  (explainData.features.heading_variance      as number ?? 0).toFixed(3) },
                      { label: "V/S",     value: `${(explainData.features.vertical_rate_fpm   as number ?? 0).toFixed(0)} fpm` },
                      { label: "GAP",     value: `${(explainData.features.update_gap_s        as number ?? 0).toFixed(0)}s` },
                      { label: "SQUAWK",  value:  (explainData.features.squawk_changed as boolean) ? "CHANGED" : "stable" },
                    ].map(({ label, value }) => (
                      <div key={label} className="flex justify-between gap-1">
                        <span className="text-[#2a4a5a] font-mono text-[8px]">{label}</span>
                        <span className="text-[#6a8a9a] font-mono text-[8px]">{value}</span>
                      </div>
                    ))}
                  </div>
                  {/* Claude narrative */}
                  <div className="text-[#8ab4d4] font-mono text-[10px] mt-2 leading-relaxed max-w-[220px]">
                    {explainData.explanation}
                  </div>
                </>
              )}
            </div>
          </>
        )}

        <div className="flex-1" />

        <button
          onClick={onClose}
          className="text-[#3a5a6a] hover:text-[#ff4a4a] font-mono text-xs self-start"
        >
          [×]
        </button>
      </div>
    </div>
  );
}


/**
 * components/AlertBanner.tsx — Critical anomaly alerts
 */

interface AlertBannerProps {
  alerts: AircraftFeature[];
  onSelect: (f: AircraftFeature) => void;
}

export function AlertBanner({ alerts, onSelect }: AlertBannerProps) {
  if (alerts.length === 0) return null;

  return (
    <div className="absolute top-14 left-0 right-0 z-20 bg-[#1a0500]/95 border-b border-[#ff3300]/40 backdrop-blur-sm px-4 py-2">
      <div className="flex items-center gap-4 overflow-x-auto scrollbar-hide">
        <span className="text-[#ff3300] font-mono text-[9px] tracking-widest uppercase flex-shrink-0 animate-pulse">
          ⚠ ALERT
        </span>
        {alerts.map((f) => (
          <button
            key={f.properties.icao24}
            onClick={() => onSelect(f)}
            className="flex items-center gap-2 flex-shrink-0 hover:opacity-80 transition-opacity"
          >
            <span className="text-[#ff6600] font-mono text-[10px]">
              {f.properties.callsign || f.properties.icao24.toUpperCase()}
            </span>
            <span className="text-[#883300] font-mono text-[9px]">
              {f.properties.squawk
                ? `SQUAWK ${f.properties.squawk}`
                : f.properties.pattern_label?.toUpperCase() || "BEHAVIORAL"}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
