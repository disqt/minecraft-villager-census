"""Integration tests for the census pipeline orchestrator."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import census
from census_db import init_db, get_latest_snapshot, get_snapshot_villager_uuids
from census_zones import make_single_zone


SAMPLE_ENTITY_LINE = """[19:44:53] [Server thread/INFO]: Fisherman has the following entity data: {Paper.SpawnReason: "BREEDING", DeathTime: 0s, Bukkit.updateLevel: 2, RestocksToday: 0, Xp: 0, OnGround: 1b, LeftHanded: 0b, AbsorptionAmount: 0.0f, FoodLevel: 0b, LastRestock: 1001127489L, AgeLocked: 0b, Invulnerable: 0b, Brain: {memories: {"minecraft:last_woken": {value: 1018112423L}, "minecraft:job_site": {value: {pos: [I; 3172, 70, -754], dimension: "minecraft:overworld"}}, "minecraft:last_slept": {value: 1018111156L}, "minecraft:last_worked_at_poi": {value: 1001132966L}, "minecraft:meeting_point": {value: {pos: [I; 3170, 66, -883], dimension: "minecraft:overworld"}}}}, Paper.Origin: [3145.9453962812213d, 63.9375d, -1006.4578843209587d], Age: 0, Rotation: [44.46672f, 0.0f], HurtByTimestamp: 0, Bukkit.Aware: 1b, ForcedAge: 0, attributes: [{base: 0.5d, id: "minecraft:movement_speed"}], WorldUUIDMost: -8821679170295479734L, fall_distance: 0.0d, Air: 300s, Offers: {Recipes: [{buy: {id: "minecraft:emerald", count: 1}, sell: {id: "minecraft:cooked_cod", count: 6}, priceMultiplier: 0.05f, buyB: {id: "minecraft:cod", count: 6}, maxUses: 16}]}, UUID: [I; 346464738, -1288157012, -1558611273, 949520682], Inventory: [{id: "minecraft:beetroot", count: 2}], Spigot.ticksLived: 821095, Paper.OriginWorld: [I; -2053957240, -1408023990, -1113309832, -1718626039], Gossips: [], VillagerData: {type: "minecraft:taiga", profession: "minecraft:fisherman", level: 1}, WorldUUIDLeast: -4781629316178913015L, Motion: [0.0d, -0.0784000015258789d, 0.0d], Pos: [3173.038130397757d, 70.0d, -755.0478646574805d], Fire: 0s, CanPickUpLoot: 1b, Health: 16.0f, HurtTime: 0s, FallFlying: 0b, PersistenceRequired: 0b, LastGossipDecay: 1024984001L, PortalCooldown: 0}"""

SAMPLE_BEDS = [
    {"type": "minecraft:home", "pos": [3172, 69, -923], "free_tickets": 0},
    {"type": "minecraft:home", "pos": [3140, 67, -1042], "free_tickets": 1},
]

# Default test zone: single circle covering the sample data
TEST_ZONES = [make_single_zone(center_x=3150, center_z=-950, radius=300, name="test-area")]
TEST_POI_REGIONS = [(5, -3), (5, -2), (6, -3), (6, -2)]


def _run_with_mocks(db_path, *, villagers=None, beds=None, players=None,
                    zones=None, plugin_events=None):
    """Helper to run census with standard mocks."""
    if villagers is None:
        from census_parse import parse_entity_line
        villagers = [parse_entity_line(SAMPLE_ENTITY_LINE)]
    if beds is None:
        beds = SAMPLE_BEDS
    if players is None:
        players = []
    if zones is None:
        zones = TEST_ZONES
    if plugin_events is None:
        plugin_events = []

    with (
        patch("census.check_players_online", return_value=players),
        patch("census.get_entity_files", return_value=[]),
        patch("census.parse_entity_regions", return_value=villagers),
        patch("census.get_poi_files", return_value=[]),
        patch("census.parse_poi_regions", return_value=beds),
        patch("census.get_villager_events", return_value=plugin_events),
    ):
        return census.run_census(
            db_path=db_path,
            zones=zones,
            poi_regions=TEST_POI_REGIONS,
        )


def test_run_census_end_to_end():
    """Full pipeline integration: mocked SSH, real SNBT parsing, real DB."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    summary = _run_with_mocks(db_path, players=["Termiduck"])

    assert summary["villager_count"] == 1
    assert summary["bed_count"] == 2
    assert summary["births"] == 1
    assert summary["deaths"] == 0
    assert summary["players_online"] == ["Termiduck"]
    assert "zones" in summary
    assert "test-area" in summary["zones"]

    conn = init_db(db_path)
    snap = get_latest_snapshot(conn)
    assert snap is not None
    assert snap["villager_count"] == 1
    assert snap["bed_count"] == 2

    cur = conn.execute("SELECT * FROM villagers")
    villagers = [dict(r) for r in cur.fetchall()]
    assert len(villagers) == 1
    assert villagers[0]["spawn_reason"] == "BREEDING"

    cur = conn.execute("SELECT * FROM villager_trades")
    assert len(cur.fetchall()) == 1

    cur = conn.execute("SELECT * FROM villager_inventory")
    assert len(cur.fetchall()) == 1

    cur = conn.execute("SELECT * FROM beds")
    assert len(cur.fetchall()) == 2

    conn.close()


