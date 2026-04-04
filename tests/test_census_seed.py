"""Tests for census_seed.py — historical seeding from death logs."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from census_seed import parse_death_logs, build_seed_snapshots
from census_db import init_db, get_villager, get_all_snapshots, get_snapshot_villager_uuids


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

SAMPLE_DEATHS = [
    "[19:54:24] [Server thread/INFO]: Villager Villager['Villager'/15678, uuid='d68d9d96-4802-4899-9b8e-bb8709eda5c0', l='ServerLevel[world_new]', x=3145.37, y=63.00, z=-965.30, cpos=[196, -61], tl=59771, v=true] died, message: 'Villager was killed'",
    "[18:32:16] [Server thread/INFO]: Villager Villager['Villager'/214, uuid='0a077d31-a230-41b5-bf50-c74d83892338', l='ServerLevel[world_new]', x=3158.63, y=64.00, z=-917.15, cpos=[197, -58], tl=708, v=true] died, message: 'Villager hit the ground too hard'",
]

SURVIVOR = {
    "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "spawn_reason": "DEFAULT",
    "origin_x": 135.7, "origin_y": 66.0, "origin_z": 223.8,
    "pos_x": 3177.0, "pos_y": 70.0, "pos_z": -763.9,
    "profession": "none", "profession_level": 1, "villager_type": "plains",
    "health": 12.0, "food_level": 0, "xp": 0, "ticks_lived": 3703310,
    "age": 0, "on_ground": 1, "restocks_today": 0,
    "home_x": None, "home_y": None, "home_z": None,
    "job_site_x": None, "job_site_y": None, "job_site_z": None,
    "meeting_point_x": None, "meeting_point_y": None, "meeting_point_z": None,
    "last_slept": None, "last_woken": None, "last_worked": 991884047,
    "last_restock": None, "last_gossip_decay": 1025345203,
    "trades": [], "inventory": [], "gossip": [],
}


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "test_census.db"
    return db_path


# ---------------------------------------------------------------------------
# test_parse_death_logs
# ---------------------------------------------------------------------------

def test_parse_death_logs():
    """2 lines → 2 dicts, check UUIDs correct."""
    results = parse_death_logs(SAMPLE_DEATHS)
    assert len(results) == 2
    uuids = {r["uuid"] for r in results}
    assert "d68d9d96-4802-4899-9b8e-bb8709eda5c0" in uuids
    assert "0a077d31-a230-41b5-bf50-c74d83892338" in uuids


def test_parse_death_logs_filters_non_matching():
    """Lines that don't match should be silently dropped."""
    lines = [
        "This is not a death log line",
        SAMPLE_DEATHS[0],
        "[INFO] Some other server line",
    ]
    results = parse_death_logs(lines)
    assert len(results) == 1
    assert results[0]["uuid"] == "d68d9d96-4802-4899-9b8e-bb8709eda5c0"


def test_parse_death_logs_empty():
    """Empty input → empty list."""
    assert parse_death_logs([]) == []


# ---------------------------------------------------------------------------
# test_build_seed_snapshots
# ---------------------------------------------------------------------------

