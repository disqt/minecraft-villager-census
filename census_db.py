"""
census_db.py — SQLite data access layer for the villager census system.

All insert functions use keyword-only arguments and call conn.commit() after
each write. The connection is configured with row_factory=sqlite3.Row so rows
can be accessed as dicts.
"""

import sqlite3
from pathlib import Path


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT    NOT NULL,
    players_online   INTEGER NOT NULL DEFAULT 0,
    area_center_x    REAL    NOT NULL DEFAULT 0,
    area_center_z    REAL    NOT NULL DEFAULT 0,
    scan_radius      INTEGER NOT NULL DEFAULT 64,
    villager_count   INTEGER NOT NULL DEFAULT 0,
    bed_count        INTEGER NOT NULL DEFAULT 0,
    bell_count       INTEGER NOT NULL DEFAULT 0,
    notes            TEXT,
    zones_scanned    TEXT,
    zones_skipped    TEXT
);

CREATE TABLE IF NOT EXISTS census_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    reason        TEXT,
    snapshot_id   INTEGER REFERENCES snapshots(id)
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
    death_snapshot      INTEGER REFERENCES snapshots(id),
    death_cause         TEXT,
    status              TEXT    NOT NULL DEFAULT 'alive',
    missing_since       INTEGER REFERENCES snapshots(id)
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
    zone                TEXT,
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
    zone          TEXT,
    UNIQUE(snapshot_id, pos_x, pos_y, pos_z)
);

CREATE TABLE IF NOT EXISTS bells (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id     INTEGER NOT NULL REFERENCES snapshots(id),
    pos_x           INTEGER NOT NULL,
    pos_y           INTEGER NOT NULL,
    pos_z           INTEGER NOT NULL,
    free_tickets    INTEGER NOT NULL DEFAULT 0,
    villager_count  INTEGER NOT NULL DEFAULT 0,
    zone            TEXT,
    UNIQUE(snapshot_id, pos_x, pos_y, pos_z)
);

