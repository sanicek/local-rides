# Local Rides

A lightweight personal system for discovering, curating, planning, and tracking minor motorcycle exploration targets. GitHub is the source of truth. Mapping and navigation applications consume generated GeoJSON or GPX.

```text
capture/research -> canonical YAML -> validate/generate -> GeoJSON + GPX
                                                |             |
                                               uMap     Kurviger/Mapy/OsmAnd
```

The repository deliberately has no custom UI, database, server, or two-way synchronization.

Detailed map setup and iPhone navigation instructions are in
[`USER_GUIDE.md`](USER_GUIDE.md).

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python tools/local_rides.py validate
python tools/local_rides.py generate
```

Export the current manual selection:

```bash
python tools/local_rides.py gpx \
  --selection selections/today.yaml \
  --output rides/afternoon.gpx
```

Run tests and the proximity dedupe report:

```bash
python -m unittest discover -s tests
python tools/local_rides.py dedupe
```

## Canonical records

Store one YAML object per file: points in `data/places/`, road or track segments in `data/roads/`. The schemas in `schemas/` document the format. The built-in validator is authoritative for CI and intentionally avoids a separate JSON Schema runtime dependency.

Minimal place:

```yaml
schema_version: 1
id: old-waterworks-001
kind: place
name: Old Waterworks
coordinates:
  lat: 48.123
  lon: 17.123
categories: [industrial, historical]
status: candidate
scores:
  destination: 3
  road: 4
access:
  motorcycle: likely
  legal_confidence: unknown
  surface: paved
sources:
  - id: osm-primary
    type: osm
    ref: node/1234567
    url: https://www.openstreetmap.org/node/1234567
    checked: 2026-09-11
claims:
  - text: The mapped object is tagged as waterworks.
    certainty: confirmed
    source_refs: [osm-primary]
notes: Minor industrial relic; potentially useful in a reservoir loop.
visits: []
```

Access values describe evidence, not permission. `motorcycle: likely` with `legal_confidence: unknown` is explicitly uncertain. Absence of an OSM restriction never proves legal access.

Quote YAML values `"yes"` and `"no"`; PyYAML otherwise interprets them as booleans.

When the target itself is not a suitable routing point, add an `approach` with a roadside or parking coordinate. GeoJSON retains the true target position; GPX uses the approach position.

```yaml
approach:
  mode: park_and_walk
  coordinates:
    lat: 48.1234
    lon: 17.1234
  notes: Use mapped parking and inspect signs locally.
```

## Statuses and scores

| Status | Meaning |
| --- | --- |
| `candidate` | Retained but not prioritized |
| `shortlist` | Worth planning soon |
| `visited` | Has at least one dated visit record |
| `rejected` | Retained for dedupe/history with a rejection reason |
| `needs_research` | Identity, interest, or access needs verification |

Destination and road scores are independent. A weak destination can justify an excellent road.

## Generated views

`python tools/local_rides.py generate` recreates:

| File | Contents |
| --- | --- |
| `places.geojson` | All non-rejected places |
| `unvisited.geojson` | Candidate, shortlist, and research-needed places |
| `shortlist.geojson` | Shortlisted places |
| `roads.geojson` | All non-rejected road segments |
| `today.geojson` | Ordered objects from `selections/today.yaml` |

Generated files are committed so public raw GitHub URLs work from an iPhone and in uMap without running code.

## uMap

Create remote GeoJSON layers using:

```text
https://raw.githubusercontent.com/sanicek/local-rides/main/generated/unvisited.geojson
https://raw.githubusercontent.com/sanicek/local-rides/main/generated/shortlist.geojson
https://raw.githubusercontent.com/sanicek/local-rides/main/generated/roads.geojson
https://raw.githubusercontent.com/sanicek/local-rides/main/generated/today.geojson
```

Try direct loading first. Enable the uMap proxy only if the selected uMap instance reports a cross-origin error. These URLs expose generated content publicly.

## Discovery with Overpass

The files in `queries/` are bounded templates. Replace `{{bbox}}` with `south,west,north,east` before running them in Overpass Turbo or through an agent. Keep the area small enough to avoid timeouts.

Overpass results are candidate inputs, not canonical facts. Curate each result, attach stable source identity, assess uncertainty, and deduplicate before writing YAML.

## iPhone capture inbox

Use the `Capture a local discovery` GitHub Issue form. Paste any map link or coordinates, add one sentence, and attach a photo if useful. Structured GIS entry is not required.

Initial labels:

- `discovery`: unprocessed place capture;
- `road`: paved road-section capture;
- `gravel`: unpaved candidate;
- `visited`: field observation requiring an update;
- `research`: source or access investigation;
- `processed`: canonical change created or merged.

An agent processes an issue by resolving coordinates and external IDs, checking duplicates, preserving provenance, writing YAML on a branch, regenerating views, and linking the pull request. Close the issue after merge.

## Planning a ride

Write an ordered list of canonical IDs into `selections/today.yaml`:

```yaml
name: Reservoir and ridge afternoon
date: 2026-09-11
start:
  name: Bratislava centre
  coordinates: {lat: 48.1486, lon: 17.1077}
return_to_start: true
items:
  - old-waterworks-001
  - ridge-gravel-001
```

Generation updates the uMap `today` layer. GPX export emits ordered waypoints and route points. For a selected road it emits its start and end. Kurviger decides how to connect the points; the exporter does not fabricate a navigable straight-line track.

Import the GPX through the iOS share sheet or Files into Kurviger, Mapy.com, or OsmAnd. OsmAnd remains the detailed offline tool for tracks, gravel inspection, and actual ride recording.

## Deduplication

Validation rejects duplicate internal IDs and repeated stable external identities such as an OSM object or Wikidata QID. `dedupe` additionally reports nearby places:

- within 25 m when categories overlap;
- within 75 m when normalized names share words.

It never merges automatically.

## Development boundary

Apple Shortcuts, scheduled scans, direct Kurviger API use, and automatic issue processing remain deferred until the manual workflow exposes a repeated cost.
