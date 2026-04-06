# Missing vs Dead Villager Distinction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop treating disappeared villagers as dead — distinguish between "missing" (disappeared without a death event) and "dead" (confirmed by plugin), and handle reappearances.

**Architecture:** Add `status` and `missing_since` columns to the `villagers` table via migration. Replace the single `mark_dead()` call in the pipeline with three-way logic: confirmed dead (plugin event), missing (no event), or reappeared (was missing, now back). Keep `presumed_dead` column for backwards compat but stop writing to it from new code paths.

**Tech Stack:** Python 3, SQLite, pytest (stdlib only)

---

### Task 1: Add `status` and `missing_since` columns + migration

**Files:**
- Modify: `census_db.py:17-52` (add columns to `_SCHEMA`)
- Modify: `census_db.py:179-208` (add migration logic in `_migrate()`)
- Test: `tests/test_census_db_migration.py`

- [ ] **Step 1: Write failing migration tests**

Add to `tests/test_census_db_migration.py`:

```python
def test_migrate_adds_status_and_missing_since_columns(tmp_path):
    """Existing DB without status/missing_since gets columns added."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE villagers (
            uuid TEXT PRIMARY KEY,
            first_seen_snapshot INTEGER,
            last_seen_snapshot INTEGER,
            spawn_reason TEXT,
            origin_x REAL, origin_y REAL, origin_z REAL,
            presumed_dead INTEGER DEFAULT 0,
            death_snapshot INTEGER,
            death_cause TEXT
        )
    """)
    conn.commit()
    conn.close()

    conn = init_db(db_path)
    cols = _get_columns(conn, "villagers")
    assert "status" in cols
    assert "missing_since" in cols
    conn.close()


def test_migrate_status_data_migration(tmp_path):
    """Migration maps presumed_dead + death_cause to correct status values."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE villagers (
            uuid TEXT PRIMARY KEY,
            first_seen_snapshot INTEGER,
            last_seen_snapshot INTEGER,
            spawn_reason TEXT,
            origin_x REAL, origin_y REAL, origin_z REAL,
            presumed_dead INTEGER DEFAULT 0,
            death_snapshot INTEGER,
            death_cause TEXT
        )
    """)
    # alive villager
    conn.execute(
        "INSERT INTO villagers (uuid, first_seen_snapshot, last_seen_snapshot, presumed_dead) "
        "VALUES ('alive-1', 1, 1, 0)"
    )
    # dead with cause (confirmed dead)
    conn.execute(
        "INSERT INTO villagers (uuid, first_seen_snapshot, last_seen_snapshot, presumed_dead, death_cause) "
        "VALUES ('dead-with-cause', 1, 1, 1, 'FALL')"
    )
    # dead without cause (ambiguous -> missing)
    conn.execute(
        "INSERT INTO villagers (uuid, first_seen_snapshot, last_seen_snapshot, presumed_dead) "
        "VALUES ('dead-no-cause', 1, 1, 1)"
    )
    conn.commit()
    conn.close()

    conn = init_db(db_path)

    row = conn.execute("SELECT status FROM villagers WHERE uuid='alive-1'").fetchone()
    assert row[0] == "alive"

    row = conn.execute("SELECT status FROM villagers WHERE uuid='dead-with-cause'").fetchone()
    assert row[0] == "dead"

    row = conn.execute("SELECT status FROM villagers WHERE uuid='dead-no-cause'").fetchone()
    assert row[0] == "missing"

    conn.close()


def test_migrate_status_idempotent(tmp_path):
    """Running init_db twice doesn't fail or re-migrate status values."""
    db_path = tmp_path / "test.db"
    conn1 = init_db(db_path)
    conn1.close()
    conn2 = init_db(db_path)
    cols = _get_columns(conn2, "villagers")
    assert "status" in cols
    assert "missing_since" in cols
    conn2.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_census_db_migration.py::test_migrate_adds_status_and_missing_since_columns tests/test_census_db_migration.py::test_migrate_status_data_migration tests/test_census_db_migration.py::test_migrate_status_idempotent -v`
