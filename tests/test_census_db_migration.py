"""Tests for DB schema migration (adding zone columns to existing databases)."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from census_db import init_db, insert_bed, insert_snapshot, insert_villager, insert_villager_state


# Old schema without zone columns
_OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT    NOT NULL,
    players_online   INTEGER NOT NULL DEFAULT 0,
    area_center_x    REAL    NOT NULL DEFAULT 0,
    area_center_z    REAL    NOT NULL DEFAULT 0,
    scan_radius      INTEGER NOT NULL DEFAULT 64,
    villager_count   INTEGER NOT NULL DEFAULT 0,
    bed_count        INTEGER NOT NULL DEFAULT 0,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS villagers (
    uuid                TEXT    PRIMARY KEY,
    first_seen_snapshot INTEGER NOT NULL REFERENCES snapshots(id),
    last_seen_snapshot  INTEGER NOT NULL REFERENCES snapshots(id),
    spawn_reason        TEXT,
    origin_x            REAL,
    origin_y            REAL,
    origin_z            REAL,
    presumed_dead       INTEGER NOT NULL DEFAULT 0,
    death_snapshot      INTEGER REFERENCES snapshots(id)
);

CREATE TABLE IF NOT EXISTS villager_states (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id         INTEGER NOT NULL REFERENCES snapshots(id),
    villager_uuid       TEXT    NOT NULL REFERENCES villagers(uuid),
    pos_x               REAL,
    pos_y               REAL,
    pos_z               REAL,
    health              REAL,
    food_level          INTEGER,
    profession          TEXT,
    profession_level    INTEGER,
    villager_type       TEXT,
    xp                  INTEGER,
    ticks_lived         INTEGER,
    age                 INTEGER,
    home_x              REAL,
    home_y              REAL,
    home_z              REAL,
    job_site_x          REAL,
    job_site_y          REAL,
    job_site_z          REAL,
    meeting_point_x     REAL,
    meeting_point_y     REAL,
    meeting_point_z     REAL,
    last_slept          TEXT,
    last_woken          TEXT,
    last_worked         TEXT,
    last_restock        TEXT,
    restocks_today      INTEGER,
    on_ground           INTEGER,
    last_gossip_decay   TEXT,
    UNIQUE(snapshot_id, villager_uuid)
);

CREATE TABLE IF NOT EXISTS villager_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id     INTEGER NOT NULL REFERENCES snapshots(id),
    villager_uuid   TEXT    NOT NULL REFERENCES villagers(uuid),
    slot            INTEGER NOT NULL,
    buy_item        TEXT,
    buy_count       INTEGER,
    buy_b_item      TEXT,
    buy_b_count     INTEGER,
    sell_item       TEXT,
    sell_count      INTEGER,
    price_multiplier REAL,
    max_uses        INTEGER,
    xp              INTEGER
);

CREATE TABLE IF NOT EXISTS villager_inventory (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id   INTEGER NOT NULL REFERENCES snapshots(id),
    villager_uuid TEXT    NOT NULL REFERENCES villagers(uuid),
    item          TEXT    NOT NULL,
    count         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS villager_gossip (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id   INTEGER NOT NULL REFERENCES snapshots(id),
    villager_uuid TEXT    NOT NULL REFERENCES villagers(uuid),
    gossip_type   TEXT    NOT NULL,
    target_uuid   TEXT,
    value         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS beds (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id   INTEGER NOT NULL REFERENCES snapshots(id),
    pos_x         INTEGER NOT NULL,
    pos_y         INTEGER NOT NULL,
    pos_z         INTEGER NOT NULL,
    free_tickets  INTEGER NOT NULL DEFAULT 0,
    claimed_by    TEXT    REFERENCES villagers(uuid),
    UNIQUE(snapshot_id, pos_x, pos_y, pos_z)
);
"""