def test_run_census_detects_deaths():
    """Second run missing a previously seen villager marks it as dead."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    summary1 = _run_with_mocks(db_path)
    assert summary1["births"] == 1
    assert summary1["deaths"] == 0

    summary2 = _run_with_mocks(db_path, villagers=[], beds=[])
    assert summary2["deaths"] == 1
    assert summary2["births"] == 0

    conn = init_db(db_path)
    cur = conn.execute("SELECT presumed_dead FROM villagers")
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["presumed_dead"] == 1
    conn.close()


def test_run_census_bed_claimed_by():
    """Bed at an unmatched position gets claimed_by=None."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    beds = [{"type": "minecraft:home", "pos": [3000, 64, -900], "free_tickets": 0}]
    _run_with_mocks(db_path, beds=beds)

    conn = init_db(db_path)
    cur = conn.execute("SELECT claimed_by FROM beds")
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["claimed_by"] is None
    conn.close()


def test_export_census_json():
    """export_census_json returns a JSON-serializable dict with expected keys."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    _run_with_mocks(db_path, players=["Termiduck"])
    result = census.export_census_json(db_path)
    assert "snapshots" in result
    assert "villagers" in result
    assert len(result["snapshots"]) == 1
    assert len(result["villagers"]) == 1


def test_run_census_homeless_count():
    """Villagers without a home memory are counted as homeless."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    summary = _run_with_mocks(db_path, beds=[])
    assert summary["homeless"] == 1


def test_run_census_zone_classification():
    """Villagers and beds are classified into the correct zones."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Sample villager is at x=3173, z=-755 — only inside a large enough zone
    zones = [
        make_single_zone(center_x=3173, center_z=-755, radius=10, name="zone-a"),
        make_single_zone(center_x=0, center_z=0, radius=10, name="zone-b"),
    ]
    beds = [
        {"type": "minecraft:home", "pos": [3173, 69, -755], "free_tickets": 0},  # inside zone-a
        {"type": "minecraft:home", "pos": [5, 64, 5], "free_tickets": 1},         # inside zone-b
    ]

    summary = _run_with_mocks(db_path, beds=beds, zones=zones)
    assert summary["zones"]["zone-a"]["villagers"] == 1
    assert summary["zones"]["zone-a"]["beds"] == 1
    assert summary["zones"]["zone-b"]["villagers"] == 0
    assert summary["zones"]["zone-b"]["beds"] == 1

    # Check DB has zone column populated
    conn = init_db(db_path)
    cur = conn.execute("SELECT zone FROM villager_states")
    assert cur.fetchone()["zone"] == "zone-a"
    cur = conn.execute("SELECT zone FROM beds ORDER BY pos_x")
    bed_zones = [dict(r)["zone"] for r in cur.fetchall()]
    assert bed_zones == ["zone-b", "zone-a"]
    conn.close()


def test_run_census_unclassified():
    """Villagers outside all zones appear as 'unclassified'."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Tiny zone far from the sample villager (x=3173, z=-755)
    zones = [make_single_zone(center_x=0, center_z=0, radius=10, name="nowhere")]

    summary = _run_with_mocks(db_path, beds=[], zones=zones)
    assert summary["zones"]["nowhere"]["villagers"] == 0
    assert summary["zones"]["unclassified"]["villagers"] == 1