Expected: FAIL — `status` and `missing_since` columns don't exist yet.

- [ ] **Step 3: Add columns to `_SCHEMA` in `census_db.py`**

In the `villagers` table definition in `_SCHEMA` (around line 42-52), add after the `death_cause TEXT` line:

```python
    death_cause         TEXT,
    status              TEXT    NOT NULL DEFAULT 'alive',
    missing_since       INTEGER REFERENCES snapshots(id)
```

Note: remove the trailing comma issue — `death_cause TEXT` currently has no comma after it, so add a comma before the new lines.

- [ ] **Step 4: Add migration logic in `_migrate()`**

At the end of `_migrate()` in `census_db.py`, after the existing `death_cause` migration block:

```python
    cur = conn.execute("PRAGMA table_info(villagers)")
    cols = {row[1] for row in cur.fetchall()}
    if "status" not in cols:
        conn.execute("ALTER TABLE villagers ADD COLUMN status TEXT NOT NULL DEFAULT 'alive'")
        conn.execute("ALTER TABLE villagers ADD COLUMN missing_since INTEGER REFERENCES snapshots(id)")
        # Data migration: map existing presumed_dead to status
        conn.execute("UPDATE villagers SET status = 'dead' WHERE presumed_dead = 1 AND death_cause IS NOT NULL")
        conn.execute("UPDATE villagers SET status = 'missing' WHERE presumed_dead = 1 AND death_cause IS NULL")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_census_db_migration.py -v`
Expected: All pass, including the three new tests.

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `python -m pytest tests/ -v`
Expected: All 135+ tests pass.

- [ ] **Step 7: Commit**

```bash
git add census_db.py tests/test_census_db_migration.py
git commit -m "feat(db): add status and missing_since columns with data migration"
```

---

### Task 2: Add `mark_missing`, `mark_alive`, and `get_missing_uuids` DB functions

**Files:**
- Modify: `census_db.py` (add three new functions after `mark_dead`)
- Test: `tests/test_census_db.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_census_db.py`, importing the new functions at the top:

```python
from census_db import (
    # ... existing imports ...
    mark_missing,
    mark_alive,
    get_missing_uuids,
)
```

Then add these test functions:

```python
def test_mark_missing(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id, uuid="miss-1111")

    mark_missing(conn, "miss-1111", snap_id)
    v = get_villager(conn, "miss-1111")
    assert v["status"] == "missing"
    assert v["missing_since"] == snap_id
    conn.close()


def test_mark_missing_only_affects_alive(tmp_path):
    """mark_missing does not change a villager already marked dead."""
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id, uuid="dead-1111")
    mark_dead(conn, "dead-1111", snap_id, death_cause="FALL")

    mark_missing(conn, "dead-1111", snap_id)
    v = get_villager(conn, "dead-1111")
    assert v["status"] == "dead"  # unchanged
    conn.close()


def test_mark_alive(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap1 = make_snapshot(conn, timestamp="2026-04-03T10:00:00")
    snap2 = make_snapshot(conn, timestamp="2026-04-03T11:00:00")
    make_villager(conn, snap1, uuid="back-1111")

    mark_missing(conn, "back-1111", snap1)
    v = get_villager(conn, "back-1111")
    assert v["status"] == "missing"

    mark_alive(conn, "back-1111")
    v = get_villager(conn, "back-1111")
    assert v["status"] == "alive"
    assert v["missing_since"] is None
    conn.close()


def test_mark_alive_only_affects_missing(tmp_path):
    """mark_alive does not change a dead villager."""
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id, uuid="dead-2222")
    mark_dead(conn, "dead-2222", snap_id, death_cause="FALL")

    mark_alive(conn, "dead-2222")
    v = get_villager(conn, "dead-2222")
    assert v["status"] == "dead"  # unchanged
    conn.close()


def test_get_missing_uuids(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id, uuid="alive-1")
    make_villager(conn, snap_id, uuid="miss-1")
    make_villager(conn, snap_id, uuid="miss-2")
    make_villager(conn, snap_id, uuid="dead-1")

    mark_missing(conn, "miss-1", snap_id)
    mark_missing(conn, "miss-2", snap_id)
    mark_dead(conn, "dead-1", snap_id)

    missing = get_missing_uuids(conn)
    assert missing == {"miss-1", "miss-2"}
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_census_db.py::test_mark_missing tests/test_census_db.py::test_mark_alive tests/test_census_db.py::test_get_missing_uuids -v`
Expected: FAIL — `ImportError: cannot import name 'mark_missing'`

