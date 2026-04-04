import sqlite3
import pytest
from census_db import (
    init_db,
    insert_snapshot,
    insert_villager,
    insert_villager_state,
    insert_trade,
    insert_inventory_item,
    insert_gossip,
    insert_bed,
    insert_bell,
    get_villager,
    get_latest_snapshot,
    mark_dead,
    get_snapshot_villager_uuids,
    get_all_snapshots,
    get_villager_history,
    export_snapshot_json,
    export_all_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_snapshot(conn, **overrides):
    defaults = dict(
        timestamp="2026-04-03T12:00:00",
        players_online=2,
        area_center_x=0,
        area_center_z=0,
        scan_radius=64,
        villager_count=3,
        bed_count=3,
        notes=None,
    )
    defaults.update(overrides)
    return insert_snapshot(conn, **defaults)


def make_villager(conn, snap_id, uuid="aaaa-1111", **overrides):
    defaults = dict(
        uuid=uuid,
        first_seen_snapshot=snap_id,
        last_seen_snapshot=snap_id,
        spawn_reason="NATURAL",
        origin_x=10.0,
        origin_y=64.0,
        origin_z=20.0,
    )
    defaults.update(overrides)
    return insert_villager(conn, **defaults)


def make_villager_state(conn, snap_id, uuid="aaaa-1111", **overrides):
    defaults = dict(
        snapshot_id=snap_id,
        villager_uuid=uuid,
        pos_x=10.0,
        pos_y=64.0,
        pos_z=20.0,
        health=20.0,
        food_level=100,
        profession="FARMER",
        profession_level=1,
        villager_type="PLAINS",
        xp=0,
        ticks_lived=1000,
        age=0,
        home_x=10.0,
        home_y=64.0,
        home_z=20.0,
        job_site_x=None,
        job_site_y=None,
        job_site_z=None,
        meeting_point_x=None,
        meeting_point_y=None,
        meeting_point_z=None,
        last_slept=None,
        last_woken=None,
        last_worked=None,
        last_restock=None,
        restocks_today=0,
        on_ground=1,
        last_gossip_decay=None,
    )
    defaults.update(overrides)
    return insert_villager_state(conn, **defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_init_db_creates_all_tables(tmp_path):
    conn = init_db(tmp_path / "test.db")
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row["name"] for row in cursor.fetchall()}
    expected = {
        "snapshots",
        "villagers",
        "villager_states",
        "villager_trades",
        "villager_inventory",
        "villager_gossip",
        "beds",
    }
    assert expected <= tables


def test_insert_snapshot(tmp_path):
    conn = init_db(tmp_path / "test.db")
    id1 = make_snapshot(conn, timestamp="2026-04-03T10:00:00")
    id2 = make_snapshot(conn, timestamp="2026-04-03T11:00:00")
    assert id1 == 1
    assert id2 == 2


def test_insert_and_get_villager(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id, uuid="bbbb-2222")

    v = get_villager(conn, "bbbb-2222")
    assert v is not None
    assert v["uuid"] == "bbbb-2222"
    assert v["spawn_reason"] == "NATURAL"
    assert v["presumed_dead"] == 0

    assert get_villager(conn, "nonexistent") is None


def test_insert_villager_upsert_updates_last_seen(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap1 = make_snapshot(conn, timestamp="2026-04-03T10:00:00")
    snap2 = make_snapshot(conn, timestamp="2026-04-03T11:00:00")

    make_villager(conn, snap1, uuid="cccc-3333")
    # Second insert with same UUID — should upsert, updating last_seen_snapshot
    insert_villager(
        conn,
        uuid="cccc-3333",
        first_seen_snapshot=snap1,
        last_seen_snapshot=snap2,
        spawn_reason="NATURAL",
        origin_x=10.0,
        origin_y=64.0,
        origin_z=20.0,
    )
    v = get_villager(conn, "cccc-3333")
    assert v["last_seen_snapshot"] == snap2


def test_insert_villager_state_unique_constraint(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id)
    make_villager_state(conn, snap_id)

    with pytest.raises(sqlite3.IntegrityError):
        make_villager_state(conn, snap_id)  # duplicate (snapshot_id, villager_uuid)


def test_mark_dead(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id, uuid="dddd-4444")

    v = get_villager(conn, "dddd-4444")
    assert v["presumed_dead"] == 0

    mark_dead(conn, "dddd-4444", snap_id)
    v = get_villager(conn, "dddd-4444")
    assert v["presumed_dead"] == 1
    assert v["death_snapshot"] == snap_id


def test_get_latest_snapshot_empty(tmp_path):
    conn = init_db(tmp_path / "test.db")
    assert get_latest_snapshot(conn) is None


def test_get_latest_snapshot_returns_most_recent(tmp_path):
    conn = init_db(tmp_path / "test.db")
    make_snapshot(conn, timestamp="2026-04-01T10:00:00")
    make_snapshot(conn, timestamp="2026-04-03T10:00:00")
    make_snapshot(conn, timestamp="2026-04-02T10:00:00")

    snap = get_latest_snapshot(conn)
    assert snap is not None
    assert snap["timestamp"] == "2026-04-03T10:00:00"


def test_insert_trade(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id)
    make_villager_state(conn, snap_id)

    insert_trade(
        conn,
        snapshot_id=snap_id,
        villager_uuid="aaaa-1111",
        slot=0,
        buy_item="WHEAT",
        buy_count=20,
        buy_b_item=None,
        buy_b_count=None,
        sell_item="EMERALD",
        sell_count=1,
        price_multiplier=0.05,
        max_uses=12,
        xp=2,
    )

    cursor = conn.execute(
        "SELECT * FROM villager_trades WHERE villager_uuid='aaaa-1111'"
    )
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["buy_item"] == "WHEAT"
    assert rows[0]["sell_item"] == "EMERALD"


def test_insert_bed_with_claimed_by(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id, uuid="eeee-5555")

    insert_bed(
        conn,
        snapshot_id=snap_id,
        pos_x=5,
        pos_y=64,
        pos_z=10,
        free_tickets=3,
        claimed_by="eeee-5555",
    )

    cursor = conn.execute("SELECT * FROM beds WHERE snapshot_id=?", (snap_id,))
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["claimed_by"] == "eeee-5555"
    assert rows[0]["free_tickets"] == 3


def test_insert_bed_unique_constraint(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)

    insert_bed(conn, snapshot_id=snap_id, pos_x=5, pos_y=64, pos_z=10, free_tickets=3, claimed_by=None)
    with pytest.raises(sqlite3.IntegrityError):
        insert_bed(conn, snapshot_id=snap_id, pos_x=5, pos_y=64, pos_z=10, free_tickets=3, claimed_by=None)


def test_get_snapshot_villager_uuids(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id, uuid="u1")
    make_villager(conn, snap_id, uuid="u2")
    make_villager_state(conn, snap_id, uuid="u1")
    make_villager_state(conn, snap_id, uuid="u2")

    uuids = get_snapshot_villager_uuids(conn, snap_id)
    assert uuids == {"u1", "u2"}


def test_get_all_snapshots(tmp_path):
    conn = init_db(tmp_path / "test.db")
    make_snapshot(conn, timestamp="2026-04-01T10:00:00")
    make_snapshot(conn, timestamp="2026-04-02T10:00:00")

    snaps = get_all_snapshots(conn)
    assert len(snaps) == 2
    assert snaps[0]["timestamp"] == "2026-04-01T10:00:00"
    assert snaps[1]["timestamp"] == "2026-04-02T10:00:00"


def test_get_villager_history(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap1 = make_snapshot(conn, timestamp="2026-04-01T10:00:00")
    snap2 = make_snapshot(conn, timestamp="2026-04-02T10:00:00")

    make_villager(conn, snap1, uuid="ff-01", last_seen_snapshot=snap2)
    make_villager_state(conn, snap1, uuid="ff-01", profession="NONE")
    make_villager_state(conn, snap2, uuid="ff-01", profession="FARMER")

    history = get_villager_history(conn, "ff-01")
    assert len(history) == 2
    assert history[0]["profession"] == "NONE"
    assert history[1]["profession"] == "FARMER"
    assert "timestamp" in history[0]


def test_export_snapshot_json(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id)
    make_villager_state(conn, snap_id)
    insert_trade(
        conn,
        snapshot_id=snap_id,
        villager_uuid="aaaa-1111",
        slot=0,
        buy_item="WHEAT",
        buy_count=20,
        buy_b_item=None,
        buy_b_count=None,
        sell_item="EMERALD",
        sell_count=1,
        price_multiplier=0.05,
        max_uses=12,
        xp=2,
    )
    insert_bed(conn, snapshot_id=snap_id, pos_x=5, pos_y=64, pos_z=10, free_tickets=3, claimed_by=None)

    result = export_snapshot_json(conn, snap_id)
    assert result["snapshot"]["id"] == snap_id
    assert len(result["villagers"]) == 1
    assert len(result["villagers"][0]["trades"]) == 1
    assert len(result["beds"]) == 1


def test_insert_bell(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn, bell_count=2)
    bell_id = insert_bell(
        conn, snapshot_id=snap_id,
        pos_x=110, pos_y=65, pos_z=210,
        free_tickets=30, villager_count=3, zone="north-village",
    )
    assert bell_id is not None

    row = conn.execute("SELECT * FROM bells WHERE id = ?", (bell_id,)).fetchone()
    assert row["pos_x"] == 110
    assert row["free_tickets"] == 30
    assert row["villager_count"] == 3
    assert row["zone"] == "north-village"

    snap = conn.execute("SELECT bell_count FROM snapshots WHERE id = ?", (snap_id,)).fetchone()
    assert snap["bell_count"] == 2


def test_insert_bell_unique_constraint(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    insert_bell(conn, snapshot_id=snap_id, pos_x=5, pos_y=64, pos_z=10, free_tickets=3)
    with pytest.raises(sqlite3.IntegrityError):
        insert_bell(conn, snapshot_id=snap_id, pos_x=5, pos_y=64, pos_z=10, free_tickets=3)


def test_export_all_json(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap1 = make_snapshot(conn, timestamp="2026-04-01T10:00:00")
    snap2 = make_snapshot(conn, timestamp="2026-04-02T10:00:00")

    result = export_all_json(conn)
    assert len(result["snapshots"]) == 2
    assert "villagers" in result