def test_run_census_stores_coverage():
    """Snapshot records which zones were scanned and skipped."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    import json
    from census_parse import parse_entity_line
    zones = [make_single_zone(center_x=3173, center_z=-755, radius=10, name="active")]
    skipped = ["inactive-a", "inactive-b"]
    villagers = [parse_entity_line(SAMPLE_ENTITY_LINE)]

    with (
        patch("census.check_players_online", return_value=[]),
        patch("census.get_entity_files", return_value=[]),
        patch("census.parse_entity_regions", return_value=villagers),
        patch("census.get_poi_files", return_value=[]),
        patch("census.parse_poi_regions", return_value=[]),
    ):
        summary = census.run_census(
            db_path=db_path, zones=zones, poi_regions=TEST_POI_REGIONS,
            skipped_zones=skipped,
        )

    conn = init_db(db_path)
    snap = conn.execute("SELECT zones_scanned, zones_skipped FROM snapshots WHERE id = ?",
                        (summary["snapshot_id"],)).fetchone()
    assert json.loads(snap["zones_scanned"]) == ["active"]
    assert json.loads(snap["zones_skipped"]) == ["inactive-a", "inactive-b"]
    conn.close()


def test_run_census_ingests_villager_events():
    """Plugin events are ingested and stored in villager_events table."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    sample_events = [
        {"type": "death", "timestamp": "2026-04-05T12:35:10Z",
         "uuid": "dead-uuid", "cause": "FALL", "killer": None,
         "x": 3145.0, "y": 63.0, "z": -965.0, "ticks_lived": 48000,
         "message": "Villager hit the ground too hard"},
        {"type": "breed", "timestamp": "2026-04-05T12:34:56Z",
         "child_uuid": "child-uuid", "parent1_uuid": "p1-uuid",
         "parent2_uuid": "p2-uuid", "x": 3150.5, "y": 64.0, "z": -950.2},
    ]

    with (
        patch("census.check_players_online", return_value=[]),
        patch("census.get_entity_files", return_value=[]),
        patch("census.parse_entity_regions", return_value=[]),
        patch("census.get_poi_files", return_value=[]),
        patch("census.parse_poi_regions", return_value=[]),
        patch("census.get_villager_events", return_value=sample_events),
    ):
        summary = census.run_census(
            db_path=db_path,
            zones=TEST_ZONES,
            poi_regions=TEST_POI_REGIONS,
        )

    conn = init_db(db_path)
    cur = conn.execute("SELECT * FROM villager_events WHERE snapshot_id = ?",
                       (summary["snapshot_id"],))
    events = [dict(r) for r in cur.fetchall()]
    assert len(events) == 2
    death = next(e for e in events if e["event_type"] == "death")
    assert death["uuid"] == "dead-uuid"
    assert death["cause"] == "FALL"
    breed = next(e for e in events if e["event_type"] == "breed")
    assert breed["uuid"] == "child-uuid"
    assert breed["parent1_uuid"] == "p1-uuid"
    conn.close()


def test_run_census_uses_plugin_death_cause():
    """Death cause from plugin events is passed to mark_dead."""
    from census_parse import parse_entity_line
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    villager = parse_entity_line(SAMPLE_ENTITY_LINE)
    villager_uuid = villager["uuid"]

    # First run: villager is alive
    _run_with_mocks(db_path, villagers=[villager])

    # Second run: villager gone, plugin reports death cause
    death_events = [
        {"type": "death", "timestamp": "2026-04-05T12:35:10Z",
         "uuid": villager_uuid, "cause": "DROWNING", "killer": None,
         "x": 0, "y": 0, "z": 0, "ticks_lived": 1000, "message": "drowned"},
    ]

    with (
        patch("census.check_players_online", return_value=[]),
        patch("census.get_entity_files", return_value=[]),
        patch("census.parse_entity_regions", return_value=[]),
        patch("census.get_poi_files", return_value=[]),
        patch("census.parse_poi_regions", return_value=[]),
        patch("census.get_villager_events", return_value=death_events),
    ):
        census.run_census(
            db_path=db_path,
            zones=TEST_ZONES,
            poi_regions=TEST_POI_REGIONS,
        )

    conn = init_db(db_path)
    v = conn.execute("SELECT death_cause FROM villagers WHERE uuid = ?",
                     (villager_uuid,)).fetchone()
    assert v["death_cause"] == "DROWNING"
    conn.close()