def test_build_seed_snapshots(tmp_db):
    """Verify 2 snapshots, correct villager counts, dead/alive state."""
    deaths = parse_death_logs(SAMPLE_DEATHS)
    build_seed_snapshots(str(tmp_db), deaths, [SURVIVOR])

    conn = init_db(tmp_db)

    # 2 snapshots created
    snapshots = get_all_snapshots(conn)
    assert len(snapshots) == 2

    pre_snap = snapshots[0]
    post_snap = snapshots[1]

    # Pre-culling: 2026-03-30T18:30:00Z
    assert pre_snap["timestamp"] == "2026-03-30T18:30:00Z"
    # Post-culling: 2026-03-30T19:55:00Z
    assert post_snap["timestamp"] == "2026-03-30T19:55:00Z"

    # Pre-culling has 3 villagers (2 dead + 1 survivor)
    pre_uuids = get_snapshot_villager_uuids(conn, pre_snap["id"])
    assert len(pre_uuids) == 3
    assert "d68d9d96-4802-4899-9b8e-bb8709eda5c0" in pre_uuids
    assert "0a077d31-a230-41b5-bf50-c74d83892338" in pre_uuids
    assert SURVIVOR["uuid"] in pre_uuids

    # Post-culling has 1 (survivor only)
    post_uuids = get_snapshot_villager_uuids(conn, post_snap["id"])
    assert len(post_uuids) == 1
    assert SURVIVOR["uuid"] in post_uuids

    # Dead villagers are marked presumed_dead
    dead1 = get_villager(conn, "d68d9d96-4802-4899-9b8e-bb8709eda5c0")
    assert dead1 is not None
    assert dead1["presumed_dead"] == 1

    dead2 = get_villager(conn, "0a077d31-a230-41b5-bf50-c74d83892338")
    assert dead2 is not None
    assert dead2["presumed_dead"] == 1

    # Survivor is NOT dead
    survivor_row = get_villager(conn, SURVIVOR["uuid"])
    assert survivor_row is not None
    assert survivor_row["presumed_dead"] == 0

    conn.close()


def test_build_seed_snapshots_snapshot_metadata(tmp_db):
    """Verify snapshot area/radius metadata and notes."""
    deaths = parse_death_logs(SAMPLE_DEATHS)
    build_seed_snapshots(str(tmp_db), deaths, [SURVIVOR])

    conn = init_db(tmp_db)
    snapshots = get_all_snapshots(conn)
    pre_snap = snapshots[0]
    post_snap = snapshots[1]

    # Area center and scan_radius
    assert pre_snap["area_center_x"] == 3150
    assert pre_snap["area_center_z"] == -950
    assert pre_snap["scan_radius"] == 300

    assert post_snap["area_center_x"] == 3150
    assert post_snap["area_center_z"] == -950
    assert post_snap["scan_radius"] == 300

    # Notes are set
    assert pre_snap["notes"] is not None
    assert "Reconstructed" in pre_snap["notes"]
    assert post_snap["notes"] is not None
    assert "Reconstructed" in post_snap["notes"]

    # players_online on pre-snap
    assert pre_snap["players_online"] == 1  # ["Termiduck"] → 1

    conn.close()


def test_build_seed_snapshots_dead_position(tmp_db):
    """Dead villager positions come from the death log coordinates."""
    deaths = parse_death_logs(SAMPLE_DEATHS)
    build_seed_snapshots(str(tmp_db), deaths, [SURVIVOR])

    conn = init_db(tmp_db)
    snapshots = get_all_snapshots(conn)
    pre_id = snapshots[0]["id"]

    # Query state for a dead villager
    cur = conn.execute(
        "SELECT pos_x, pos_y, pos_z, ticks_lived FROM villager_states "
        "WHERE snapshot_id=? AND villager_uuid=?",
        (pre_id, "d68d9d96-4802-4899-9b8e-bb8709eda5c0"),
    )
    row = dict(cur.fetchone())
    assert row["pos_x"] == pytest.approx(3145.37)
    assert row["pos_y"] == pytest.approx(63.00)
    assert row["pos_z"] == pytest.approx(-965.30)
    assert row["ticks_lived"] == 59771

    conn.close()


def test_build_seed_snapshots_survivor_uses_origin(tmp_db):
    """Survivor position uses origin coords, not pos coords."""
    deaths = parse_death_logs(SAMPLE_DEATHS)
    build_seed_snapshots(str(tmp_db), deaths, [SURVIVOR])

    conn = init_db(tmp_db)
    snapshots = get_all_snapshots(conn)
    pre_id = snapshots[0]["id"]

    cur = conn.execute(
        "SELECT pos_x, pos_y, pos_z FROM villager_states "
        "WHERE snapshot_id=? AND villager_uuid=?",
        (pre_id, SURVIVOR["uuid"]),
    )
    row = dict(cur.fetchone())
    # Origin coords: 135.7, 66.0, 223.8
    assert row["pos_x"] == pytest.approx(135.7)
    assert row["pos_y"] == pytest.approx(66.0)
    assert row["pos_z"] == pytest.approx(223.8)

    conn.close()
