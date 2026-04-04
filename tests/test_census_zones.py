"""Tests for census_zones.py — zone loading and classification."""

import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from census_zones import (
    bounding_box,
    classify_villager,
    load_place,
    make_single_zone,
    zone_bounds,
    zone_center,
)


SAMPLE_TOML = b"""\
[places.piwigord]
poi_regions = [[5, -3], [5, -2]]

[[places.piwigord.zones]]
name = "north"
corners = [[100, -200], [200, -100]]

[[places.piwigord.zones]]
name = "south"
corners = [[100, -100], [200, 0]]

[places.hamlet]
poi_regions = [[1, 1]]

[[places.hamlet.zones]]
name = "center"
center = [50, 50]
radius = 30
"""


@pytest.fixture
def zones_file(tmp_path):
    p = tmp_path / "zones.toml"
    p.write_bytes(SAMPLE_TOML)
    return p


def test_load_place_rect(zones_file):
    place = load_place("piwigord", zones_path=zones_file)
    assert len(place["zones"]) == 2
    assert place["poi_regions"] == [(5, -3), (5, -2)]

    north = place["zones"][0]
    assert north["name"] == "north"
    assert north["type"] == "rect"
    assert north["x_min"] == 100
    assert north["z_max"] == -100


def test_load_place_circle(zones_file):
    place = load_place("hamlet", zones_path=zones_file)
    assert len(place["zones"]) == 1
    z = place["zones"][0]
    assert z["type"] == "circle"
    assert z["center_x"] == 50
    assert z["radius"] == 30


def test_load_place_not_found(zones_file):
    with pytest.raises(KeyError, match="nonexistent"):
        load_place("nonexistent", zones_path=zones_file)


def test_bounding_box_rects():
    zones = [
        {"type": "rect", "name": "a", "x_min": 10, "z_min": -50, "x_max": 30, "z_max": -20},
        {"type": "rect", "name": "b", "x_min": 20, "z_min": -30, "x_max": 40, "z_max": 0},
    ]
    assert bounding_box(zones) == (10, -50, 40, 0)


def test_bounding_box_circle():
    zones = [make_single_zone(center_x=100, center_z=-200, radius=50, name="c")]
    assert bounding_box(zones) == (50, -250, 150, -150)


def test_bounding_box_mixed():
    zones = [
        {"type": "rect", "name": "r", "x_min": 0, "z_min": 0, "x_max": 100, "z_max": 100},
        make_single_zone(center_x=200, center_z=50, radius=10, name="c"),
    ]
    x_min, z_min, x_max, z_max = bounding_box(zones)
    assert x_min == 0
    assert z_min == 0
    assert x_max == 210
    assert z_max == 100


def test_classify_villager_rect():
    zones = [
        {"type": "rect", "name": "north", "x_min": 0, "z_min": -100, "x_max": 100, "z_max": 0},
        {"type": "rect", "name": "south", "x_min": 0, "z_min": 0, "x_max": 100, "z_max": 100},
    ]
    assert classify_villager(zones, x=50, z=-50) == "north"
    assert classify_villager(zones, x=50, z=50) == "south"
    assert classify_villager(zones, x=999, z=999) is None


def test_classify_villager_circle():
    zones = [make_single_zone(center_x=100, center_z=100, radius=10, name="hub")]
    assert classify_villager(zones, x=105, z=100) == "hub"
    assert classify_villager(zones, x=200, z=200) is None


def test_classify_villager_on_boundary():
    """Villager exactly on zone boundary is classified (<=)."""
    zones = [
        {"type": "rect", "name": "a", "x_min": 0, "z_min": 0, "x_max": 10, "z_max": 10},
    ]
    assert classify_villager(zones, x=0, z=0) == "a"
    assert classify_villager(zones, x=10, z=10) == "a"


def test_classify_first_match_wins():
    """Overlapping zones: first match wins."""
    zones = [
        {"type": "rect", "name": "first", "x_min": 0, "z_min": 0, "x_max": 100, "z_max": 100},
        {"type": "rect", "name": "second", "x_min": 0, "z_min": 0, "x_max": 100, "z_max": 100},
    ]
    assert classify_villager(zones, x=50, z=50) == "first"


def test_corners_order_normalized(zones_file):
    """Corners given in any order get normalized to min/max."""
    # The TOML has corners = [[100, -200], [200, -100]] which is already ordered,
    # but let's test with a custom file where they're swapped.
    toml = b"""\
[places.test]
poi_regions = []

[[places.test.zones]]
name = "swapped"
corners = [[200, 0], [100, -100]]
"""
    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
        f.write(toml)
        f.flush()
        place = load_place("test", zones_path=f.name)

    z = place["zones"][0]
    assert z["x_min"] == 100
    assert z["x_max"] == 200
    assert z["z_min"] == -100
    assert z["z_max"] == 0


def test_zone_bounds_rect():
    zone = {"name": "a", "type": "rect", "x_min": 100, "z_min": -200, "x_max": 300, "z_max": -50}
    assert zone_bounds(zone) == (100, -200, 300, -50)


def test_zone_bounds_circle():
    zone = {"name": "b", "type": "circle", "center_x": 150, "center_z": -100, "radius": 50}
    assert zone_bounds(zone) == (100, -150, 200, -50)


def test_zone_center_rect():
    zone = {"type": "rect", "name": "r", "x_min": 0, "z_min": -100, "x_max": 100, "z_max": 0}
    assert zone_center(zone) == (50, -50)


def test_zone_center_circle():
    zone = make_single_zone(center_x=3150, center_z=-950, radius=100, name="c")
    assert zone_center(zone) == (3150, -950)