CREATE TABLE IF NOT EXISTS villager_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    uuid         TEXT NOT NULL,
    parent1_uuid TEXT,
    parent2_uuid TEXT,
    cause        TEXT,
    killer       TEXT,
    message      TEXT,
    pos_x        REAL,
    pos_y        REAL,
    pos_z        REAL,
    ticks_lived  INTEGER,
    snapshot_id  INTEGER REFERENCES snapshots(id)
);
"""


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_db(db_path):
    """Create all tables and return a connection with row_factory=sqlite3.Row."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn):
    """Add columns and tables introduced after initial schema."""
    cur = conn.execute("PRAGMA table_info(villager_states)")
    cols = {row[1] for row in cur.fetchall()}
    if "zone" not in cols:
        conn.execute("ALTER TABLE villager_states ADD COLUMN zone TEXT")

    cur = conn.execute("PRAGMA table_info(beds)")
    cols = {row[1] for row in cur.fetchall()}
    if "zone" not in cols:
        conn.execute("ALTER TABLE beds ADD COLUMN zone TEXT")

    cur = conn.execute("PRAGMA table_info(census_runs)")
    cols = {row[1] for row in cur.fetchall()}
    if "entity_mtimes" not in cols:
        conn.execute("ALTER TABLE census_runs ADD COLUMN entity_mtimes TEXT")

    cur = conn.execute("PRAGMA table_info(snapshots)")
    cols = {row[1] for row in cur.fetchall()}
    if "zones_scanned" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN zones_scanned TEXT")
        conn.execute("ALTER TABLE snapshots ADD COLUMN zones_skipped TEXT")
    if "bell_count" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN bell_count INTEGER NOT NULL DEFAULT 0")

    cur = conn.execute("PRAGMA table_info(villagers)")
    cols = {row[1] for row in cur.fetchall()}
    if "death_cause" not in cols:
        conn.execute("ALTER TABLE villagers ADD COLUMN death_cause TEXT")

    cur = conn.execute("PRAGMA table_info(villagers)")
    cols = {row[1] for row in cur.fetchall()}
    if "status" not in cols:
        conn.execute("ALTER TABLE villagers ADD COLUMN status TEXT NOT NULL DEFAULT 'alive'")
        conn.execute("ALTER TABLE villagers ADD COLUMN missing_since INTEGER REFERENCES snapshots(id)")
        conn.execute("UPDATE villagers SET status = 'dead' WHERE presumed_dead = 1 AND death_cause IS NOT NULL")
        conn.execute("UPDATE villagers SET status = 'missing' WHERE presumed_dead = 1 AND death_cause IS NULL")


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def insert_snapshot(conn, *, timestamp, players_online, area_center_x,
                    area_center_z, scan_radius, villager_count, bed_count,
                    bell_count=0, notes, zones_scanned=None, zones_skipped=None):
    """Insert a snapshot row and return its lastrowid."""
    cur = conn.execute(
        """
        INSERT INTO snapshots
            (timestamp, players_online, area_center_x, area_center_z,
             scan_radius, villager_count, bed_count, bell_count, notes,
             zones_scanned, zones_skipped)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (timestamp, players_online, area_center_x, area_center_z,
         scan_radius, villager_count, bed_count, bell_count, notes,
         zones_scanned, zones_skipped),
    )
    conn.commit()
    return cur.lastrowid


def insert_census_run(conn, *, timestamp, status, reason=None, snapshot_id=None, entity_mtimes=None):
    """Log a census run attempt. Status: 'completed', 'skipped_no_players', 'skipped_no_chunks'.

    entity_mtimes: JSON-encoded dict of entity .mca file paths to mtime strings,
    used as a noop gate to skip scans when no entity files have changed.
    """
    cur = conn.execute(
        """
        INSERT INTO census_runs (timestamp, status, reason, snapshot_id, entity_mtimes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (timestamp, status, reason, snapshot_id, entity_mtimes),
    )
    conn.commit()
    return cur.lastrowid


def insert_villager(conn, *, uuid, first_seen_snapshot, last_seen_snapshot,
                    spawn_reason, origin_x, origin_y, origin_z):
    """Upsert a villager row; on conflict update last_seen_snapshot."""
    cur = conn.execute(
        """
        INSERT INTO villagers
            (uuid, first_seen_snapshot, last_seen_snapshot,
             spawn_reason, origin_x, origin_y, origin_z)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(uuid) DO UPDATE SET
            last_seen_snapshot = excluded.last_seen_snapshot
        """,
        (uuid, first_seen_snapshot, last_seen_snapshot,
         spawn_reason, origin_x, origin_y, origin_z),
    )
    conn.commit()
    return cur.lastrowid


def insert_villager_state(conn, *, snapshot_id, villager_uuid, pos_x, pos_y,
                          pos_z, health, food_level, profession,
                          profession_level, villager_type, xp, ticks_lived,
                          age, home_x, home_y, home_z, job_site_x, job_site_y,
                          job_site_z, meeting_point_x, meeting_point_y,
                          meeting_point_z, last_slept, last_woken,
                          last_worked, last_restock, restocks_today,
                          on_ground, last_gossip_decay, zone=None):
    """Insert a villager state row. UNIQUE(snapshot_id, villager_uuid)."""
    cur = conn.execute(
        """
        INSERT INTO villager_states
            (snapshot_id, villager_uuid, pos_x, pos_y, pos_z, health,
             food_level, profession, profession_level, villager_type, xp,
             ticks_lived, age, home_x, home_y, home_z, job_site_x,
             job_site_y, job_site_z, meeting_point_x, meeting_point_y,
             meeting_point_z, last_slept, last_woken, last_worked,
             last_restock, restocks_today, on_ground, last_gossip_decay,
             zone)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (snapshot_id, villager_uuid, pos_x, pos_y, pos_z, health,
         food_level, profession, profession_level, villager_type, xp,
         ticks_lived, age, home_x, home_y, home_z, job_site_x,
         job_site_y, job_site_z, meeting_point_x, meeting_point_y,
         meeting_point_z, last_slept, last_woken, last_worked,
         last_restock, restocks_today, on_ground, last_gossip_decay,
         zone),
    )
    conn.commit()
    return cur.lastrowid


def insert_trade(conn, *, snapshot_id, villager_uuid, slot, buy_item,
                 buy_count, buy_b_item, buy_b_count, sell_item, sell_count,
                 price_multiplier, max_uses, xp):
    """Insert a trade row."""
    cur = conn.execute(
        """
        INSERT INTO villager_trades
            (snapshot_id, villager_uuid, slot, buy_item, buy_count,
             buy_b_item, buy_b_count, sell_item, sell_count,
             price_multiplier, max_uses, xp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (snapshot_id, villager_uuid, slot, buy_item, buy_count,
         buy_b_item, buy_b_count, sell_item, sell_count,
         price_multiplier, max_uses, xp),
    )
    conn.commit()
    return cur.lastrowid


def insert_inventory_item(conn, *, snapshot_id, villager_uuid, item, count):
    """Insert an inventory item row."""
    cur = conn.execute(
        """
        INSERT INTO villager_inventory (snapshot_id, villager_uuid, item, count)
        VALUES (?, ?, ?, ?)
        """,
        (snapshot_id, villager_uuid, item, count),
    )
    conn.commit()
    return cur.lastrowid


def insert_gossip(conn, *, snapshot_id, villager_uuid, gossip_type,
                  target_uuid, value):
    """Insert a gossip row."""
    cur = conn.execute(
        """
        INSERT INTO villager_gossip
            (snapshot_id, villager_uuid, gossip_type, target_uuid, value)
        VALUES (?, ?, ?, ?, ?)
        """,
        (snapshot_id, villager_uuid, gossip_type, target_uuid, value),
    )
    conn.commit()
    return cur.lastrowid


def insert_bed(conn, *, snapshot_id, pos_x, pos_y, pos_z, free_tickets,
               claimed_by, zone=None):
    """Insert a bed row. UNIQUE(snapshot_id, pos_x, pos_y, pos_z)."""
    cur = conn.execute(
        """
        INSERT INTO beds (snapshot_id, pos_x, pos_y, pos_z, free_tickets, claimed_by, zone)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (snapshot_id, pos_x, pos_y, pos_z, free_tickets, claimed_by, zone),
    )
    conn.commit()
    return cur.lastrowid


def insert_bell(conn, *, snapshot_id, pos_x, pos_y, pos_z, free_tickets,
                villager_count=0, zone=None):
    """Insert a bell row. UNIQUE(snapshot_id, pos_x, pos_y, pos_z)."""
    cur = conn.execute(
        """
        INSERT INTO bells (snapshot_id, pos_x, pos_y, pos_z, free_tickets, villager_count, zone)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (snapshot_id, pos_x, pos_y, pos_z, free_tickets, villager_count, zone),
    )
    conn.commit()
    return cur.lastrowid


def insert_villager_event(conn, *, event_type, timestamp, uuid,
                          parent1_uuid=None, parent2_uuid=None,
                          cause=None, killer=None, message=None,
                          pos_x=None, pos_y=None, pos_z=None,
                          ticks_lived=None, snapshot_id=None):
    """Insert a villager event (breed or death)."""
    cur = conn.execute(
        """
        INSERT INTO villager_events
            (event_type, timestamp, uuid, parent1_uuid, parent2_uuid,
             cause, killer, message, pos_x, pos_y, pos_z, ticks_lived,
             snapshot_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (event_type, timestamp, uuid, parent1_uuid, parent2_uuid,
         cause, killer, message, pos_x, pos_y, pos_z, ticks_lived,
         snapshot_id),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_villager(conn, uuid):
    """Return a villager row as dict, or None if not found."""
    cur = conn.execute("SELECT * FROM villagers WHERE uuid = ?", (uuid,))
    return _row_to_dict(cur.fetchone())


def get_latest_snapshot(conn):
    """Return the most recent snapshot as dict, or None if table is empty."""
    cur = conn.execute(
        "SELECT * FROM snapshots ORDER BY timestamp DESC, id DESC LIMIT 1"
    )
    return _row_to_dict(cur.fetchone())


def mark_dead(conn, uuid, death_snapshot, death_cause=None):
    """Mark a villager as confirmed dead."""
    conn.execute("""
        UPDATE villagers
        SET status = 'dead', presumed_dead = 1,
            death_snapshot = ?, death_cause = ?,
            missing_since = NULL
        WHERE uuid = ?
    """, (death_snapshot, death_cause, uuid))
    conn.commit()


def mark_missing(conn, uuid, snapshot_id):
    """Mark a villager as missing (disappeared without a death event)."""
    conn.execute("""
        UPDATE villagers
        SET status = 'missing', missing_since = ?
        WHERE uuid = ? AND status = 'alive'
    """, (snapshot_id, uuid))
    conn.commit()


def mark_alive(conn, uuid):
    """Mark a previously missing villager as alive again."""
    conn.execute("""
        UPDATE villagers
        SET status = 'alive', missing_since = NULL
        WHERE uuid = ? AND status = 'missing'
    """, (uuid,))
    conn.commit()


def get_missing_uuids(conn):
    """Return set of UUIDs currently in 'missing' status."""
    cur = conn.execute("SELECT uuid FROM villagers WHERE status = 'missing'")
    return {row['uuid'] for row in cur.fetchall()}


def backfill_death_causes(conn, log_deaths):
    """Update dead villagers that have no death_cause with log-parsed messages.

    log_deaths: list of dicts from parse_death_log, each with 'uuid' and 'message'.
    Returns the number of villagers updated.
    """
    cause_map = {d["uuid"]: d["message"] for d in log_deaths}
    cur = conn.execute(
        "SELECT uuid FROM villagers WHERE presumed_dead = 1 AND death_cause IS NULL"
    )
    missing = [row["uuid"] for row in cur.fetchall()]
    updated = 0
    for uuid in missing:
        if uuid in cause_map:
            conn.execute(
                "UPDATE villagers SET death_cause = ? WHERE uuid = ?",
                (cause_map[uuid], uuid),
            )
            updated += 1
    if updated:
        conn.commit()
    return updated


def get_villager_events_for_snapshot(conn, snapshot_id):
    """Return all villager events for a given snapshot."""
    cur = conn.execute(
        "SELECT * FROM villager_events WHERE snapshot_id = ?",
        (snapshot_id,),
    )
    return [dict(row) for row in cur.fetchall()]


def get_snapshot_villager_uuids(conn, snapshot_id):
    """Return the set of villager UUIDs recorded in a snapshot."""
    cur = conn.execute(
        "SELECT villager_uuid FROM villager_states WHERE snapshot_id = ?",
        (snapshot_id,),
    )
    return {row["villager_uuid"] for row in cur.fetchall()}


def get_all_snapshots(conn):
    """Return all snapshots as a list of dicts, ordered by id ascending."""
    cur = conn.execute("SELECT * FROM snapshots ORDER BY id ASC")
    return [dict(row) for row in cur.fetchall()]


def get_villager_history(conn, uuid):
    """Return all state rows for a villager, joined with snapshot timestamp."""
    cur = conn.execute(
        """
        SELECT vs.*, s.timestamp
        FROM villager_states vs
        JOIN snapshots s ON s.id = vs.snapshot_id
        WHERE vs.villager_uuid = ?
        ORDER BY s.timestamp ASC, vs.snapshot_id ASC
        """,
        (uuid,),
    )
    return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _get_snapshot_dict(conn, snapshot_id):
    cur = conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,))
    return _row_to_dict(cur.fetchone())


def _get_villager_states_for_snapshot(conn, snapshot_id):
    cur = conn.execute(
        "SELECT * FROM villager_states WHERE snapshot_id = ?", (snapshot_id,)
    )
    return [dict(row) for row in cur.fetchall()]


def _get_trades_for_snapshot_villager(conn, snapshot_id, villager_uuid):
    cur = conn.execute(
        "SELECT * FROM villager_trades WHERE snapshot_id = ? AND villager_uuid = ?",
        (snapshot_id, villager_uuid),
    )
    return [dict(row) for row in cur.fetchall()]


def _get_inventory_for_snapshot_villager(conn, snapshot_id, villager_uuid):
    cur = conn.execute(
        "SELECT * FROM villager_inventory WHERE snapshot_id = ? AND villager_uuid = ?",
        (snapshot_id, villager_uuid),
    )
    return [dict(row) for row in cur.fetchall()]


def _get_gossip_for_snapshot_villager(conn, snapshot_id, villager_uuid):
    cur = conn.execute(
        "SELECT * FROM villager_gossip WHERE snapshot_id = ? AND villager_uuid = ?",
        (snapshot_id, villager_uuid),
    )
    return [dict(row) for row in cur.fetchall()]


def _get_beds_for_snapshot(conn, snapshot_id):
    cur = conn.execute(
        "SELECT * FROM beds WHERE snapshot_id = ?", (snapshot_id,)
    )
    return [dict(row) for row in cur.fetchall()]


def _get_bells_for_snapshot(conn, snapshot_id):
    cur = conn.execute(
        "SELECT * FROM bells WHERE snapshot_id = ?", (snapshot_id,)
    )
    return [dict(row) for row in cur.fetchall()]


def export_snapshot_json(conn, snapshot_id):
    """Return a full snapshot as a JSON-serializable dict."""
    snapshot = _get_snapshot_dict(conn, snapshot_id)
    states = _get_villager_states_for_snapshot(conn, snapshot_id)
    villagers_out = []
    for state in states:
        uuid = state["villager_uuid"]
        villagers_out.append({
            "state": state,
            "villager": get_villager(conn, uuid),
            "trades": _get_trades_for_snapshot_villager(conn, snapshot_id, uuid),
            "inventory": _get_inventory_for_snapshot_villager(conn, snapshot_id, uuid),
            "gossip": _get_gossip_for_snapshot_villager(conn, snapshot_id, uuid),
        })
    return {
        "snapshot": snapshot,
        "villagers": villagers_out,
        "beds": _get_beds_for_snapshot(conn, snapshot_id),
        "bells": _get_bells_for_snapshot(conn, snapshot_id),
    }


def export_all_json(conn):
    """Return the entire database as a JSON-serializable dict."""
    snapshots = get_all_snapshots(conn)
    cur = conn.execute("SELECT * FROM villagers ORDER BY uuid")
    villagers = [dict(row) for row in cur.fetchall()]
    return {
        "snapshots": [
            export_snapshot_json(conn, s["id"]) for s in snapshots
        ],
        "villagers": villagers,
    }
