# AeroIntel: Real-Time Airspace Anomaly Detection with ML and LLM Interpretability

**Author:** Chris Schmidt  
**Date:** April 2026  
**System:** Live at [aerointel-git-main-chris-schmidts-projects.vercel.app](https://aerointel-git-main-chris-schmidts-projects.vercel.app)  
**Repository:** [github.com/PCSchmidt/aerointel](https://github.com/PCSchmidt/aerointel)

---

## Summary

AeroIntel is a real-time airspace intelligence dashboard that ingests live ADS-B transponder data from roughly 11,000 aircraft, applies a multi-stage machine learning pipeline to detect behavioral anomalies and flight patterns, and uses a large language model to explain each detection in plain English. The system runs continuously on Fly.io and streams results to a browser-based map interface via WebSocket.

This document describes why each design decision was made, what the system actually does in production, and where the honest limits of the approach lie.

---

## The Problem

Aircraft broadcast their position, altitude, speed, and heading every few seconds via ADS-B (Automatic Dependent Surveillance-Broadcast), a transponder standard that replaced most radar-based tracking in civilian airspace. This data is publicly accessible through aggregators like OpenSky Network and adsb.lol. Roughly 11,000 aircraft are broadcasting at any given moment over North America and the North Atlantic.

Most of that traffic is routine. A commercial airliner climbs to cruise altitude, follows its filed route, and descends into its destination. What makes airspace surveillance interesting, and difficult, is the rare aircraft that does something outside that envelope: an unusual climb rate, a holding pattern where none is expected, a transponder code change mid-flight, or a military aircraft flying a structured surveillance orbit.

The naive approach is to set static thresholds: flag any aircraft climbing faster than 3,000 feet per minute, or any aircraft below 10,000 feet in restricted airspace. The problem is that real-world data does not sort cleanly at those boundaries. A helicopter in steep climb, an airliner executing an emergency descent, and a bad ADS-B transponder reading all produce similar numbers. A threshold that catches genuine anomalies will also generate many false positives; a threshold tuned to suppress false positives will miss real events.

AeroIntel takes a different approach. Rather than fixed thresholds, it builds a behavioral model of the current fleet and flags aircraft that are statistically unusual compared to their peers, then uses a language model to reason about whether that statistical signal reflects a genuine operational anomaly or a benign explanation.

---

## Data Sources

**OpenSky Network** provides state vectors for commercial and civilian aircraft. A state vector is a snapshot of one aircraft's position, altitude, speed, heading, vertical rate, and squawk code at a given moment. The system fetches these via OAuth-authenticated API calls, which provide higher rate limits than anonymous access. At the time of writing, a typical fetch returns data for 10,000 to 11,000 aircraft.

**adsb.lol** provides a separate feed focused on military aircraft that broadcast ADS-B publicly. Military aircraft with Mode S transponders appear in this feed even when they are not present in OpenSky's civilian feed. The system merges both feeds each pipeline cycle.

Both sources have rate limits. OpenSky's limit is enforced per IP and per account. The system detects 429 and 503 responses and falls back to serving the previous cycle's data with a warning banner in the UI, rather than crashing or serving stale data silently.

---

## Pipeline Architecture

Each pipeline cycle runs every 60 seconds. The cycle has six stages that execute in sequence:

```
[OpenSky + adsb.lol] --> [Kalman Filter] --> [DBSCAN Clustering] --> [IsolationForest] --> [App State] --> [WebSocket Broadcast]
```

Stages 3 and 4 do not run every cycle. DBSCAN runs every 2 cycles (every 2 minutes) to reduce CPU cost. IsolationForest scoring runs every 3 cycles (every 3 minutes). Between scoring cycles, the system carries over the last computed scores and pattern labels so the UI always shows current values rather than going blank.

That carry-over behavior was the source of a significant bug described later in this document.

---

## Stage 1: Data Ingestion

The `opensky.py` service fetches both feeds concurrently using `asyncio` and `httpx`. It normalizes units: OpenSky reports altitude in meters and speed in meters per second, and the pipeline converts to feet and knots throughout. Each raw state vector is validated against a Pydantic schema before entering the pipeline, which catches malformed records (null positions, invalid squawk codes) without crashing the cycle.

Aircraft are categorized heuristically from ADS-B data alone. Mode S ICAO addresses in the military range (starting with `AE`, `AF`, `43`, and similar prefixes) are flagged as military. Everything else is classified as commercial, private, or unknown based on callsign format and altitude profile.

---

## Stage 2: Kalman Filtering

ADS-B updates arrive every 5 to 10 seconds with position accuracy around 10 meters. Between updates, raw interpolation between two point positions produces jerky motion on the map: an aircraft appears to jump rather than move smoothly. More importantly, raw positions are noisy enough that naive velocity estimates (distance divided by time between updates) produce large errors.

The `kalman.py` service maintains a constant-velocity Kalman filter for each aircraft. A Kalman filter is a mathematical technique for estimating the true state of a system from noisy measurements. The key insight is that it combines two sources of information: a prediction based on what we expect to happen (an aircraft moving at its current velocity) and a measurement of what we observe (the next ADS-B position fix). It weights these proportionally to their respective uncertainties.

The state vector for each aircraft is:

$$x = [\text{lat}, \text{lon}, \dot{\text{lat}}, \dot{\text{lon}}]$$

where $\dot{\text{lat}}$ and $\dot{\text{lon}}$ are the estimated velocity components in degrees per second. The measurement is just the observed latitude and longitude. The filter produces smoothed position estimates between updates and propagates its uncertainty estimate forward in time.

This is the same family of algorithms used in aircraft navigation systems for GPS/INS sensor fusion, adapted here for public ADS-B telemetry rather than onboard sensors. In production, roughly 99 percent of tracked aircraft have Kalman state established after two pipeline cycles.

---

## Stage 3: DBSCAN Pattern Detection

Some aircraft fly patterns: a holding fix is a standard oval or circular path flown at low speed while waiting for landing clearance. Military ISR (intelligence, surveillance, and reconnaissance) aircraft often fly racetrack orbits, which are elongated ovals at a consistent altitude over a fixed geographic area. Helicopters frequently fly tight circles.

These patterns are visible in the aircraft's position history as geographic clusters: the aircraft repeatedly visits the same coordinates. DBSCAN (Density-Based Spatial Clustering of Applications with Noise) is a clustering algorithm that finds groups of nearby points without requiring you to specify how many groups to look for. That property matters here because the number of holding patterns in the airspace at any given moment is unknown.

The `clustering.py` service maintains a rolling position history of up to 60 points per aircraft (approximately 10 minutes at 10-second update rates). DBSCAN runs on each aircraft's history using a neighborhood radius of 0.05 degrees (roughly 5.5 km at mid-latitudes). An aircraft needs at least 4 position fixes in the neighborhood of any single point before a cluster is detected.

When a cluster is found, the service classifies the pattern type based on the cluster's shape:

- **Holding:** roughly circular cluster, radius under 8 km.
- **Racetrack:** elongated cluster with an aspect ratio above 2:1 (length more than twice the width).
- **Orbit:** tight circular cluster, typically with higher turn rates, common in helicopter operations.

In a warm pipeline cycle, roughly 1,800 aircraft out of 11,000 are classified as patterned. Most of these are airliners in standard holding stacks near major airports; a smaller number are military or surveillance aircraft.

---

## Stage 4: IsolationForest Anomaly Detection

This is the core of AeroIntel's behavioral detection capability.

### Why IsolationForest

Supervised machine learning requires labeled examples: pairs of inputs and correct outputs. A supervised anomaly detector for aircraft would need a training set of labeled anomalous flights. Such a dataset does not exist publicly, and even if it did, "anomalous" means different things in different contexts. A rapid descent at 4,000 feet per minute is normal for a fighter jet and unusual for a regional turboprop.

IsolationForest is an unsupervised algorithm, meaning it works without labeled examples. The idea is that anomalies are rare and different: they are isolated from the bulk of the data. The algorithm builds many random decision trees, each constructed by repeatedly picking a random feature and a random split value until each data point is isolated in its own leaf. Anomalous points require fewer splits to isolate because they sit far from the dense cluster of normal behavior. The algorithm assigns a score based on how quickly each point was isolated: lower scores indicate more anomalous behavior.

The mathematical detail: for a data point $x$, the anomaly score is:

$$s(x, n) = 2^{-\frac{E[h(x)]}{c(n)}}$$

where $E[h(x)]$ is the average path length to isolate $x$ across all trees, and $c(n)$ is the expected path length for a sample of size $n$ under random binary search tree assumptions. Scores near 1 indicate strong anomalies; scores near 0.5 indicate normal behavior; scores below the threshold of $-0.15$ in this implementation trigger a behavioral anomaly flag.

The contamination parameter is set to 0.02, meaning the model expects roughly 2 percent of the fleet to be anomalous at any time. This is a tunable assumption; setting it lower reduces false positives at the cost of missing subtler anomalies.

### The Feature Vector

Each aircraft contributes one 6-dimensional feature vector, computed from a rolling 5-minute window of observations. A minimum of 6 observations (roughly one per minute) is required before an aircraft is scored.

| Feature | What It Measures |
|---|---|
| `altitude_delta_ft` | Total altitude change over the 5-minute window, in feet |
| `speed_delta_kts` | Total speed change over the window, in knots |
| `heading_variance` | Circular variance of heading readings (0 = constant heading, 1 = random) |
| `vertical_rate_fpm` | Current climb or descent rate, in feet per minute |
| `update_gap_s` | Seconds since the last ADS-B contact |
| `squawk_changed` | Binary: whether the transponder code changed in the window |

**Why circular variance for heading:** heading is an angle, and angles wrap around at 360 degrees. Standard variance would treat a heading oscillating between 359 and 1 degrees as having enormous variance, when it is actually very stable. Circular variance uses unit vectors on the unit circle to handle this correctly.

**Why `update_gap_s`:** a long gap in ADS-B updates can indicate the aircraft is out of receiver range, but it can also indicate the aircraft turned off its transponder. Combined with other unusual features, a long gap is informative.

**Why `squawk_changed`:** squawk code changes mid-flight can reflect ATC reassignment, which is routine, but combined with rapid altitude or speed changes, a squawk change is a relevant signal. The codes 7700 (general emergency), 7600 (radio failure), and 7500 (hijacking) are checked separately and generate an immediate alert regardless of IsolationForest score.

IsolationForest requires a minimum population of 30 scored aircraft before fitting. At the start of each scoring cycle, the model is fit fresh on the current fleet's feature vectors, producing scores calibrated to that moment's population. Scores are then stored in the application state and reused across the next two non-scoring cycles.

---

## Stage 5: LLM Interpretability

A numeric anomaly score answers "is this aircraft unusual?" but not "why is it unusual, and does it matter?" That gap between detection and understanding is a known problem in applied ML. A system that flags events without explaining them creates alert fatigue: operators learn to ignore the flags because they cannot quickly tell which ones are real.

AeroIntel closes this gap by passing each flagged aircraft's feature vector to Claude (Anthropic's claude-sonnet-4-6) for plain-English assessment. The prompt includes the 6 feature values, the aircraft's callsign and ICAO address, the anomaly score, and the DBSCAN pattern label if one was assigned. Claude is instructed to reason like an aviation analyst: identify which features are driving the detection, consider benign explanations, and note when the evidence is ambiguous.

The system also supports two other LLM modes: a natural language query parser (the user types "show me military aircraft above FL300" and Claude converts it to a structured API filter) and a region situation summary (Claude synthesizes all aircraft in the current map view into a plain-English intelligence brief).

All LLM calls are made asynchronously using `asyncio.to_thread()` because the Anthropic Python client is synchronous. This prevents a slow LLM response from blocking the pipeline cycle.

---

## Real Detections from April 22, 2026

The following are actual outputs from the live system. The feature values and explanations are reproduced exactly from the saved evidence files.

### Detection 1: GRZLY71 (ICAO 480446)

GRZLY71 is a US military helicopter, identifiable by its ICAO address prefix (48xxxx corresponds to US military aircraft). The system assigned it a racetrack pattern label and an anomaly score of 0.1624.

Feature vector:

| Feature | Value |
|---|---|
| Altitude delta | +1,775 ft |
| Speed delta | -25.3 kts |
| Heading variance | 0.009 (extremely low) |
| Vertical rate | +448 ft/min |
| Update gap | 2.4 seconds |
| Squawk changed | true |

Claude's assessment (excerpt): "The combination of a racetrack pattern with a squawk code change, significant altitude gain, and simultaneous speed reduction is what likely drove this detection. This profile is consistent with an aircraft entering a holding pattern or an aerial search/surveillance operation, where climbing, decelerating, and changing transponder codes during a structured orbit are operationally expected. The heading variance is extremely low (0.009), which reinforces the racetrack interpretation: the aircraft is flying very deliberate, repeatable tracks rather than maneuvering erratically."

This is a well-calibrated detection. The IsolationForest correctly identified that the combination of squawk change plus altitude shift plus speed reduction is unusual in the broader fleet, even though each individual feature has an innocent explanation. The DBSCAN racetrack label adds context that points toward intentional surveillance behavior rather than random maneuvering.

### Detection 2: adff72 (No Callsign)

This aircraft had no callsign registered in the ADS-B feed and an anomaly score of -0.0697 (below the -0.15 flagging threshold, so it was not actually flagged in the UI, but the feature vector was scored). The system queried it for evidence purposes.

Feature vector:

| Feature | Value |
|---|---|
| Altitude delta | +3,725 ft |
| Speed delta | -230.6 kts |
| Heading variance | 0.659 (moderate) |
| Vertical rate | +17,024 ft/min |
| Update gap | 12.4 seconds |
| Squawk changed | false |

Claude's assessment (excerpt): "The vertical rate of 17,024 ft/min and accompanying altitude change suggest an extremely rapid climb or descent, well beyond typical operational rates for most aircraft. The simultaneous speed reduction of 230.6 knots and moderate heading variance could indicate an emergency descent, an unusual upset recovery, or possibly a data artifact such as transponder interpolation errors or mode-C encoding issues. It is worth noting the anomaly score is relatively close to the threshold, so this could be a false positive."

This is an example of an honest false positive. A vertical rate of 17,000 ft/min is physically impossible for most aircraft. The more likely explanation is a mode-C altitude encoding artifact: ADS-B altitude is encoded in 100-foot increments from a pressure altimeter, and a brief data gap combined with an altitude encoder rollover can produce implausible rate values. The anomaly score of -0.0697 is below threshold, meaning IsolationForest correctly ranked this as less anomalous than the threshold requires, likely because the update gap of 12 seconds and the absence of a squawk change tempered the other extreme values.

### Detection 3: CVEX28 (ICAO 3b776d)

Feature vector:

| Feature | Value |
|---|---|
| Altitude delta | -13,250 ft |
| Speed delta | -119.3 kts |
| Heading variance | 0.075 (low) |
| Vertical rate | -2,944 ft/min |
| Update gap | 2.4 seconds |
| Squawk changed | true |

Claude's assessment (excerpt): "The extreme altitude loss and vertical rate together suggest a very rapid and sustained descent, well outside normal cruise or approach profiles. This is compounded by a significant speed reduction and a squawk code change, which could indicate the crew declared an emergency or was directed to a new code by ATC during an unplanned descent. However, heading variance remains low, suggesting controlled, directed flight rather than erratic maneuvering, and the frequent data update gap indicates good surveillance coverage."

The low heading variance is the key disambiguating signal here. An out-of-control aircraft would show high heading variance; a controlled emergency descent would not. The system correctly captures this nuance.

---

## A Production Bug and How It Was Found

For the first weeks of deployment, the anomaly count in the UI was consistently zero despite the IsolationForest fitting successfully on 200 or more aircraft and producing non-zero scores. The pipeline logs showed normal cycle counts. The bug was not obvious.

The root cause: every pipeline cycle, the application fetched fresh aircraft state from OpenSky and created new Python objects for each aircraft. These new objects had null anomaly scores and no pattern labels, because those values are computed by separate services that run every 2 or 3 cycles, not every cycle. At the end of each non-scoring cycle, the application replaced its live aircraft dictionary with the freshly built objects, discarding all the scores computed in the previous cycle.

The scores were being computed correctly; they were simply thrown away immediately.

The fix added two dictionaries to the application state: one for anomaly scores (keyed by ICAO address) and one for pattern labels. Both are updated on their respective scoring cycles and left unchanged on non-scoring cycles. At the start of each cycle, after fresh aircraft objects are built, the pipeline applies both stored dictionaries to the new objects before they replace the live state. The scores persist across cycles and are pruned when an aircraft leaves the active fleet.

This class of bug, where stateful computation is silently discarded by a fresh object construction, is easy to miss because the system appears to function correctly in every other respect. The pipeline completes, the map updates, and no errors are logged. Only the anomaly count field in the stats endpoint reveals that something is wrong.

---

## Measured Performance

From pipeline stats snapshots captured on April 21-22, 2026:

| Metric | Value |
|---|---|
| Aircraft tracked simultaneously | 11,338 |
| Military aircraft | 244 |
| Pattern-detected aircraft | 1,861 |
| Kalman-filtered aircraft | 11,255 |
| Pipeline cycle duration (typical) | 3 to 7 seconds |
| Pipeline cycle duration (peak load) | 13 seconds |
| IsolationForest fit population | 200 to 210 aircraft per scoring cycle |
| WebSocket connections supported | tested to 5 concurrent |

The pipeline duration varies with fleet size and with OpenSky response latency. The 13-second cycle observed on April 22 coincided with peak North Atlantic traffic (mid-morning US East Coast time). The system keeps up comfortably at 60-second intervals even at peak load.

---

## Honest Assessment

**What this system is.** AeroIntel is a working demonstration of how multiple ML techniques can be composed into a coherent real-time inference pipeline. IsolationForest, DBSCAN, Kalman filtering, and LLM interpretation are each well-established individually; the work here is in integrating them at production scale and making the outputs intelligible to a non-technical user.

**What this system is not.** It is not a surveillance system suitable for operational use. The IsolationForest is fit on the current session's population, which means its baseline changes every 3 minutes. An anomaly that persists across many cycles will drift toward "normal" as it dominates the population. A proper production system would maintain a stable baseline model, update it carefully, and include a formal false positive rate calibration against labeled ground truth.

The contamination parameter (0.02) is an assumption, not a measured property of the actual population. The threshold of -0.15 was set by inspection rather than by optimizing a precision-recall curve against labeled examples. Both of these would need rigorous calibration before the system could be used to make decisions with consequences.

The LLM explanations are only as good as the prompts. Claude reasons plausibly from the feature values, but it does not have access to flight plans, ATC communications, notam data, or aircraft type information. Its explanations are informed speculation from a small set of numeric features.

**The honest value.** The pipeline architecture, the feature engineering choices, the state persistence pattern, and the LLM interpretability approach are all directly applicable to real operational anomaly detection problems. The techniques generalize beyond aviation to any streaming telemetry domain where labeled anomalies are scarce, false positive control matters, and interpretability is required for operator trust.

---

## What I Learned

**Unsupervised anomaly detection requires a theory of normal before it can define abnormal.** The IsolationForest's contamination parameter is that theory, encoded as a numeric assumption. Changing it from 0.02 to 0.05 would roughly double the flagging rate without changing any flight behavior. This is not a flaw in the algorithm; it is an honest representation of the fact that "anomalous" is a relative judgment that requires a prior.

**Stateful services in a pipeline need explicit ownership.** The state persistence bug existed because the freshly built aircraft objects and the anomaly score dictionary were both considered to be the "current state," without clarity about which one owned the scores. Making the application state dictionary the single source of truth for scores, and making the fresh aircraft objects consumers of that dictionary rather than originators of it, resolved the issue cleanly.

**LLM interpretability is most useful at the boundary of confidence.** When the feature values are extreme and unambiguous (a 17,000 ft/min vertical rate), the LLM's contribution is modest. When the values are moderate and multi-causal, as in the GRZLY71 case where racetrack plus squawk change plus altitude shift each have innocent explanations but the combination is unusual, the LLM's ability to reason about the combination is genuinely useful. Routing only ambiguous cases to the LLM, and handling clear-cut ones with deterministic logic, would reduce API cost without reducing coverage.

**OpenSky rate limits force architectural honesty.** The original design assumed continuous data. When the rate limiter fires and the pipeline must serve cached state, every downstream component has to handle stale data gracefully. That constraint produced a better architecture: the pipeline warning propagates to the UI, the cache is served transparently, and the system degrades in a way users can see rather than in a way that silently corrupts their view of the data.
