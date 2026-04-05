# Death Cause Tracking

Date: 2026-04-05
Repo: `disqt/minecraft-villager-census`

## Overview

Wire the existing `parse_death_log()` function into the live census pipeline so death causes are captured and stored in the database. Currently, deaths are detected by UUID absence between snapshots but no cause is recorded. The log parsing code already exists in `census_collect.py` but is only used for historical seeding.

## Current State

- `census_collect.py:239` — `parse_death_log(line)` parses server log lines, returns `{uuid, x, y, z, ticks_lived, message}`
- `census.py:276` — Deaths detected as `prev_uuids - current_uuids`, then `mark_dead(conn, uuid, snapshot_id)` called
- `census_db.py:381` — `mark_dead()` sets `presumed_dead=1` and `death_snapshot` but stores no cause
- Server log format: `Villager[..., uuid='...', ..., x=X, y=Y, z=Z, ..., tl=N, ...] died, message: 'Villager was slain by Drowned'`

## Changes

### 1. Add `death_cause` column to `villagers` table

In `census_db.py`, add to the schema:

```sql
ALTER TABLE villagers ADD COLUMN death_cause TEXT;
```

Also add a migration path: at DB open, check if column exists and add if missing (the census already handles schema evolution this way for other columns).

### 2. New collection function: `get_recent_deaths()`

In `census_collect.py`, add a function that tails the server log and returns all death entries since a given timestamp:

```python
def get_recent_deaths(since_lines=500):
    """Tail the server log and extract villager death entries.
    
    Returns a list of dicts: {uuid, x, y, z, ticks_lived, message}
    """
    lines = _run_command(f"tail -n {since_lines} {LOG_PATH}")
    deaths = []
    for line in lines:
        parsed = parse_death_log(line)
        if parsed:
            deaths.append(parsed)
    return deaths
```

### 3. Wire into census pipeline

In `census.py`, after detecting `deaths_uuids` (line 276), call `get_recent_deaths()` and match UUIDs:

```python
# After: deaths_uuids = prev_uuids - current_uuids
recent_deaths = get_recent_deaths()
death_causes = {d["uuid"]: d["message"] for d in recent_deaths}

for uuid in deaths_uuids:
    cause = death_causes.get(uuid)
    mark_dead(conn, uuid, snapshot_id, death_cause=cause)
```

### 4. Update `mark_dead()` to accept death_cause

In `census_db.py`:

```python
def mark_dead(conn, uuid, death_snapshot, death_cause=None):
    conn.execute(
        """
        UPDATE villagers
        SET presumed_dead = 1, death_snapshot = ?, death_cause = ?
        WHERE uuid = ?
        """,
        (death_snapshot, death_cause, uuid),
    )
    conn.commit()
```

### 5. Expose death_cause in frontend queries

The frontend's `queries.js` `getVillagerInfo(uuid)` already does `SELECT * FROM villagers`, so `death_cause` will automatically be available once the column exists.

## Edge Cases

- **Death between snapshots but log rotated**: The 500-line tail should cover most cases since the census runs every 30 minutes. If the log rotated, `death_cause` will be NULL (acceptable).
- **Multiple deaths of same UUID**: Can't happen — UUIDs are unique per villager.
- **Death log format changes**: The regex in `parse_death_log()` is specific to PaperMC 1.21.x format. If Paper changes the format, the regex needs updating but the pipeline will gracefully fall back to NULL cause.

## Files Modified

| File | Changes |
|------|---------|
| `census_db.py` | Add `death_cause` column, migration, update `mark_dead()` |
| `census_collect.py` | Add `get_recent_deaths()` function |
| `census.py` | Wire death cause lookup into pipeline |

## Testing

- Add test for `get_recent_deaths()` with sample log lines
- Add test for `mark_dead()` with death_cause parameter
- Verify migration adds column without breaking existing data
