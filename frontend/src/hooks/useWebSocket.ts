/**
 * hooks/useWebSocket.ts
 * ----------------------
 * WebSocket hook — receives GeoJSON pushes from the pipeline.
 * Falls back to REST polling if WebSocket unavailable.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { AircraftGeoJSON, WS_URL, fetchAircraft } from "@/lib/api";

const POLL_INTERVAL_MS = 65_000;  // fallback polling interval
const RECONNECT_DELAY_MS = 5_000;

interface UseWebSocketReturn {
  data: AircraftGeoJSON | null;
  connected: boolean;
  lastUpdate: Date | null;
  error: string | null;
  pipelineWarning: string | null;
}

export function useAircraftWebSocket(): UseWebSocketReturn {
  const [data, setData] = useState<AircraftGeoJSON | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pipelineWarning, setPipelineWarning] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<NodeJS.Timeout>();
  const pollTimer = useRef<NodeJS.Timeout>();
  const useFallback = useRef(false);

  // REST fallback polling
  const startPolling = useCallback(() => {
    useFallback.current = true;
    const poll = async () => {
      try {
        const result = await fetchAircraft();
        setData(result);
        setLastUpdate(new Date());
        setError(null);
      } catch (e) {
        setError("Data fetch failed");
      }
    };
    poll();
    pollTimer.current = setInterval(poll, POLL_INTERVAL_MS);
  }, []);

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(`${WS_URL}/ws/aircraft`);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setError(null);
        if (pollTimer.current) clearInterval(pollTimer.current);
        useFallback.current = false;
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          // Ignore keepalive pings
          if (msg.type === "ping") return;
          const geojson = msg as AircraftGeoJSON;
          setData(geojson);
          setLastUpdate(new Date());
          setPipelineWarning(geojson.metadata?.pipeline_warning ?? null);
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        // Reconnect after delay
        reconnectTimer.current = setTimeout(() => {
          if (!useFallback.current) connect();
        }, RECONNECT_DELAY_MS);
      };

      ws.onerror = () => {
        setError("WebSocket error — falling back to polling");
        ws.close();
        startPolling();
      };
    } catch {
      startPolling();
    }
  }, [startPolling]);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
  }, [connect]);

  return { data, connected, lastUpdate, error, pipelineWarning };
}
