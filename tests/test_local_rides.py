from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "local_rides.py"
SPEC = importlib.util.spec_from_file_location("local_rides", MODULE_PATH)
assert SPEC and SPEC.loader
local_rides = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = local_rides
SPEC.loader.exec_module(local_rides)


PLACE = """\
schema_version: 1
id: test-well
kind: place
name: Test well
coordinates:
  lat: 48.1
  lon: 17.1
categories: [well, historical]
status: shortlist
scores:
  destination: 3
  road: 4
access:
  motorcycle: unknown
  legal_confidence: unknown
  surface: paved
approach:
  mode: park_and_walk
  coordinates:
    lat: 48.11
    lon: 17.11
sources:
  - id: osm
    type: osm
    ref: node/123
    url: https://www.openstreetmap.org/node/123
claims:
  - text: The mapped object is tagged as a well.
    certainty: confirmed
    source_refs: [osm]
notes: Test fixture.
visits: []
"""

ROAD = """\
schema_version: 1
id: test-road
kind: road
name: Test road
geometry:
  type: LineString
  coordinates:
    - [17.10, 48.10]
    - [17.12, 48.12]
categories: [gravel]
status: candidate
scores:
  destination: 1
  road: 5
access:
  motorcycle: unknown
  legal_confidence: unknown
  surface: gravel
sources: []
claims: []
visits: []
"""


class LocalRidesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for directory in ("data/places", "data/roads", "selections", "generated", "rides"):
            (self.root / directory).mkdir(parents=True)
        (self.root / "data/places/test-well.yaml").write_text(PLACE, encoding="utf-8")
        (self.root / "data/roads/test-road.yaml").write_text(ROAD, encoding="utf-8")
        (self.root / "selections/today.yaml").write_text(
            "name: Test ride\ndate: 2026-09-11\n"
            "start:\n  name: Test start\n  coordinates: {lat: 48.0, lon: 17.0}\n"
            "return_to_start: true\nitems: [test-well, test-road]\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_valid_records(self) -> None:
        records, errors = local_rides.validate_all(self.root)
        self.assertEqual(errors, [])
        self.assertEqual([record.id for record in records], ["test-well", "test-road"])

    def test_generate_views(self) -> None:
        self.assertEqual(local_rides.cmd_generate(self.root), 0)
        places = json.loads((self.root / "generated/places.geojson").read_text())
        today = json.loads((self.root / "generated/today.geojson").read_text())
        self.assertEqual([feature["id"] for feature in places["features"]], ["test-well"])
        self.assertEqual([feature["id"] for feature in today["features"]], ["selection-start", "test-well", "test-road"])
        self.assertEqual(today["features"][2]["properties"]["ride_order"], 2)

    def test_gpx_contains_place_and_road_endpoints(self) -> None:
        output = self.root / "rides/test.gpx"
        result = local_rides.cmd_gpx(self.root, self.root / "selections/today.yaml", output)
        self.assertEqual(result, 0)
        document = ET.parse(output)
        namespace = {"g": "http://www.topografix.com/GPX/1/1"}
        self.assertEqual(len(document.findall("g:wpt", namespace)), 5)
        self.assertEqual(len(document.findall("g:rte/g:rtept", namespace)), 5)
        self.assertEqual(document.findall("g:wpt", namespace)[1].attrib["lat"], "48.11")

    def test_invalid_coordinate_fails(self) -> None:
        bad = PLACE.replace("lat: 48.1", "lat: 148.1")
        (self.root / "data/places/test-well.yaml").write_text(bad, encoding="utf-8")
        _, errors = local_rides.validate_all(self.root)
        self.assertTrue(any("coordinates.lat" in error for error in errors))

    def test_duplicate_external_identity_fails(self) -> None:
        duplicate = PLACE.replace("id: test-well", "id: second-well").replace("name: Test well", "name: Second well")
        (self.root / "data/places/second-well.yaml").write_text(duplicate, encoding="utf-8")
        _, errors = local_rides.validate_all(self.root)
        self.assertTrue(any("duplicate external identity" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
