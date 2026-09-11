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

## Discovery pull requests

For an agentic discovery task:

1. Determine the target branch and merge-base commit.
2. Research and write canonical records with provenance and explicit access uncertainty.
3. Run validation, generation, and deduplication.
4. Generate `generated/latest-discovery.geojson` containing only records added or materially modified by the task. Use `python tools/local_rides.py review --base-ref origin/main` in a Git checkout, or pass each id with `--added` or `--modified`.
5. Commit canonical records and every generated projection.
6. After the commit SHA is known, use `python tools/local_rides.py preview-url --base-sha BASE --head-sha HEAD`.
7. Put both clickable uMap links in the pull request description: proposed features alone and proposed features with the base catalogue context.
8. Include a candidate table, validation results, and unresolved access questions in the pull request description.
9. Regenerate the review projection and replace the URLs after later discovery commits.

The review projection is generated, not canonical. New features are crimson and modified features are dark orange. Never give an agent uMap session cookies or GitHub SSO credentials; uMap consumes the immutable raw GitHub URLs without authentication.
