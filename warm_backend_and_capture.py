import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib import request, error

BASE = "https://aerointel-backend.fly.dev"
STATS_URL = BASE + "/api/stats"
AIRCRAFT_URL = BASE + "/api/aircraft"
MAX_ATTEMPTS = 8
SLEEP_SECONDS = 5


def now_ts():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def fetch_json(url):
    req = request.Request(
        url,
        headers={
            "User-Agent": "aerointel-warm-check/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            text = resp.read().decode(charset, errors="replace")
            return json.loads(text)
    except error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def safe_get(obj, *keys, default=None):
    cur = obj
    for key in keys:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def find_first_int(obj, candidates):
    if isinstance(obj, dict):
        for key in candidates:
            value = obj.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return int(value)
        for value in obj.values():
            found = find_first_int(value, candidates)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_first_int(item, candidates)
            if found is not None:
                return found
    return None


def summarize_stats(stats):
    aircraft_count = find_first_int(stats, ["aircraft_count", "aircraftCount", "count"])
    military_count = find_first_int(stats, ["military_count", "militaryCount"])
    anomaly_count = find_first_int(stats, ["anomaly_count", "anomalyCount"])
    pipeline_cycle = safe_get(stats, "pipeline", "cycle", default=safe_get(stats, "pipeline_cycle", default=None))
    pipeline_warning = safe_get(stats, "pipeline", "warning", default=safe_get(stats, "pipeline_warning", default=None))
    pipeline_errors = safe_get(stats, "pipeline", "errors", default=safe_get(stats, "pipeline_errors", default=None))
    return {
        "aircraft_count": aircraft_count,
        "military_count": military_count,
        "anomaly_count": anomaly_count,
        "pipeline_cycle": pipeline_cycle,
        "pipeline_warning": pipeline_warning,
        "pipeline_errors": pipeline_errors,
    }


def as_list(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if payload.get("type") == "FeatureCollection" and isinstance(payload.get("features"), list):
            return payload["features"]
        for key in ("aircraft", "items", "data", "results", "features"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def truthy_anomaly(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "anomaly", "anomalous"}
    return False


def candidate_icao24(item):
    if not isinstance(item, dict):
        return None
    if item.get("type") == "Feature":
        props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        for key in ("icao24", "icao", "hex", "id"):
            value = props.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
    for key in ("icao24", "icao", "hex", "id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def item_is_anomalous(item):
    if not isinstance(item, dict):
        return False
    checks = []
    numeric_scores = []
    if item.get("type") == "Feature":
        props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        checks.extend([
            props.get("is_anomaly"),
            props.get("anomaly"),
            props.get("anomalous"),
            props.get("has_anomaly"),
            props.get("anomaly_severity"),
            props.get("classification"),
            props.get("status"),
        ])
        numeric_scores.extend([
            props.get("anomaly_score"),
            props.get("anomalyScore"),
        ])
    checks.extend([
        item.get("is_anomaly"),
        item.get("anomaly"),
        item.get("anomalous"),
        item.get("has_anomaly"),
        item.get("anomaly_severity"),
        item.get("classification"),
        item.get("status"),
    ])
    numeric_scores.extend([
        item.get("anomaly_score"),
        item.get("anomalyScore"),
    ])
    for value in checks:
        if truthy_anomaly(value):
            return True
        if isinstance(value, str) and value.strip().lower() in {"anomaly", "anomalous", "alert"}:
            return True
    for value in numeric_scores:
        if isinstance(value, (int, float)) and value < 0:
            return True
    return False


def save_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def main():
    attempt_summaries = []
    stats_payload = None
    warmed = False

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            stats_payload = fetch_json(STATS_URL)
            summary = summarize_stats(stats_payload)
            attempt_summaries.append(summary)
            print(
                f"Attempt {attempt}/{MAX_ATTEMPTS}: "
                f"aircraft_count={summary['aircraft_count']} "
                f"military_count={summary['military_count']} "
                f"anomaly_count={summary['anomaly_count']} "
                f"pipeline_cycle={summary['pipeline_cycle']} "
                f"pipeline_warning={summary['pipeline_warning']} "
                f"pipeline_errors={summary['pipeline_errors']}"
            )
            if isinstance(summary["aircraft_count"], int) and summary["aircraft_count"] > 1000:
                warmed = True
                break
        except Exception as exc:
            print(f"Attempt {attempt}/{MAX_ATTEMPTS}: request_failed={exc}")
        if attempt < MAX_ATTEMPTS:
            time.sleep(SLEEP_SECONDS)

    if not warmed:
        print("Backend did not warm successfully within 8 attempts; no evidence files were created.")
        return 0

    saved_paths = []
    timestamp = now_ts()

    fresh_stats = fetch_json(STATS_URL)
    stats_path = os.path.join("evidence", "pipeline-stats", f"stats-live-warm-{timestamp}.json")
    save_json(stats_path, fresh_stats)
    saved_paths.append(stats_path)

    aircraft_payload = fetch_json(AIRCRAFT_URL)
    aircraft_items = as_list(aircraft_payload)
    seen = set()
    anomalous = []
    for item in aircraft_items:
        icao24 = candidate_icao24(item)
        if not icao24 or icao24 in seen:
            continue
        if item_is_anomalous(item):
            seen.add(icao24)
            anomalous.append(icao24)
        if len(anomalous) >= 3:
            break

    print(f"Anomalous aircraft selected: {anomalous if anomalous else 'none found'}")

    for icao24 in anomalous:
        detail_payload = fetch_json(BASE + f"/api/aircraft/{icao24}")
        if not isinstance(detail_payload, dict) or not detail_payload.get("anomalies"):
            print(f"Skipping {icao24}: detail endpoint has no anomalies")
            continue
        explain_payload = fetch_json(BASE + f"/api/aircraft/{icao24}/explain")
        if explain_payload is None:
            print(f"Skipping {icao24}: explain endpoint returned 404")
            continue
        explain_path = os.path.join("evidence", "anomaly-explanations", f"explain-{icao24}-{timestamp}.json")
        save_json(explain_path, explain_payload)
        saved_paths.append(explain_path)

    print("Saved files:")
    for path in saved_paths:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
