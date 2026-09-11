# Local Rides: Initial Design and Implementation Plan

## 1. Outcome

Build a repository-centered personal exploration system. Canonical YAML records describe places and road segments. Small Python tools validate those records and generate GeoJSON and GPX. GitHub Issues are the capture inbox. uMap, Mapy.com, Kurviger, and OsmAnd remain replaceable consumers.

Version 1 has no database, web application, API service, account system, or automatic scheduler.

## 2. GitHub integration finding

The connected GitHub integration can:

- search accessible repositories;
- read and write repository files;
- create and update branches;
- create, label, update, and close issues;
- create and inspect pull requests;
- inspect GitHub Actions runs.

No existing repository named `local-rides` was found. Repository creation is not exposed by the current integration. Create the empty repository once through GitHub's UI or `gh repo create`; subsequent maintenance can happen through ChatGPT Work/Codex.

Recommended repository visibility:

- **Public** if publishing approximate locations and notes is acceptable. This gives uMap a zero-infrastructure raw GeoJSON feed.
- **Private canonical plus public projection repository** if private notes, captures, or exact locations matter. Publish only sanitized `generated/*.geojson` and selected GPX files to the second repository with GitHub Actions.
- Do not embed a GitHub token in uMap or a URL. Do not add a proxy service in version 1.

uMap supports a remote data URL, GeoJSON format selection, URL checking, and optional server-side proxy/cache. Its documentation also warns that the origin must permit third-party access unless the uMap proxy is used. This works naturally with public raw GitHub content, not authenticated private content.

## 3. Repository layout

```text
local-rides/
├── data/
│   ├── places/
│   │   └── example-place.yaml
│   └── roads/
│       └── example-road.yaml
├── selections/
│   └── today.yaml
├── queries/
│   ├── historical.overpass
│   ├── infrastructure.overpass
│   ├── viewpoints.overpass
│   └── gravel.overpass
├── generated/
│   ├── places.geojson
│   ├── unvisited.geojson
│   ├── shortlist.geojson
│   ├── roads.geojson
│   └── today.geojson
├── rides/
│   └── .gitkeep
├── schemas/
│   ├── place.schema.json
│   └── road.schema.json
├── tools/
│   └── local_rides.py
├── tests/
│   └── fixtures/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   └── capture.yml
│   └── workflows/
│       └── validate.yml
├── AGENTS.md
├── README.md
└── requirements.txt
```

Generated files are committed. This makes raw URLs stable, lets phone clients fetch them without running tooling, and makes diffs reviewable.

## 4. Canonical record model

Use one YAML document per object. File names are convenience; the internal `id` is authoritative and immutable.

### 4.1 Shared fields

| Field | Required | Meaning |
| --- | --- | --- |
| `schema_version` | yes | Integer, initially `1` |
| `id` | yes | Stable lowercase kebab-case identifier |
| `kind` | yes | `place` or `road` |
| `name` | yes | Human-readable label |
| `categories` | yes | Non-empty list of open vocabulary tags |
| `status` | yes | `candidate`, `shortlist`, `visited`, `rejected`, or `needs_research` |
| `scores.destination` | yes | Integer 1–5; low is valid for road-led targets |
| `scores.road` | yes | Integer 1–5 |
| `access.motorcycle` | yes | `yes`, `no`, `likely`, or `unknown` |
| `access.legal_confidence` | yes | `confirmed`, `inferred`, or `unknown` |
| `access.surface` | yes | Controlled value such as `paved`, `gravel`, `dirt`, `mixed`, or `unknown` |
| `sources` | yes | List of source records; may be empty only for raw inbox-derived candidates |
| `claims` | no | Factual or access claims tied to sources and certainty |
| `notes` | no | Subjective curation notes, not factual authority |
| `visits` | yes | List of visit records; empty until visited |
| `rejection` | conditional | Required when status is `rejected` |

Source record:

```yaml
- id: osm-primary
  type: osm
  ref: node/1234567
  url: https://www.openstreetmap.org/node/1234567
  checked: 2026-09-11
```

Claim record:

```yaml
- text: Public road reaches the site entrance.
  certainty: inferred
  source_refs: [osm-primary]
```

This separates evidence-backed statements from personal notes. `motorcycle: likely` is never equivalent to a legal-access claim.

### 4.2 Place schema

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
  - text: The mapped object is tagged as a waterworks.
    certainty: confirmed
    source_refs: [osm-primary]
notes: Minor industrial relic; useful as part of a reservoir loop.
visits: []
```

Validation requires latitude `-90..90`, longitude `-180..180`, unique IDs, valid source references, and status consistency. `status: visited` requires at least one visit. `status: rejected` requires a reason.

### 4.3 Road/track schema

Use GeoJSON coordinate order inside line geometry: longitude, latitude.

```yaml
schema_version: 1
id: ridge-gravel-001
kind: road
name: Ridge gravel connector
geometry:
  type: LineString
  coordinates:
    - [17.1001, 48.2001]
    - [17.1120, 48.2075]
categories: [gravel, ridge, scenic]
status: candidate
scores:
  destination: 1
  road: 5
