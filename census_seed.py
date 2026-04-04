"""census_seed.py — Historical seeding from culling death logs.

Seeds the SQLite database with two reconstructed snapshots from the March 30
Great Culling event, using death log lines and current villager data to
reconstruct the pre- and post-culling populations.
"""

from census_collect import parse_death_log
from census_db import (
    init_db,
    insert_snapshot,
    insert_villager,
    insert_villager_state,
    mark_dead,
)


# ---------------------------------------------------------------------------
# Snapshot constants for the March 30 culling event
# ---------------------------------------------------------------------------

_PRE_CULLING_TS = "2026-03-30T18:30:00Z"
_POST_CULLING_TS = "2026-03-30T19:55:00Z"
_AREA_CENTER_X = 3150
_AREA_CENTER_Z = -950
_SCAN_RADIUS = 300
_PLAYERS_ONLINE = ["Termiduck"]

_PRE_NOTES = (
    "Reconstructed from death logs. Partial data — only UUIDs and positions known."
)
_POST_NOTES = (
    "Reconstructed. Survivors inferred from current census DEFAULT villagers"
    " + death log subtraction."
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_death_logs(lines):
    """Parse a list of death log line strings.

    Calls parse_death_log on each line and returns a list of parsed dicts,
    filtering out None values (non-matching lines).
    """
    results = []
    for line in lines:
        parsed = parse_death_log(line)
        if parsed is not None:
            results.append(parsed)
    return results


def build_seed_snapshots(db_path, deaths, current_villagers):
    """Create 2 seed snapshots in the database from culling event data.

    Parameters
    ----------
    db_path : str or Path
        Path to the SQLite database file.
    deaths : list[dict]
        Parsed death log dicts (from parse_death_logs), each with keys:
        uuid, x, y, z, ticks_lived, message.
    current_villagers : list[dict]
        Current villager data dicts as collected by the census pipeline.
        Survivors are those whose UUID does not appear in the deaths list.
    """
    conn = init_db(db_path)

    dead_uuids = {d["uuid"] for d in deaths}

    # Identify survivors: current DEFAULT-spawn villagers not in the dead list.
    # BREEDING villagers born after the culling should NOT appear in seed snapshots.
    survivors = [
        v for v in current_villagers
        if v["uuid"] not in dead_uuids and v.get("spawn_reason") == "DEFAULT"
    ]

    total_pre = len(deaths) + len(survivors)

    # ------------------------------------------------------------------
    # Snapshot 0 — Pre-culling
    # ------------------------------------------------------------------
    pre_snap = insert_snapshot(
        conn,
        timestamp=_PRE_CULLING_TS,
        players_online=len(_PLAYERS_ONLINE),
        area_center_x=_AREA_CENTER_X,
        area_center_z=_AREA_CENTER_Z,
        scan_radius=_SCAN_RADIUS,
        villager_count=total_pre,
        bed_count=0,
        notes=_PRE_NOTES,
    )

    # Insert dead villagers into villagers + states
    for death in deaths:
        insert_villager(
            conn,
            uuid=death["uuid"],
            first_seen_snapshot=pre_snap,
            last_seen_snapshot=pre_snap,
            spawn_reason=None,
            origin_x=None,
            origin_y=None,
            origin_z=None,
        )
        insert_villager_state(
            conn,
            snapshot_id=pre_snap,
            villager_uuid=death["uuid"],
            pos_x=death["x"],
            pos_y=death["y"],
            pos_z=death["z"],
            health=None,
            food_level=None,
            profession=None,
            profession_level=None,
            villager_type=None,
            xp=None,
            ticks_lived=death["ticks_lived"],
            age=None,
            home_x=None,
            home_y=None,
            home_z=None,
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
            restocks_today=None,
            on_ground=None,
            last_gossip_decay=None,
        )
        mark_dead(conn, death["uuid"], death_snapshot=pre_snap)

    # Insert survivors into villagers + states (pre-culling)
    for v in survivors:
        # Use origin coords if available, fallback to pos coords
        if v.get("origin_x") is not None:
            sv_x = v["origin_x"]
            sv_y = v["origin_y"]
            sv_z = v["origin_z"]
        else:
            sv_x = v.get("pos_x")
            sv_y = v.get("pos_y")
            sv_z = v.get("pos_z")

        insert_villager(
            conn,
            uuid=v["uuid"],
            first_seen_snapshot=pre_snap,
            last_seen_snapshot=pre_snap,
            spawn_reason=v.get("spawn_reason"),
            origin_x=v.get("origin_x"),
            origin_y=v.get("origin_y"),
            origin_z=v.get("origin_z"),
        )
        insert_villager_state(
            conn,
            snapshot_id=pre_snap,
            villager_uuid=v["uuid"],
            pos_x=sv_x,
            pos_y=sv_y,
            pos_z=sv_z,
            health=None,
            food_level=None,
            profession=v.get("profession"),
            profession_level=v.get("profession_level"),
            villager_type=v.get("villager_type"),
            xp=None,
            ticks_lived=None,
            age=None,
            home_x=None,
            home_y=None,
            home_z=None,
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
            restocks_today=None,
            on_ground=None,
            last_gossip_decay=None,
        )

    # ------------------------------------------------------------------
    # Snapshot 1 — Post-culling
    # ------------------------------------------------------------------
    post_snap = insert_snapshot(
        conn,
        timestamp=_POST_CULLING_TS,
        players_online=len(_PLAYERS_ONLINE),
        area_center_x=_AREA_CENTER_X,
        area_center_z=_AREA_CENTER_Z,
        scan_radius=_SCAN_RADIUS,
        villager_count=len(survivors),
        bed_count=0,
        notes=_POST_NOTES,
    )

    # Insert survivors into post-culling snapshot and update last_seen
    for v in survivors:
        if v.get("origin_x") is not None:
            sv_x = v["origin_x"]
            sv_y = v["origin_y"]
            sv_z = v["origin_z"]
        else:
            sv_x = v.get("pos_x")
            sv_y = v.get("pos_y")
            sv_z = v.get("pos_z")

        insert_villager(
            conn,
            uuid=v["uuid"],
            first_seen_snapshot=pre_snap,
            last_seen_snapshot=post_snap,
            spawn_reason=v.get("spawn_reason"),
            origin_x=v.get("origin_x"),
            origin_y=v.get("origin_y"),
            origin_z=v.get("origin_z"),
        )
        insert_villager_state(
            conn,
            snapshot_id=post_snap,
            villager_uuid=v["uuid"],
            pos_x=sv_x,
            pos_y=sv_y,
            pos_z=sv_z,
            health=None,
            food_level=None,
            profession=v.get("profession"),
            profession_level=v.get("profession_level"),
            villager_type=v.get("villager_type"),
            xp=None,
            ticks_lived=None,
            age=None,
            home_x=None,
            home_y=None,
            home_z=None,
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
            restocks_today=None,
            on_ground=None,
            last_gossip_decay=None,
        )

    conn.close()
