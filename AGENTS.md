# Repository contract

You maintain a personal motorcycle exploration database.

## Goals

- Discover minor interesting destinations.
- Discover enjoyable road sections.
- Discover legal or plausibly legal easy unpaved roads.
- Avoid duplicates.
- Preserve provenance.
- Distinguish facts, inference, uncertainty, and personal observations.

## Authority

- Canonical data: `data/**/*.yaml`
- Manual ride selection: `selections/today.yaml`
- Generated projections: `generated/*.geojson` and `rides/*.gpx`

Never treat generated files as authoritative. Never edit generated files by hand.

## Data rules

- Allowed statuses: `candidate`, `shortlist`, `visited`, `rejected`, `needs_research`.
- Score destination interest and road interest independently from 1 to 5.
- Retain source URLs and stable OSM, Wikidata, or registry identifiers when available.
- Tie material factual and access claims to sources.
- Never infer legal motorcycle access merely because OSM lacks a restriction.
- Represent uncertainty explicitly.
- Never silently merge possible duplicates.
- Preserve an object's internal `id` after creation.
- GeoJSON coordinate arrays use longitude, latitude order.

## Required checks

Before committing canonical changes:

1. Run `python tools/local_rides.py validate`.
2. Run `python tools/local_rides.py generate`.
3. Run `python tools/local_rides.py validate` again.
4. Include regenerated output in the same commit.

