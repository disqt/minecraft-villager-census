# Missing vs Dead: Stop Assuming Missing = Dead

Date: 2026-04-06
Repo: `disqt/minecraft-villager-census`

## Problem

The census pipeline currently treats any UUID absent from the current snapshot as dead:

```python
deaths_uuids = prev_uuids - current_uuids
for uuid in deaths_uuids:
    mark_dead(conn, uuid, snapshot_id, death_cause=cause)
```

This is wrong. Villagers can disappear from a snapshot without dying:
- **Chunk not loaded** during save-all (player not nearby, chunk unloaded)
- **Wandered outside scanned zones** (walked past zone boundary)
- **Entity temporarily unloaded** (server performance, entity limits)
- **Moved to unscanned dimension** (e.g., nether portal)

With the VillagerCensusEvents plugin now deployed, we have ground truth: `EntityDeathEvent` fires when a villager actually dies. If a UUID disappears without a death event, the villager is **missing**, not dead.

## Current Schema

```sql
-- villagers table
uuid TEXT PRIMARY KEY,
presumed_dead INTEGER NOT NULL DEFAULT 0,
death_snapshot INTEGER REFERENCES snapshots(id),
death_cause TEXT

-- villager_events table (from plugin)
event_type TEXT,  -- 'breed' or 'death'
uuid TEXT,
cause TEXT,
timestamp TEXT
```

## Changes

### 1. Add `status` column to `villagers` table

Replace the boolean `presumed_dead` with a richer status:

```sql
ALTER TABLE villagers ADD COLUMN status TEXT NOT NULL DEFAULT 'alive';
-- Values: 'alive', 'missing', 'dead'
```

Migration: map existing data:
- `presumed_dead = 0` -> `status = 'alive'`
- `presumed_dead = 1 AND death_cause IS NOT NULL` -> `status = 'dead'` (confirmed by plugin)
- `presumed_dead = 1 AND death_cause IS NULL` -> `status = 'missing'` (no confirmation)

Keep `presumed_dead` for backwards compatibility but stop writing to it. New code reads `status`.

### 2. Add `missing_since` column

```sql
ALTER TABLE villagers ADD COLUMN missing_since INTEGER REFERENCES snapshots(id);
```

Tracks when the villager was first noticed missing. If they reappear, this resets to NULL.

### 3. Update pipeline logic in `census.py`

Replace the current death detection (around line 276):

```python
# OLD:
deaths_uuids = prev_uuids - current_uuids
for uuid in deaths_uuids:
    mark_dead(conn, uuid, snapshot_id, death_cause=cause)

# NEW:
disappeared_uuids = prev_uuids - current_uuids
reappeared_uuids = current_uuids & get_missing_uuids(conn)

# Check plugin events for confirmed deaths
events = get_villager_events()
death_event_uuids = {e['uuid'] for e in events if e['type'] == 'death'}

for uuid in disappeared_uuids:
    if uuid in death_event_uuids:
        # Confirmed dead — plugin recorded the death
        mark_dead(conn, uuid, snapshot_id, death_cause=death_causes.get(uuid))
    else:
        # Missing — no death event, might come back
        mark_missing(conn, uuid, snapshot_id)

for uuid in reappeared_uuids:
    # Was missing, now back — clear missing status
    mark_alive(conn, uuid)
```

### 4. New DB functions in `census_db.py`

```python
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

def get_missing_uuids(conn):
    """Return set of UUIDs currently in 'missing' status."""
    cur = conn.execute("SELECT uuid FROM villagers WHERE status = 'missing'")
    return {row['uuid'] for row in cur.fetchall()}
```

### 5. Handle pre-plugin historical data

For the 95 villagers marked `presumed_dead` with no `death_cause` (died before plugin was installed):
- Leave them as `status = 'missing'` after migration
- They're genuinely ambiguous — we don't know if they died or just left
- If any reappear in a future snapshot, they'll automatically get `status = 'alive'`

### 6. Grace period for missing villagers

A villager missing for 1 snapshot might just be a chunk loading issue. Consider adding a `missing_threshold` (e.g., 3 consecutive snapshots) before surfacing them in diagnostics. The pipeline doesn't need to implement this — the frontend can filter by `missing_since` age.

## Frontend Impact

The diagnostics tab should gain a new card:

**Missing Villagers** (warning severity)
- Query: `SELECT * FROM villagers WHERE status = 'missing'`
- Shows: UUID, last seen snapshot, missing since, how many snapshots missed
- Distinct from "Dead Villagers" — missing ones might return

The existing death-related diagnostics continue to work — they query `villager_events` directly.

## Files Modified

| File | Changes |
|------|---------|
| `census_db.py` | Add `status`, `missing_since` columns + migration, new functions |
| `census.py` | Replace death detection with missing/dead/reappeared logic |
| `census_collect.py` | No changes (event reading already exists) |

## Testing

- Villager disappears without death event -> `status = 'missing'`
- Villager disappears with death event -> `status = 'dead'`, `death_cause` set
- Missing villager reappears -> `status = 'alive'`, `missing_since` cleared
- Pre-plugin dead villagers with no cause -> migrated to `status = 'missing'`
- Pre-plugin dead villagers with cause -> migrated to `status = 'dead'`