def _create_old_db(path):
    """Create a DB with the old schema (no zone columns) and seed some data."""
    conn = sqlite3.connect(str(path))
    conn.executescript(_OLD_SCHEMA)
    conn.execute(
        "INSERT INTO snapshots (timestamp, players_online, villager_count, bed_count) "
        "VALUES ('2026-03-30T00:00:00Z', 1, 5, 3)"
    )
    conn.execute(
        "INSERT INTO villagers (uuid, first_seen_snapshot, last_seen_snapshot) "
        "VALUES ('abc-123', 1, 1)"
    )
    conn.execute(
        "INSERT INTO villager_states (snapshot_id, villager_uuid, pos_x, pos_y, pos_z) "
        "VALUES (1, 'abc-123', 100.0, 64.0, -200.0)"
    )
    conn.execute(
        "INSERT INTO beds (snapshot_id, pos_x, pos_y, pos_z, free_tickets) "
        "VALUES (1, 100, 64, -200, 0)"
    )
    conn.commit()
    conn.close()


def _get_columns(conn, table):
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def test_migrate_adds_zone_to_villager_states():
    """Opening an old DB with init_db adds the zone column to villager_states."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    _create_old_db(db_path)

    # Verify old schema has no zone column
    conn = sqlite3.connect(db_path)
    assert "zone" not in _get_columns(conn, "villager_states")
    conn.close()

    # init_db should migrate
    conn = init_db(db_path)
    assert "zone" in _get_columns(conn, "villager_states")

    # Old data still intact
    cur = conn.execute("SELECT pos_x FROM villager_states WHERE villager_uuid = 'abc-123'")
    assert cur.fetchone()[0] == 100.0

    # zone is NULL for old rows
    cur = conn.execute("SELECT zone FROM villager_states WHERE villager_uuid = 'abc-123'")
    assert cur.fetchone()[0] is None

    conn.close()


def test_migrate_adds_zone_to_beds():
    """Opening an old DB with init_db adds the zone column to beds."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    _create_old_db(db_path)

    conn = sqlite3.connect(db_path)
    assert "zone" not in _get_columns(conn, "beds")
    conn.close()

    conn = init_db(db_path)
    assert "zone" in _get_columns(conn, "beds")

    cur = conn.execute("SELECT zone FROM beds")
    assert cur.fetchone()[0] is None

    conn.close()


def test_migrate_is_idempotent():
    """Running init_db twice on a migrated DB doesn't fail."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    _create_old_db(db_path)

    conn1 = init_db(db_path)
    conn1.close()

    # Second call should not raise
    conn2 = init_db(db_path)
    assert "zone" in _get_columns(conn2, "villager_states")
    assert "zone" in _get_columns(conn2, "beds")
    conn2.close()


def test_migrate_adds_entity_mtimes_column():
    """Migration adds entity_mtimes TEXT column to census_runs."""
    conn = init_db(":memory:")
    cur = conn.execute("PRAGMA table_info(census_runs)")
    cols = {row[1] for row in cur.fetchall()}
    assert "entity_mtimes" in cols
    conn.close()


def test_new_rows_can_use_zone_after_migration():
    """After migration, new inserts can set the zone column."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    _create_old_db(db_path)
    conn = init_db(db_path)

    # Insert new state with zone
    insert_villager(conn, uuid="new-456", first_seen_snapshot=1,
                    last_seen_snapshot=1, spawn_reason="BREEDING",
                    origin_x=0, origin_y=0, origin_z=0)
    insert_villager_state(
        conn, snapshot_id=1, villager_uuid="new-456",
        pos_x=50, pos_y=64, pos_z=-100, health=20, food_level=0,
        profession="farmer", profession_level=1, villager_type="plains",
        xp=0, ticks_lived=1000, age=0,
        home_x=50, home_y=64, home_z=-100,
        job_site_x=None, job_site_y=None, job_site_z=None,
        meeting_point_x=None, meeting_point_y=None, meeting_point_z=None,
        last_slept=None, last_woken=None, last_worked=None,
        last_restock=None, restocks_today=None, on_ground=1,
        last_gossip_decay=None, zone="old-city",
    )

    cur = conn.execute("SELECT zone FROM villager_states WHERE villager_uuid = 'new-456'")
    assert cur.fetchone()[0] == "old-city"

    # Insert new bed with zone
    insert_bed(conn, snapshot_id=1, pos_x=50, pos_y=64, pos_z=-101,
               free_tickets=0, claimed_by="new-456", zone="old-city")

    cur = conn.execute("SELECT zone FROM beds WHERE pos_z = -101")
    assert cur.fetchone()[0] == "old-city"

    conn.close()