- [ ] **Step 3: Implement the three functions**

Add to `census_db.py` after the existing `mark_dead` function (after line 436):

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


def get_missing_uuids(conn):
    """Return set of UUIDs currently in 'missing' status."""
    cur = conn.execute("SELECT uuid FROM villagers WHERE status = 'missing'")
    return {row['uuid'] for row in cur.fetchall()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_census_db.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add census_db.py tests/test_census_db.py
git commit -m "feat(db): add mark_missing, mark_alive, get_missing_uuids functions"
```

---

### Task 3: Update `mark_dead` to set `status = 'dead'`

**Files:**
- Modify: `census_db.py:426-436` (update `mark_dead`)
- Test: `tests/test_census_db.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_census_db.py`:

```python
def test_mark_dead_sets_status_dead(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id, uuid="dead-status-1")
    mark_dead(conn, "dead-status-1", snap_id, death_cause="FALL")
    v = get_villager(conn, "dead-status-1")
    assert v["status"] == "dead"
    assert v["missing_since"] is None
    conn.close()


def test_mark_dead_clears_missing_since(tmp_path):
    """A missing villager confirmed dead gets missing_since cleared."""
    conn = init_db(tmp_path / "test.db")
    snap1 = make_snapshot(conn, timestamp="2026-04-03T10:00:00")
    snap2 = make_snapshot(conn, timestamp="2026-04-03T11:00:00")
    make_villager(conn, snap1, uuid="was-missing-1")
    mark_missing(conn, "was-missing-1", snap1)

    v = get_villager(conn, "was-missing-1")
    assert v["status"] == "missing"
    assert v["missing_since"] == snap1

    mark_dead(conn, "was-missing-1", snap2, death_cause="ENTITY_ATTACK")
    v = get_villager(conn, "was-missing-1")
    assert v["status"] == "dead"
    assert v["missing_since"] is None
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_census_db.py::test_mark_dead_sets_status_dead tests/test_census_db.py::test_mark_dead_clears_missing_since -v`
Expected: FAIL — `mark_dead` doesn't set `status` yet.

- [ ] **Step 3: Update `mark_dead` in `census_db.py`**

Replace the existing `mark_dead` function:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_census_db.py -v`
Expected: All pass (including existing `test_mark_dead` tests — they still check `presumed_dead = 1`).

- [ ] **Step 5: Commit**

```bash
git add census_db.py tests/test_census_db.py
git commit -m "feat(db): update mark_dead to set status='dead' and clear missing_since"
```

---

### Task 4: Update pipeline logic in `census.py`

**Files:**
- Modify: `census.py:1-37` (update imports)
- Modify: `census.py:277-319` (replace death detection with missing/dead/reappeared logic)
- Modify: `census.py:348-359` (add `missing` count to summary)
- Test: `tests/test_census_pipeline.py`

- [ ] **Step 1: Write failing pipeline tests**

Add to `tests/test_census_pipeline.py`, updating the imports:

```python
from census_db import init_db, get_latest_snapshot, get_snapshot_villager_uuids, get_villager, get_missing_uuids
```

Then add these test functions:

```python
def test_run_census_missing_without_death_event():
    """Villager disappearing without a death event is marked missing, not dead."""
    from census_parse import parse_entity_line
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    villager = parse_entity_line(SAMPLE_ENTITY_LINE)
    villager_uuid = villager["uuid"]

    # First run: villager alive
    _run_with_mocks(db_path, villagers=[villager])

    # Second run: villager gone, NO death event from plugin
    _run_with_mocks(db_path, villagers=[], beds=[], plugin_events=[])

    conn = init_db(db_path)
    v = get_villager(conn, villager_uuid)
    assert v["status"] == "missing"
    assert v["missing_since"] is not None
    conn.close()


def test_run_census_dead_with_death_event():
    """Villager disappearing WITH a death event is marked dead."""
    from census_parse import parse_entity_line
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    villager = parse_entity_line(SAMPLE_ENTITY_LINE)
    villager_uuid = villager["uuid"]

    # First run: villager alive
    _run_with_mocks(db_path, villagers=[villager])

    # Second run: villager gone, death event from plugin
    death_events = [
        {"type": "death", "timestamp": "2026-04-06T12:00:00Z",
         "uuid": villager_uuid, "cause": "DROWNING", "killer": None,
         "x": 0, "y": 0, "z": 0, "ticks_lived": 1000, "message": "drowned"},
    ]
    _run_with_mocks(db_path, villagers=[], beds=[], plugin_events=death_events)

    conn = init_db(db_path)
    v = get_villager(conn, villager_uuid)
    assert v["status"] == "dead"
    assert v["death_cause"] == "DROWNING"
    conn.close()


def test_run_census_missing_villager_reappears():
    """A missing villager that reappears gets status='alive' and missing_since=NULL."""
    from census_parse import parse_entity_line
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    villager = parse_entity_line(SAMPLE_ENTITY_LINE)
    villager_uuid = villager["uuid"]

    # Run 1: villager alive
    _run_with_mocks(db_path, villagers=[villager])

    # Run 2: villager gone (missing)
    _run_with_mocks(db_path, villagers=[], beds=[], plugin_events=[])

    conn = init_db(db_path)
    v = get_villager(conn, villager_uuid)
    assert v["status"] == "missing"
    conn.close()

    # Run 3: villager is back
    _run_with_mocks(db_path, villagers=[villager])

    conn = init_db(db_path)
    v = get_villager(conn, villager_uuid)
    assert v["status"] == "alive"
    assert v["missing_since"] is None
    conn.close()


def test_run_census_summary_includes_missing():
    """Summary dict includes missing count."""
    from census_parse import parse_entity_line
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    villager = parse_entity_line(SAMPLE_ENTITY_LINE)

    # Run 1: villager alive
    _run_with_mocks(db_path, villagers=[villager])

    # Run 2: villager gone, no death event
    summary = _run_with_mocks(db_path, villagers=[], beds=[], plugin_events=[])
    assert summary["missing"] == 1
    assert summary["deaths"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_census_pipeline.py::test_run_census_missing_without_death_event tests/test_census_pipeline.py::test_run_census_dead_with_death_event tests/test_census_pipeline.py::test_run_census_missing_villager_reappears tests/test_census_pipeline.py::test_run_census_summary_includes_missing -v`
Expected: FAIL — pipeline still calls `mark_dead` for all disappearances.

- [ ] **Step 3: Update imports in `census.py`**

Update the `census_db` import block at the top of `census.py`:

```python
from census_db import (
    export_all_json,
    get_latest_snapshot,
    get_missing_uuids,
    get_snapshot_villager_uuids,
    init_db,
    insert_bed,
    insert_bell,
    insert_census_run,
    insert_gossip,
    insert_inventory_item,
    insert_snapshot,
    insert_trade,
    insert_villager,
    insert_villager_event,
    insert_villager_state,
    mark_alive,
    mark_dead,
    mark_missing,
)
```

- [ ] **Step 4: Replace death detection logic in `census.py`**

Replace the Step 10 block (lines 277-319) with:

```python
    # Step 10: detect disappeared, dead, and reappeared villagers
    disappeared_uuids = prev_uuids - current_uuids
    reappeared_uuids = current_uuids & get_missing_uuids(conn)

    # Step 10a: ingest plugin events
    plugin_events = get_villager_events()
    death_causes = {}
    for event in plugin_events:
        evt_type = event.get("type")
        if evt_type == "death":
            uuid = event.get("uuid", "")
            insert_villager_event(
                conn,
                event_type="death",
                timestamp=event.get("timestamp", ""),
                uuid=uuid,
                cause=event.get("cause"),
                killer=event.get("killer"),
                message=event.get("message"),
                pos_x=event.get("x"),
                pos_y=event.get("y"),
                pos_z=event.get("z"),
                ticks_lived=event.get("ticks_lived"),
                snapshot_id=snapshot_id,
            )
            death_causes[uuid] = event.get("cause")
        elif evt_type == "breed":
            insert_villager_event(
                conn,
                event_type="breed",
                timestamp=event.get("timestamp", ""),
                uuid=event.get("child_uuid", ""),
                parent1_uuid=event.get("parent1_uuid"),
                parent2_uuid=event.get("parent2_uuid"),
                pos_x=event.get("x"),
                pos_y=event.get("y"),
                pos_z=event.get("z"),
                snapshot_id=snapshot_id,
            )

    # Step 10b: classify disappearances as dead or missing
    death_event_uuids = set(death_causes.keys())
    confirmed_deaths = disappeared_uuids & death_event_uuids
    newly_missing = disappeared_uuids - death_event_uuids

    for uuid in confirmed_deaths:
        mark_dead(conn, uuid, snapshot_id, death_cause=death_causes.get(uuid))

    for uuid in newly_missing:
        mark_missing(conn, uuid, snapshot_id)

    # Step 10c: reappeared villagers (were missing, now back)
    for uuid in reappeared_uuids:
        mark_alive(conn, uuid)
```

- [ ] **Step 5: Update summary to include `missing` count**

Replace the summary return dict (around line 348) — add `"missing"` key and update `"deaths"` to only count confirmed deaths:

```python
    return {
        "snapshot_id": snapshot_id,
        "timestamp": timestamp,
        "villager_count": len(villagers),
        "bed_count": len(beds),
        "bell_count": len(bells),
        "births": len(births_uuids),
        "deaths": len(confirmed_deaths),
        "missing": len(newly_missing),
        "homeless": homeless,
        "players_online": players,
        "zones": zone_summary,
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_census_pipeline.py -v`
Expected: All pass.

- [ ] **Step 7: Update the existing `test_run_census_detects_deaths` test**

This test currently expects `summary2["deaths"] == 1` when a villager disappears without a death event. With the new logic, it should be `missing == 1` and `deaths == 0`. Update:

```python
def test_run_census_detects_deaths():
    """Second run missing a previously seen villager marks it as missing (no death event)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    summary1 = _run_with_mocks(db_path)
    assert summary1["births"] == 1
    assert summary1["deaths"] == 0

    summary2 = _run_with_mocks(db_path, villagers=[], beds=[])
    assert summary2["deaths"] == 0
    assert summary2["missing"] == 1

    conn = init_db(db_path)
    cur = conn.execute("SELECT status FROM villagers")
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "missing"
    conn.close()
```

- [ ] **Step 8: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add census.py tests/test_census_pipeline.py
git commit -m "feat: distinguish missing vs dead villagers in pipeline logic"
```

---

### Task 5: Update CLI summary output

**Files:**
- Modify: `census.py:588-599` (print summary)

- [ ] **Step 1: Update the summary print block**

In the CLI `main()` function, update the summary print (around line 588-594) to include missing count:

```python
    print(f"\n## Census — {summary['timestamp']}")
    print(f"**Population:** {summary['villager_count']}  |  "
          f"**Beds:** {summary['bed_count']}  |  "
          f"**Bells:** {summary['bell_count']}  |  "
          f"**Births:** {summary['births']}  |  "
          f"**Deaths:** {summary['deaths']}  |  "
          f"**Missing:** {summary['missing']}  |  "
          f"**Homeless:** {summary['homeless']}")
```

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add census.py
git commit -m "feat(cli): show missing villager count in census summary output"
```
