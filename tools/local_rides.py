#!/usr/bin/env python3
"""Validate local-rides YAML and generate portable GeoJSON/GPX views."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

import yaml


STATUSES = {"candidate", "shortlist", "visited", "rejected", "needs_research"}
MOTORCYCLE_ACCESS = {"yes", "no", "likely", "unknown"}
LEGAL_CONFIDENCE = {"confirmed", "inferred", "unknown"}
SURFACES = {"paved", "unpaved", "gravel", "dirt", "mixed", "unknown"}
CERTAINTIES = {"confirmed", "inferred", "uncertain"}
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EXTERNAL_ID_TYPES = {"osm", "wikidata", "heritage_registry"}
REVIEW_COLORS = {"added": "Crimson", "modified": "DarkOrange"}


@dataclass(frozen=True)
class Record:
    path: Path
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.data.get("id", ""))


def yaml_load(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read YAML: {exc}") from exc


def discover_records(root: Path) -> list[Record]:
    records: list[Record] = []
    for kind in ("places", "roads"):
        directory = root / "data" / kind
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            raw = yaml_load(path)
            if not isinstance(raw, dict):
                raise ValueError(f"{path.relative_to(root)}: document must be a mapping")
            records.append(Record(path, raw))
    return records


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def require_mapping(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} must be a mapping")
        return {}
    return value


def require_list(value: Any, label: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{label} must be a list")
        return []
    return value


def validate_record(record: Record, root: Path) -> list[str]:
    data = record.data
    rel = record.path.relative_to(root)
    errors: list[str] = []

    def error(message: str) -> None:
        errors.append(f"{rel}: {message}")

    if data.get("schema_version") != 1:
        error("schema_version must be 1")
    record_id = data.get("id")
    if not isinstance(record_id, str) or not ID_RE.fullmatch(record_id):
        error("id must be lowercase kebab-case")
    expected_kind = "place" if record.path.parent.name == "places" else "road"
    if data.get("kind") != expected_kind:
        error(f"kind must be {expected_kind!r} in this directory")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        error("name must be a non-empty string")

    categories = data.get("categories")
    if not isinstance(categories, list) or not categories or not all(isinstance(x, str) and x.strip() for x in categories):
        error("categories must be a non-empty list of strings")
    elif len(categories) != len(set(categories)):
        error("categories must not contain duplicates")

    status = data.get("status")
    if status not in STATUSES:
        error(f"status must be one of {sorted(STATUSES)}")

    scores = require_mapping(data.get("scores"), "scores", errors)
    for field in ("destination", "road"):
        score = scores.get(field)
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
            error(f"scores.{field} must be an integer from 1 to 5")

    access = require_mapping(data.get("access"), "access", errors)
    if access.get("motorcycle") not in MOTORCYCLE_ACCESS:
        error(f"access.motorcycle must be one of {sorted(MOTORCYCLE_ACCESS)}")
    if access.get("legal_confidence") not in LEGAL_CONFIDENCE:
        error(f"access.legal_confidence must be one of {sorted(LEGAL_CONFIDENCE)}")
    if access.get("surface") not in SURFACES:
        error(f"access.surface must be one of {sorted(SURFACES)}")

    if expected_kind == "place":
        coordinates = require_mapping(data.get("coordinates"), "coordinates", errors)
        lat, lon = coordinates.get("lat"), coordinates.get("lon")
        if not is_number(lat) or not -90 <= lat <= 90:
            error("coordinates.lat must be a finite number from -90 to 90")
        if not is_number(lon) or not -180 <= lon <= 180:
            error("coordinates.lon must be a finite number from -180 to 180")
    else:
        geometry = require_mapping(data.get("geometry"), "geometry", errors)
        if geometry.get("type") != "LineString":
            error("geometry.type must be LineString")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            error("geometry.coordinates must contain at least two [lon, lat] positions")
        else:
            for index, position in enumerate(coordinates):
                if (
                    not isinstance(position, list)
                    or len(position) != 2
                    or not is_number(position[0])
                    or not is_number(position[1])
                    or not -180 <= position[0] <= 180
                    or not -90 <= position[1] <= 90
                ):
                    error(f"geometry.coordinates[{index}] must be [lon, lat] within valid ranges")

    approach = data.get("approach")
    if approach is not None:
        approach = require_mapping(approach, "approach", errors)
        if approach.get("mode") not in {"ride_to", "roadside", "park_and_walk"}:
            error("approach.mode must be ride_to, roadside, or park_and_walk")
        approach_coordinates = require_mapping(approach.get("coordinates"), "approach.coordinates", errors)
        lat, lon = approach_coordinates.get("lat"), approach_coordinates.get("lon")
        if not is_number(lat) or not -90 <= lat <= 90:
            error("approach.coordinates.lat must be a finite number from -90 to 90")
        if not is_number(lon) or not -180 <= lon <= 180:
            error("approach.coordinates.lon must be a finite number from -180 to 180")

    sources = require_list(data.get("sources"), "sources", errors)
    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            error(f"sources[{index}] must be a mapping")
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id:
            error(f"sources[{index}].id must be a non-empty string")
        elif source_id in source_ids:
            error(f"duplicate local source id {source_id!r}")
        else:
            source_ids.add(source_id)
        if not isinstance(source.get("type"), str) or not source["type"]:
            error(f"sources[{index}].type must be a non-empty string")
        url = source.get("url")
        if url is not None and (not isinstance(url, str) or not url.startswith(("https://", "http://"))):
            error(f"sources[{index}].url must be an HTTP(S) URL")

    claims = data.get("claims", [])
    if not isinstance(claims, list):
        error("claims must be a list")
        claims = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            error(f"claims[{index}] must be a mapping")
            continue
        if not isinstance(claim.get("text"), str) or not claim["text"].strip():
            error(f"claims[{index}].text must be a non-empty string")
        if claim.get("certainty") not in CERTAINTIES:
            error(f"claims[{index}].certainty must be one of {sorted(CERTAINTIES)}")
        refs = claim.get("source_refs")
        if not isinstance(refs, list):
            error(f"claims[{index}].source_refs must be a list")
        else:
            for ref in refs:
                if ref not in source_ids:
                    error(f"claims[{index}] refers to unknown source {ref!r}")

    visits = data.get("visits")
    if not isinstance(visits, list):
        error("visits must be a list")
        visits = []
    if status == "visited" and not visits:
        error("status visited requires at least one visit")
    if status != "visited" and visits:
        error("records with visits must use status visited")
    for index, visit in enumerate(visits):
        if not isinstance(visit, dict) or not isinstance(visit.get("date"), (str, __import__("datetime").date)):
            error(f"visits[{index}] must contain a date")

    if status == "rejected":
        rejection = data.get("rejection")
        if not isinstance(rejection, dict) or not isinstance(rejection.get("reason"), str) or not rejection["reason"].strip():
            error("status rejected requires rejection.reason")

    return errors


def external_keys(record: Record) -> Iterable[tuple[str, str]]:
    for source in record.data.get("sources", []):
        if not isinstance(source, dict) or source.get("type") not in EXTERNAL_ID_TYPES:
            continue
        ref = source.get("ref")
        if isinstance(ref, str) and ref:
            yield source["type"], ref


def validate_all(root: Path) -> tuple[list[Record], list[str]]:
    try:
        records = discover_records(root)
    except ValueError as exc:
        return [], [str(exc)]
    errors = [item for record in records for item in validate_record(record, root)]

    ids: dict[str, Path] = {}
    externals: dict[tuple[str, str], Record] = {}
    for record in records:
        if record.id in ids:
            errors.append(
                f"{record.path.relative_to(root)}: duplicate id {record.id!r}; "
                f"first used by {ids[record.id].relative_to(root)}"
            )
        else:
            ids[record.id] = record.path
        for key in external_keys(record):
            if key in externals:
                errors.append(
                    f"{record.path.relative_to(root)}: duplicate external identity "
                    f"{key[0]}:{key[1]}; first used by {externals[key].path.relative_to(root)}"
                )
            else:
                externals[key] = record
    return records, errors


def source_urls(data: dict[str, Any]) -> list[str]:
    return [s["url"] for s in data.get("sources", []) if isinstance(s, dict) and isinstance(s.get("url"), str)]


def feature(record: Record, order: int | None = None) -> dict[str, Any]:
    data = record.data
    if data["kind"] == "place":
        geometry = {
            "type": "Point",
            "coordinates": [data["coordinates"]["lon"], data["coordinates"]["lat"]],
        }
    else:
        geometry = data["geometry"]
    properties: dict[str, Any] = {
        "id": data["id"],
        "name": data["name"],
        "kind": data["kind"],
        "categories": data["categories"],
        "status": data["status"],
        "destination_score": data["scores"]["destination"],
        "road_score": data["scores"]["road"],
        "motorcycle_access": data["access"]["motorcycle"],
        "legal_confidence": data["access"]["legal_confidence"],
        "surface": data["access"]["surface"],
        "notes": data.get("notes", ""),
        "source_urls": source_urls(data),
    }
    if "approach" in data:
        properties["approach_mode"] = data["approach"]["mode"]
        properties["approach_notes"] = data["approach"].get("notes", "")
    if order is not None:
        properties["ride_order"] = order
    return {"type": "Feature", "id": data["id"], "geometry": geometry, "properties": properties}


def review_description(data: dict[str, Any], change_type: str) -> str:
    scores = data["scores"]
    access = data["access"]
    lines = [
        f"Change: {change_type}",
        f"Status: {data['status']}",
        f"Destination: {scores['destination']}/5",
        f"Road: {scores['road']}/5",
        f"Motorcycle access: {access['motorcycle']}",
        f"Legal confidence: {access['legal_confidence']}",
        f"Surface: {access['surface']}",
    ]
    if data.get("notes"):
        lines.extend(["", str(data["notes"])])
    urls = source_urls(data)
    if urls:
        lines.extend(["", "Sources:", *urls])
    return "\n".join(lines)


def review_feature(record: Record, change_type: str) -> dict[str, Any]:
    item = feature(record)
    properties = item["properties"]
    properties["change_type"] = change_type
    properties["description"] = review_description(record.data, change_type)
    properties["_umap_options"] = {"color": REVIEW_COLORS[change_type]}
    return item


def collection(records: Iterable[Record]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": [feature(r) for r in sorted(records, key=lambda x: x.id)]}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda item: item.isoformat(),
        )
        + "\n",
        encoding="utf-8",
    )


def load_selection(root: Path, path: Path | None = None) -> tuple[dict[str, Any], list[str]]:
    selection_path = path or root / "selections" / "today.yaml"
    try:
        raw = yaml_load(selection_path)
    except ValueError as exc:
        return {}, [f"{selection_path}: {exc}"]
    if not isinstance(raw, dict):
        return {}, [f"{selection_path}: selection must be a mapping"]
    errors: list[str] = []
    if not isinstance(raw.get("name"), str) or not raw["name"].strip():
        errors.append(f"{selection_path}: name must be a non-empty string")
    items = raw.get("items")
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        errors.append(f"{selection_path}: items must be a list of record ids")
    elif len(items) != len(set(items)):
        errors.append(f"{selection_path}: items must not contain duplicates")
    start = raw.get("start")
    if start is not None:
        if not isinstance(start, dict):
            errors.append(f"{selection_path}: start must be a mapping")
        else:
            coordinates = start.get("coordinates")
            if not isinstance(start.get("name"), str) or not start["name"].strip():
                errors.append(f"{selection_path}: start.name must be a non-empty string")
            if not isinstance(coordinates, dict):
                errors.append(f"{selection_path}: start.coordinates must be a mapping")
            else:
                lat, lon = coordinates.get("lat"), coordinates.get("lon")
                if not is_number(lat) or not -90 <= lat <= 90:
                    errors.append(f"{selection_path}: start.coordinates.lat is invalid")
                if not is_number(lon) or not -180 <= lon <= 180:
                    errors.append(f"{selection_path}: start.coordinates.lon is invalid")
    if not isinstance(raw.get("return_to_start", False), bool):
        errors.append(f"{selection_path}: return_to_start must be true or false")
    return raw, errors


def selection_start_feature(selection: dict[str, Any]) -> dict[str, Any] | None:
    start = selection.get("start")
    if not start:
        return None
    coordinates = start["coordinates"]
    return {
        "type": "Feature",
        "id": "selection-start",
        "geometry": {"type": "Point", "coordinates": [coordinates["lon"], coordinates["lat"]]},
        "properties": {"id": "selection-start", "name": start["name"], "kind": "start", "ride_order": 0},
    }


def select_records(records: list[Record], selection: dict[str, Any], path: Path) -> tuple[list[Record], list[str]]:
    by_id = {record.id: record for record in records}
    selected: list[Record] = []
    errors: list[str] = []
    for item in selection.get("items", []):
        if item not in by_id:
            errors.append(f"{path}: unknown selected id {item!r}")
        else:
            selected.append(by_id[item])
    return selected, errors


def cmd_validate(root: Path) -> int:
    records, errors = validate_all(root)
    selection, selection_errors = load_selection(root)
    errors.extend(selection_errors)
    if not selection_errors:
        _, unknown = select_records(records, selection, root / "selections" / "today.yaml")
        errors.extend(unknown)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Validated {len(records)} record(s).")
    return 0


def cmd_generate(root: Path) -> int:
    records, errors = validate_all(root)
    selection, selection_errors = load_selection(root)
    errors.extend(selection_errors)
    selected: list[Record] = []
    if not selection_errors:
        selected, unknown = select_records(records, selection, root / "selections" / "today.yaml")
        errors.extend(unknown)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    places = [r for r in records if r.data["kind"] == "place" and r.data["status"] != "rejected"]
    unvisited = [r for r in places if r.data["status"] in {"candidate", "shortlist", "needs_research"}]
    shortlist = [r for r in places if r.data["status"] == "shortlist"]
    roads = [r for r in records if r.data["kind"] == "road" and r.data["status"] != "rejected"]
    today_features = [feature(record, order=index) for index, record in enumerate(selected, 1)]
    start_feature = selection_start_feature(selection)
    if start_feature:
        today_features.insert(0, start_feature)
    today = {
        "type": "FeatureCollection",
        "name": selection["name"],
        "date": selection.get("date"),
        "features": today_features,
    }
    generated = root / "generated"
    write_json(generated / "places.geojson", collection(places))
    write_json(generated / "unvisited.geojson", collection(unvisited))
    write_json(generated / "shortlist.geojson", collection(shortlist))
    write_json(generated / "roads.geojson", collection(roads))
    write_json(generated / "today.geojson", today)
    print(f"Generated five GeoJSON views from {len(records)} record(s).")
    return 0


def changed_record_ids(root: Path, base_ref: str) -> tuple[dict[str, str], list[str]]:
    command = [
        "git",
        "diff",
        "--name-status",
        f"{base_ref}...HEAD",
        "--",
        "data/places",
        "data/roads",
    ]
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "git diff failed"
        return {}, [f"cannot compare with {base_ref!r}: {detail}"]
    changes: dict[str, str] = {}
    errors: list[str] = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        status = fields[0]
        path_text = fields[-1]
        if status.startswith("D") or not path_text.endswith(".yaml"):
            continue
        path = root / path_text
        if not path.exists():
            errors.append(f"changed record does not exist: {path_text}")
            continue
        try:
            raw = yaml_load(path)
        except ValueError as exc:
            errors.append(f"{path_text}: {exc}")
            continue
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            errors.append(f"{path_text}: changed record has no valid id")
            continue
        changes[raw["id"]] = "added" if status.startswith("A") else "modified"
    return changes, errors


def cmd_review(
    root: Path,
    output: Path,
    base_ref: str | None,
    added_ids: list[str],
    modified_ids: list[str],
) -> int:
    records, errors = validate_all(root)
    changes: dict[str, str] = {}
    if base_ref:
        changes, change_errors = changed_record_ids(root, base_ref)
        errors.extend(change_errors)
    for record_id in added_ids:
        changes[record_id] = "added"
    for record_id in modified_ids:
        if changes.get(record_id) == "added":
            errors.append(f"review id {record_id!r} cannot be both added and modified")
        else:
            changes[record_id] = "modified"

    by_id = {record.id: record for record in records}
    for record_id in changes:
        if record_id not in by_id:
            errors.append(f"unknown review id {record_id!r}")
    if not changes:
        errors.append("review contains no added or modified record ids")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    features = [review_feature(by_id[record_id], changes[record_id]) for record_id in sorted(changes)]
    value = {
        "type": "FeatureCollection",
        "name": "Latest discovery review",
        "features": features,
    }
    write_json(output, value)
    print(f"Generated uMap review projection with {len(features)} feature(s) at {output}.")
    return 0


def umap_preview_urls(
    repository: str,
    base_sha: str,
    head_sha: str,
    instance: str,
    review_path: str,
) -> tuple[str, str]:
    raw = f"https://raw.githubusercontent.com/{repository}"
    review_url = f"{raw}/{head_sha}/{review_path}"
    review_query = urlencode([("dataUrl", review_url), ("dataFormat", "geojson")])
    review_only = f"{instance.rstrip('/')}/?{review_query}"
    context_query = urlencode(
        [
            ("dataUrl", f"{raw}/{base_sha}/generated/places.geojson"),
            ("dataUrl", f"{raw}/{base_sha}/generated/roads.geojson"),
            ("dataUrl", review_url),
            ("dataFormat", "geojson"),
        ]
    )
    context = f"{instance.rstrip('/')}/?{context_query}"
    return review_only, context


def cmd_preview_url(
    repository: str,
    base_sha: str,
    head_sha: str,
    instance: str,
    review_path: str,
) -> int:
    review_only, context = umap_preview_urls(repository, base_sha, head_sha, instance, review_path)
    print(f"Review only: {review_only}")
    print(f"With catalogue context: {context}")
    return 0


def haversine_m(a: Record, b: Record) -> float:
    lat1 = math.radians(a.data["coordinates"]["lat"])
    lat2 = math.radians(b.data["coordinates"]["lat"])
    dlat = lat2 - lat1
    dlon = math.radians(b.data["coordinates"]["lon"] - a.data["coordinates"]["lon"])
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def normalized_name(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def cmd_dedupe(root: Path) -> int:
    records, errors = validate_all(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    places = [r for r in records if r.data["kind"] == "place"]
    findings = 0
    for index, first in enumerate(places):
        for second in places[index + 1 :]:
            distance = haversine_m(first, second)
            shared_categories = set(first.data["categories"]) & set(second.data["categories"])
            shared_name = normalized_name(first.data["name"]) & normalized_name(second.data["name"])
            if distance <= 25 and shared_categories or distance <= 75 and shared_name:
                findings += 1
                print(f"POSSIBLE DUPLICATE: {first.id} <-> {second.id} ({distance:.0f} m)")
    if not findings:
        print("No possible spatial duplicates found.")
    return 0


def route_positions(record: Record) -> list[tuple[float, float, str]]:
    data = record.data
    if data["kind"] == "place":
        if "approach" in data:
            coordinates = data["approach"]["coordinates"]
            return [(coordinates["lat"], coordinates["lon"], data["name"])]
        return [(data["coordinates"]["lat"], data["coordinates"]["lon"], data["name"])]
    coordinates = data["geometry"]["coordinates"]
    return [
        (coordinates[0][1], coordinates[0][0], f"{data['name']} — start"),
        (coordinates[-1][1], coordinates[-1][0], f"{data['name']} — end"),
    ]


def cmd_gpx(root: Path, selection_path: Path, output: Path) -> int:
    records, errors = validate_all(root)
    selection, selection_errors = load_selection(root, selection_path)
    errors.extend(selection_errors)
    selected: list[Record] = []
    if not selection_errors:
        selected, unknown = select_records(records, selection, selection_path)
        errors.extend(unknown)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    gpx = ET.Element(
        "gpx",
        {"version": "1.1", "creator": "local-rides", "xmlns": "http://www.topografix.com/GPX/1/1"},
    )
    metadata = ET.SubElement(gpx, "metadata")
    ET.SubElement(metadata, "name").text = selection["name"]
    route = ET.SubElement(gpx, "rte")
    ET.SubElement(route, "name").text = selection["name"]
    positions: list[tuple[float, float, str]] = []
    if selection.get("start"):
        start = selection["start"]
        positions.append((start["coordinates"]["lat"], start["coordinates"]["lon"], start["name"]))
    for record in selected:
        positions.extend(route_positions(record))
    if selection.get("return_to_start") and selection.get("start"):
        start = selection["start"]
        positions.append((start["coordinates"]["lat"], start["coordinates"]["lon"], f"{start['name']} — return"))
    for lat, lon, name in positions:
        waypoint = ET.SubElement(gpx, "wpt", {"lat": str(lat), "lon": str(lon)})
        ET.SubElement(waypoint, "name").text = name
        routepoint = ET.SubElement(route, "rtept", {"lat": str(lat), "lon": str(lon)})
        ET.SubElement(routepoint, "name").text = name
    ET.indent(gpx, space="  ")
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(gpx).write(output, encoding="utf-8", xml_declaration=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write("\n")
    print(f"Wrote GPX route with {len(selected)} selected item(s) and {len(positions)} route point(s) to {output}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="repository root")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate all canonical records and the current selection")
    subparsers.add_parser("generate", help="regenerate committed GeoJSON views")
    subparsers.add_parser("dedupe", help="report possible nearby duplicate places")
    review = subparsers.add_parser("review", help="generate a highlighted GeoJSON projection for PR review")
    review.add_argument("--base-ref", help="git ref to compare with HEAD, for example origin/main")
    review.add_argument("--added", action="append", default=[], help="canonical id added by the discovery batch")
    review.add_argument("--modified", action="append", default=[], help="canonical id modified by the discovery batch")
    review.add_argument("--output", type=Path, default=Path("generated/latest-discovery.geojson"))
    preview = subparsers.add_parser("preview-url", help="print immutable uMap links for a discovery review")
    preview.add_argument("--repository", default="sanicek/local-rides", help="GitHub owner/repository")
    preview.add_argument("--base-sha", required=True, help="immutable base commit SHA")
    preview.add_argument("--head-sha", required=True, help="immutable review commit SHA")
    preview.add_argument("--instance", default="https://framacarte.org/en/map/", help="uMap-compatible map URL")
    preview.add_argument("--review-path", default="generated/latest-discovery.geojson")
    gpx = subparsers.add_parser("gpx", help="export an ordered selection as GPX waypoints and route points")
    gpx.add_argument("--selection", type=Path, default=Path("selections/today.yaml"))
    gpx.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    if args.command == "validate":
        return cmd_validate(root)
    if args.command == "generate":
        return cmd_generate(root)
    if args.command == "dedupe":
        return cmd_dedupe(root)
    if args.command == "review":
        output = args.output if args.output.is_absolute() else root / args.output
        return cmd_review(root, output, args.base_ref, args.added, args.modified)
    if args.command == "preview-url":
        return cmd_preview_url(args.repository, args.base_sha, args.head_sha, args.instance, args.review_path)
    selection = args.selection if args.selection.is_absolute() else root / args.selection
    output = args.output if args.output.is_absolute() else root / args.output
    return cmd_gpx(root, selection, output)


if __name__ == "__main__":
    raise SystemExit(main())
