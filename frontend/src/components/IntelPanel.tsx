"use client";

/**
 * components/IntelPanel.tsx
 * -------------------------
 * Right-side intelligence panel with two capabilities:
 *   1. Natural language query → filter
 *   2. Region situation summary (uses currently visible region)
 */

import { useState, useEffect } from "react";
import { submitNLQuery, fetchRegionSummary, fetchStats, SituationSummary, ViewportBounds, PipelineStats, AircraftFeature } from "@/lib/api";

interface IntelPanelProps {
  aircraftCount: number;
  onFilterApply: (filters: Record<string, unknown>, explanation: string) => void;
  onClose: () => void;
  viewportBounds?: ViewportBounds;
  aircraftFeatures?: AircraftFeature[];
}

export default function IntelPanel({ aircraftCount, onFilterApply, onClose, viewportBounds, aircraftFeatures }: IntelPanelProps) {
  const [nlQuery, setNlQuery] = useState("");
  const [queryLoading, setQueryLoading] = useState(false);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [queryResult, setQueryResult] = useState<string | null>(null);

  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summary, setSummary] = useState<SituationSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const [pipelineStats, setPipelineStats] = useState<PipelineStats | null>(null);
  const [showPatternList, setShowPatternList] = useState(false);

  // Poll pipeline stats every 30s
  useEffect(() => {
    let mounted = true;
    const poll = () =>
      fetchStats()
        .then((s) => { if (mounted) setPipelineStats(s); })
        .catch(() => {});
    poll();
    const id = setInterval(poll, 30_000);
    return () => { mounted = false; clearInterval(id); };
  }, []);

  const handleQuery = async () => {
    if (!nlQuery.trim()) return;
    setQueryLoading(true);
    setQueryError(null);
    setQueryResult(null);
    try {
      const result = await submitNLQuery(nlQuery, aircraftCount);
      onFilterApply(result.filter_params, result.explanation);
      setQueryResult(result.explanation);
    } catch (e) {
      setQueryError("Query failed. Check backend connection.");
    } finally {
      setQueryLoading(false);
    }
  };

  const handleSummary = async () => {
    setSummaryLoading(true);
    setSummaryError(null);
    setSummary(null);
    try {
      // Use real viewport bounds from map; fall back to North Atlantic for demo
      const bounds = viewportBounds ?? { minLat: 20, maxLat: 65, minLon: -80, maxLon: 40 };
      const label = viewportBounds ? "Current view" : "North Atlantic / Europe";
      const result = await fetchRegionSummary(
        bounds.minLat, bounds.maxLat,
        bounds.minLon, bounds.maxLon,
        label
      );
      setSummary(result);
    } catch (e) {
      setSummaryError("Summary failed. Check backend connection.");
    } finally {
      setSummaryLoading(false);
    }
  };

  return (
    <div className="w-80 h-[calc(100vh-4rem)] bg-[#0d1117]/95 border-l border-[#1e2a38] backdrop-blur-sm flex flex-col overflow-hidden">

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#1e2a38]">
        <div>
          <div className="text-[#34d399] font-sans text-xs tracking-widest uppercase">
            Intel Panel
          </div>
          <div className="text-[#4a7a9b] font-sans text-[10px] mt-0.5">
            AI-POWERED ANALYSIS
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-[#4a7a9b] hover:text-[#8ab4d4] font-sans text-xs"
        >
          ×
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-5">

        {/* ── Fleet Analytics ── */}
        <section>
          <div className="text-[#4a7a9b] font-sans text-[10px] tracking-widest uppercase mb-3">
            Fleet Analytics
          </div>
          {pipelineStats ? (
            <>
              <div className="grid grid-cols-2 gap-x-3 gap-y-2 mb-3">
                {[
                  { label: "AIRCRAFT",  value: pipelineStats.aircraft_count, color: "#4a9eff",  clickable: false },
                  { label: "MILITARY",  value: pipelineStats.military_count,  color: "#ff4a4a", clickable: false },
                  { label: "ANOMALIES", value: pipelineStats.anomaly_count,   color: pipelineStats.anomaly_count > 0 ? "#ff6600" : "#3a5a6a", clickable: false },
                  { label: "PATTERNS",  value: pipelineStats.pattern_count,   color: pipelineStats.pattern_count > 0 ? "#ffb800" : "#3a5a6a", clickable: true },
                ].map(({ label, value, color, clickable }) => (
                  clickable ? (
                    <button
                      key={label}
                      onClick={() => setShowPatternList((v) => !v)}
                      className="bg-[#070a0e] border border-[#1e2a38] px-2 py-1.5 text-left w-full hover:border-[#ffb800]/40 transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <div className="text-[#3a5a6a] font-mono text-[8px] uppercase tracking-wider">{label}</div>
                        <div className="text-[#3a5a6a] font-mono text-[8px]">{showPatternList ? "▾" : "▸"}</div>
                      </div>
                      <div className="font-mono text-sm mt-0.5" style={{ color }}>{value}</div>
                    </button>
                  ) : (
                    <div key={label} className="bg-[#070a0e] border border-[#1e2a38] px-2 py-1.5">
                      <div className="text-[#3a5a6a] font-mono text-[8px] uppercase tracking-wider">{label}</div>
                      <div className="font-mono text-sm mt-0.5" style={{ color }}>{value}</div>
                    </div>
                  )
                ))}
              </div>

              {/* ── Pattern aircraft list ── */}
              {showPatternList && (() => {
                const patterned = (aircraftFeatures ?? []).filter((f) => f.properties.pattern_label);
                const BADGE: Record<string, string> = {
                  holding:   "#4a9eff",
                  racetrack: "#ffb800",
                  orbit:     "#34d399",
                };
                return (
                  <div className="mb-2">
                    <div className="text-[#3a5a6a] font-mono text-[8px] uppercase tracking-wider mb-1.5">
                      Pattern aircraft ({patterned.length})
                    </div>
                    {patterned.length === 0 ? (
                      <div className="text-[#2a4a5a] font-mono text-[9px]">No pattern aircraft in current view</div>
                    ) : (
                      <div className="max-h-48 overflow-y-auto flex flex-col gap-0.5 pr-1">
                        {patterned.map((f) => {
                          const p = f.properties;
                          const badgeColor = BADGE[p.pattern_label ?? ""] ?? "#8ab4d4";
                          return (
                            <div
                              key={p.icao24}
                              className="flex items-center justify-between bg-[#070a0e] border border-[#1e2a38] px-2 py-1"
                            >
                              <div>
                                <div className="font-mono text-[10px] text-[#8ab4d4]">
                                  {p.callsign || p.icao24}
                                </div>
                                <div className="font-mono text-[8px] text-[#3a5a6a]">{p.icao24}</div>
                              </div>
                              <div
                                className="font-mono text-[8px] uppercase px-1.5 py-0.5 border"
                                style={{ color: badgeColor, borderColor: `${badgeColor}40` }}
                              >
                                {p.pattern_label}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })()}
              <div className="flex flex-col gap-1.5">
                <div className="flex justify-between text-[9px] font-mono">
                  <span className="text-[#3a5a6a]">Kalman tracked</span>
                  <span className="text-[#4a9eff]">{pipelineStats.kalman_tracked}</span>
                </div>
                <div className="flex justify-between text-[9px] font-mono">
                  <span className="text-[#3a5a6a]">Pipeline</span>
                  <span className="text-[#34d399]">{pipelineStats.pipeline_duration_s.toFixed(1)}s</span>
                </div>
              </div>
              {pipelineStats.pipeline_warning && (
                <div className="mt-2 p-2 bg-[#1a1000] border border-[#f59e0b]/30 text-[#f59e0b] font-mono text-[9px]">
                  ⚠ {pipelineStats.pipeline_warning}
                </div>
              )}
            </>
          ) : (
            <div className="text-[#3a5a6a] font-mono text-[9px] animate-pulse">Connecting...</div>
          )}
        </section>

        <div className="border-t border-[#1e2a38]" />

        {/* ── NL Query ── */}
        <section>
          <div className="text-[#4a7a9b] font-sans text-[10px] tracking-widest uppercase mb-2">
            Natural Language Filter
          </div>
          <div className="text-[#3a5a6a] font-sans text-[9px] mb-3 leading-relaxed">
            Claude parses your query into structured filters applied to the live aircraft feed.
          </div>

          <div className="flex flex-col gap-2">
            <textarea
              value={nlQuery}
              onChange={(e) => setNlQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && e.metaKey) handleQuery(); }}
              placeholder="e.g. military aircraft above 30,000 feet&#10;e.g. holding pattern aircraft&#10;e.g. emergency squawk"
              className="w-full bg-[#070a0e] border border-[#1e2a38] text-[#8ab4d4] font-mono text-[11px] p-2.5 placeholder-[#2a4a5a] resize-none focus:outline-none focus:border-[#34d399]/40 transition-colors"
              rows={3}
            />
            <button
              onClick={handleQuery}
              disabled={queryLoading || !nlQuery.trim()}
              className="w-full py-2 bg-[#0a2a1a] border border-[#34d399]/30 text-[#34d399] font-sans text-xs tracking-widest uppercase hover:bg-[#0a3a25] hover:border-[#34d399]/60 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
            >
              {queryLoading ? "PARSING..." : "APPLY FILTER  ⌘↵"}
            </button>
          </div>

          {queryResult && (
            <div className="mt-2 p-2.5 bg-[#0a1a10] border border-[#34d399]/20">
              <div className="text-[#34d399] font-mono text-[10px] leading-relaxed">
                ✓ {queryResult}
              </div>
            </div>
          )}
          {queryError && (
            <div className="mt-2 p-2.5 bg-[#1a0a0a] border border-[#ff4a4a]/20">
              <div className="text-[#ff6666] font-mono text-[10px]">{queryError}</div>
            </div>
          )}

          {/* Example queries */}
          <div className="mt-3">
            <div className="text-[#3a5a6a] font-sans text-[9px] mb-1.5 uppercase tracking-wider">
              Examples
            </div>
            {[
              "Military aircraft above FL300",
              "Holding pattern aircraft",
              "Aircraft with emergency squawk",
              "Private jets over the Atlantic",
            ].map((example) => (
              <button
                key={example}
                onClick={() => setNlQuery(example)}
                className="block w-full text-left text-[#3a6a8a] font-mono text-[9px] py-0.5 hover:text-[#4a9eff] transition-colors"
              >
                › {example}
              </button>
            ))}
          </div>
        </section>

        <div className="border-t border-[#1e2a38]" />

        {/* ── Situation Summary ── */}
        <section>
          <div className="text-[#4a7a9b] font-sans text-[10px] tracking-widest uppercase mb-2">
            Situation Summary
          </div>
          <div className="text-[#3a5a6a] font-sans text-[9px] mb-3 leading-relaxed">
            Claude synthesizes current aircraft data into a plain-English intelligence brief.
          </div>

          <button
            onClick={handleSummary}
            disabled={summaryLoading}
            className="w-full py-2 bg-[#0a1a2a] border border-[#4a9eff]/30 text-[#4a9eff] font-sans text-xs tracking-widest uppercase hover:bg-[#0a2a3a] hover:border-[#4a9eff]/60 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
          >
            {summaryLoading ? "ANALYZING..." : "GENERATE BRIEF"}
          </button>

          {summary && (
            <div className="mt-3 p-3 bg-[#070a10] border border-[#1e3a5a]">
              <div className="text-[#4a9eff] font-sans text-[9px] tracking-widest uppercase mb-2">
                {summary.region_label} — {summary.aircraft_count} aircraft
              </div>
              <div className="text-[#8ab4d4] font-mono text-[11px] leading-relaxed">
                {summary.summary}
              </div>
              {summary.notable_items.length > 0 && (
                <div className="mt-2 pt-2 border-t border-[#1e3a5a]">
                  <div className="text-[#3a5a6a] font-sans text-[9px] uppercase tracking-wider mb-1">
                    Notable
                  </div>
                  {summary.notable_items.map((item, i) => (
                    <div key={i} className="text-[#ffb800] font-mono text-[10px]">
                      › {item}
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-2 text-[#2a4a5a] font-mono text-[9px]">
                Generated {new Date(summary.generated_at * 1000).toLocaleTimeString()}
                {" · "}claude-sonnet-4-6
              </div>
            </div>
          )}

          {summaryError && (
            <div className="mt-2 p-2.5 bg-[#1a0a0a] border border-[#ff4a4a]/20">
              <div className="text-[#ff6666] font-mono text-[10px]">{summaryError}</div>
            </div>
          )}
        </section>

        {/* ── Model info ── */}
        <div className="border-t border-[#1e2a38] pt-3">
          <div className="text-[#2a4a5a] font-sans text-[9px] leading-relaxed">
            NL filtering uses Claude to parse queries into structured predicates.
            Situation summaries pass live ADS-B telemetry + ML flags to Claude
            for synthesized intelligence assessment.
          </div>
        </div>

      </div>
    </div>
  );
}