access:
  motorcycle: unknown
  legal_confidence: unknown
  surface: gravel
direction: either
sources:
  - id: osm-way
    type: osm
    ref: way/7654321
    url: https://www.openstreetmap.org/way/7654321
    checked: 2026-09-11
claims: []
notes: Verify barriers and traffic restrictions before riding.
visits: []
```

Optional road fields: `direction`, `season`, `difficulty`, `length_km`, and `endpoints`. Derived values such as length should be marked as derived or regenerated, not hand-maintained without reason.

## 5. Deduplication rules

Apply deterministic checks before AI judgment:

1. Exact source identity: same OSM `type/id`, Wikidata QID, heritage-registry ID, or canonical URL is a duplicate.
2. Exact internal ID is an error.
3. Places within 75 m with materially similar normalized names/categories are flagged for review.
4. Unnamed places within 25 m are flagged when categories overlap.
5. Roads sharing an OSM way ID are duplicates; substantially overlapping geometries are flagged for review.
6. Never silently merge. Preserve both source sets and record the merge in Git history or a PR.

The validator handles exact conflicts. A `dedupe` command reports proximity/overlap candidates but makes no changes.

## 6. Tooling

Use Python 3.12 and one runtime dependency, `PyYAML`. Keep validation rules in `schemas/*.schema.json`, but implement the required subset directly in `tools/local_rides.py` rather than adding a JSON Schema engine in version 1.

Commands:

```text
python tools/local_rides.py validate
python tools/local_rides.py dedupe
python tools/local_rides.py generate
python tools/local_rides.py gpx --selection selections/today.yaml --output rides/2026-09-11-afternoon.gpx
```

`generate` performs validation first and writes deterministic, sorted output:

- `places.geojson`: every place except rejected records;
- `unvisited.geojson`: `candidate`, `shortlist`, and `needs_research` places;
- `shortlist.geojson`: shortlist places;
- `roads.geojson`: every non-rejected road;
- `today.geojson`: records named in `selections/today.yaml`, preserving order metadata.

GeoJSON feature properties contain `id`, `name`, `kind`, `categories`, `status`, both scores, access summary, notes, and source links. They do not duplicate the full canonical evidence model.

`today.yaml` is intentionally simple:

```yaml
name: Reservoir and ridge afternoon
date: 2026-09-11
items:
  - old-waterworks-001
  - ridge-gravel-001
```

The first GPX exporter emits ordered waypoints for places and the endpoints of selected roads. Kurviger performs routing. It does not claim that a generated straight line is a navigable route. Later, an optional track-mode export may include road geometries for OsmAnd.

## 7. Reusable Overpass queries

Each query uses a replaceable `{{bbox}}` token and outputs geometry with tags. Keep separate files because broad combined queries time out and are harder to assess.

- `historical.overpass`: `historic=*`, memorials, wayside crosses/shrines, ruins, archaeological sites.
- `infrastructure.overpass`: water wells, pumps, towers, dams, bridges, fords, abandoned or disused railways.
- `viewpoints.overpass`: viewpoints, peaks, cliffs, caves, springs, notable natural features.
- `gravel.overpass`: tracks and minor roads with gravel/unpaved/dirt surfaces, plus access, motor_vehicle, motorcycle, tracktype, smoothness, barrier, and seasonal tags.

Overpass results are discovery inputs, never canonical records. Import requires curation, deduplication, and an access-confidence assessment. Absence of an access restriction tag is not proof of legal motorcycle access.

## 8. Consumer behavior

| Consumer | V1 handoff | Authority |
| --- | --- | --- |
| uMap | Remote public GeoJSON URL per generated view | Visual overview only |
| Mapy.com | Manual GPX import from Files/share sheet | Navigation/exploration only |
| Kurviger | GPX waypoint import | Chooses enjoyable paved routing |
| OsmAnd iOS | GPX import | Offline detail, track following, ride recording |

Configure uMap layers for `unvisited`, `shortlist`, `roads`, and `today`. Use a raw URL pinned to the default branch for live updates. Enable uMap proxy only if direct CORS loading fails; use a short cache during active editing and up to one day for normal use.

Two-way sync with Mapy, Kurviger, or OsmAnd is out of scope. Actual ride recordings return as GPX attachments to a GitHub Issue or as files under `rides/actual/` only when worth retaining.

## 9. iPhone-first workflow

### Capture

1. Open GitHub Mobile or github.com.
2. Create an issue with label `discovery`, `road`, or `gravel`.
3. Paste a shared map URL or coordinates and a short note. Attach a photo when useful.
4. Do not fill out canonical fields on the phone.

Issue title convention: `[capture] short human hint`.

Issue body accepts any subset of:

```text
Location/map link:
What caught my attention:
Access observation:
Photo:
Visited now: yes/no
```

The issue template must allow blank fields. Labels describe inbox context; canonical status remains in YAML.

### Process inbox

On demand, an agent:

1. reads open capture issues;
2. resolves coordinates and stable external IDs;
3. checks exact and spatial duplicates;
4. enriches from structured and supporting sources;
5. separates confirmed, inferred, and uncertain claims;
6. creates or updates canonical YAML on a branch;
7. regenerates projections and validates;
8. opens a compact PR linking the source issue;
9. closes the issue only after merge.

### Plan and ride

Tell the agent the available duration, approximate start, surface tolerance, and desired mix. It proposes a small ordered set, writes `selections/today.yaml`, regenerates `today.geojson`, and exports GPX. Open the GPX on iPhone in Kurviger, Mapy, or OsmAnd.

### Record outcome

Create a short issue or update records through an agent: visited date, access reality, surface, closures, and rejection reason. Keep observations time-stamped because access and surface conditions change.

## 10. Initial `AGENTS.md` contract

```markdown
# Repository contract

You maintain a personal motorcycle exploration database.

Goals:
- discover minor interesting destinations;
- discover enjoyable road sections;
- discover legal/easy unpaved roads;
- avoid duplicates;
- preserve provenance;
- distinguish facts, inference, and uncertainty.

Canonical data is `data/**/*.yaml`.
Generated projections are `generated/*.geojson` and `rides/*.gpx`.
Never treat generated files as authoritative or edit them by hand.

Allowed statuses: candidate, shortlist, visited, rejected, needs_research.
Score destination interest and road interest independently from 1 to 5.
Retain source URLs and stable OSM, Wikidata, or registry identifiers when available.
Tie material factual and access claims to sources.
Never infer that motorcycle access is legal merely because OSM lacks a restriction.
Represent uncertainty explicitly.
Never silently merge possible duplicates.

Before committing:
1. run `python tools/local_rides.py validate`;
2. run `python tools/local_rides.py generate`;
3. run validation again;
4. include regenerated outputs in the same commit.
```

## 11. GitHub Issue labels

Create only these labels initially:

| Label | Purpose |
| --- | --- |
| `discovery` | Unprocessed place capture |
| `road` | Paved-road or road-section capture |
| `gravel` | Unpaved candidate or observation |
| `visited` | Field observation requiring canonical update |
| `research` | Needs source/access investigation |
| `processed` | Canonical PR created or merged |

Avoid encoding candidate status entirely in labels. The repository record is authoritative.

## 12. Implementation sequence

### Phase 0 — one-time setup

1. Create `local-rides` in GitHub with a README, no framework template.
2. Choose public or private-plus-public-projection visibility.
3. Grant the existing GitHub connection access to the repository if it is installation-scoped.

Exit condition: Work can read the default branch and create a test branch.

### Phase 1 — canonical core

1. Add the directory structure and `AGENTS.md`.
2. Add place and road schema files plus one valid fixture each.
3. Implement `validate`, including cross-file uniqueness and status rules.
4. Add the GitHub Action that installs PyYAML and runs validation.

Exit condition: valid fixtures pass; malformed coordinates, duplicate IDs, broken source references, and inconsistent statuses fail.

### Phase 2 — projections

1. Implement deterministic GeoJSON generation.
2. Add `selections/today.yaml` handling.
3. Commit generated output and add a CI dirty-tree check after generation.
4. Configure uMap remote layers against raw public URLs.

Exit condition: editing one YAML record and regenerating changes the expected uMap-visible feature without manual uMap import.

### Phase 3 — discovery inputs

1. Add four bounded Overpass templates.
2. Document bbox substitution and sensible query size limits.
3. Manually curate a small Bratislava-area seed set to test source handling and dedupe.

Exit condition: each query returns usable geometry and at least one result can be normalized without losing provenance.

### Phase 4 — ride handoff

1. Implement waypoint-oriented GPX export from `today.yaml`.
2. Test the same GPX on iPhone with Kurviger, Mapy.com, and OsmAnd.
3. Document consumer-specific quirks observed in practice.

Exit condition: one selected outing can be opened and routed without editing XML or re-entering every waypoint.

### Phase 5 — mobile inbox

1. Add the permissive capture issue form and labels.
2. Process three deliberately messy test captures through the full branch/PR flow.
3. Add an Apple Shortcut only if GitHub Mobile/share-sheet capture remains materially awkward.

Exit condition: a phone capture becomes a reviewed canonical record with no structured phone entry.

## 13. Deferred work and rejection criteria

Defer Apple Shortcut logic, automated discovery, scheduled scans, Kurviger API integration, and hosting until a repeated manual cost is measured.

Reject a proposed component in version 1 if it introduces any of:

- a continuously running service;
- a separate database;
- credentials outside GitHub and existing map applications;
- two-way synchronization;
- a custom map UI;
- opaque generated state that cannot be rebuilt from YAML.

## 14. First build brief for a coding agent

Implement Phases 1 and 2 only. Use Python 3.12 and PyYAML. Keep all logic in one readable module until it exceeds roughly 500 lines or responsibilities become genuinely separable. Use `argparse`, `json`, `pathlib`, and `xml.etree.ElementTree` from the standard library. Produce stable sorted output with a final newline. Tests use `unittest`; do not add pytest. Do not implement networking, Overpass execution, AI calls, GitHub API calls, routing, or Apple Shortcuts in this build.

Acceptance commands:

```bash
python -m unittest discover -s tests
python tools/local_rides.py validate
python tools/local_rides.py generate
git diff --exit-code
```

