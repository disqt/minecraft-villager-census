"""census_zones.py — Zone configuration loading and villager classification."""

import tomllib
from pathlib import Path


DEFAULT_ZONES_PATH = Path(__file__).parent / "zones.toml"


def load_place(place_name, *, zones_path=None):
    """Load a place definition from zones.toml.

    Returns a dict with keys:
        zones: list of zone dicts (each has 'name' and geometry)
        poi_regions: list of (rx, rz) tuples
    """
    path = Path(zones_path) if zones_path else DEFAULT_ZONES_PATH
    with open(path, "rb") as f:
        config = tomllib.load(f)

    places = config.get("places", {})
    if place_name not in places:
        available = ", ".join(sorted(places)) or "(none)"
        raise KeyError(f"Place '{place_name}' not found in {path}. Available: {available}")

    place = places[place_name]
    zones = [_parse_zone(z) for z in place.get("zones", [])]
    poi_regions = [tuple(r) for r in place.get("poi_regions", [])]

    return {"zones": zones, "poi_regions": poi_regions}


def _parse_zone(raw):
    """Parse a zone entry from TOML into a normalized dict."""
    name = raw["name"]

    if "corners" in raw:
        (x_min, z_min), (x_max, z_max) = raw["corners"]
        return {
            "name": name,
            "type": "rect",
            "x_min": min(x_min, x_max),
            "z_min": min(z_min, z_max),
            "x_max": max(x_min, x_max),
            "z_max": max(z_min, z_max),
        }

    if "center" in raw and "radius" in raw:
        cx, cz = raw["center"]
        r = raw["radius"]
        return {
            "name": name,
            "type": "circle",
            "center_x": cx,
            "center_z": cz,
            "radius": r,
        }

    raise ValueError(f"Zone '{name}' must have 'corners' or 'center'+'radius'")


def make_single_zone(*, center_x, center_z, radius, name="default"):
    """Create a single circular zone (for backward-compatible point+radius mode)."""
    return {
        "name": name,
        "type": "circle",
        "center_x": center_x,
        "center_z": center_z,
        "radius": radius,
    }


def zone_bounds(zone):
    """Return (x_min, z_min, x_max, z_max) for a single zone."""
    if zone["type"] == "rect":
        return zone["x_min"], zone["z_min"], zone["x_max"], zone["z_max"]
    elif zone["type"] == "circle":
        r = zone["radius"]
        return (zone["center_x"] - r, zone["center_z"] - r,
                zone["center_x"] + r, zone["center_z"] + r)


def bounding_box(zones):
    """Compute the axis-aligned bounding box covering all zones.

    Returns (x_min, z_min, x_max, z_max).
    """
    boxes = [zone_bounds(z) for z in zones]
    x_mins, z_mins, x_maxs, z_maxs = zip(*boxes)
    return min(x_mins), min(z_mins), max(x_maxs), max(z_maxs)


def zone_center(zone):
    """Return the (x, z) center of a zone as integers."""
    if zone["type"] == "circle":
        return int(zone["center_x"]), int(zone["center_z"])
    elif zone["type"] == "rect":
        cx = (zone["x_min"] + zone["x_max"]) // 2
        cz = (zone["z_min"] + zone["z_max"]) // 2
        return cx, cz


def classify_villager(zones, *, x, z):
    """Return the name of the zone containing (x, z), or None if outside all zones."""
    for zone in zones:
        if zone["type"] == "rect":
            if zone["x_min"] <= x <= zone["x_max"] and zone["z_min"] <= z <= zone["z_max"]:
                return zone["name"]
        elif zone["type"] == "circle":
            dx = x - zone["center_x"]
            dz = z - zone["center_z"]
            if dx * dx + dz * dz <= zone["radius"] ** 2:
                return zone["name"]
    return None


def classify_bed(zones, *, x, z):
    """Return the name of the zone containing bed at (x, z), or None."""
    return classify_villager(zones, x=x, z=z)
