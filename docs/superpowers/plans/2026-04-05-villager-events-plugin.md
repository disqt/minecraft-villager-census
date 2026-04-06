# Villager Events Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PaperMC plugin that captures villager breed/death events as JSONL, and wire the census backend to ingest those events into SQLite.

**Architecture:** Two components: (1) A Java PaperMC plugin (`VillagerCensusEvents/`) that listens to `EntityBreedEvent` and `EntityDeathEvent`, writing JSON lines to `events.jsonl`. (2) Python census integration that reads the JSONL file via SSH, stores events in a new `villager_events` table, and uses plugin death causes to enrich `mark_dead()`.

**Tech Stack:** Java 21, Gradle, PaperMC API 1.21, Python 3.11+, SQLite, SSH/SCP

**Spec:** `docs/superpowers/specs/2026-04-05-villager-events-plugin-design.md`

---

## File Structure

### New files (Java plugin)

| File | Responsibility |
|------|---------------|
| `VillagerCensusEvents/build.gradle` | Gradle build config targeting Paper API 1.21 |
| `VillagerCensusEvents/settings.gradle` | Project name |
| `VillagerCensusEvents/src/main/java/com/disqt/census/events/EventWriter.java` | Thread-safe JSONL file appender |
| `VillagerCensusEvents/src/main/java/com/disqt/census/events/VillagerEventListener.java` | Event handlers for breed + death |
| `VillagerCensusEvents/src/main/java/com/disqt/census/events/VillagerCensusEventsPlugin.java` | Main plugin class, registers listener |
| `VillagerCensusEvents/src/main/resources/paper-plugin.yml` | Plugin metadata |

### Modified files (Python census)

| File | Changes |
|------|---------|
| `census_db.py` | Add `villager_events` table to schema, `death_cause` column migration, `insert_villager_event()`, `get_villager_events_for_snapshot()` |
| `census_collect.py` | Add `get_villager_events()` to read + truncate the JSONL file via SSH |
| `census.py` | Import new functions, wire event ingestion after step 10, pass death cause to `mark_dead()` |
| `tests/test_census_db.py` | Tests for new table, insert, query, migration |
| `tests/test_census_collect.py` | Tests for `get_villager_events()` parsing |
| `tests/test_census_pipeline.py` | Integration test for event ingestion in pipeline |

---

## Task 1: Gradle project scaffold

**Files:**
- Create: `VillagerCensusEvents/build.gradle`
- Create: `VillagerCensusEvents/settings.gradle`
- Create: `VillagerCensusEvents/src/main/resources/paper-plugin.yml`

- [ ] **Step 1: Create `settings.gradle`**

```gradle
rootProject.name = 'VillagerCensusEvents'
```

- [ ] **Step 2: Create `build.gradle`**

```gradle
plugins {
    id 'java'
}

group = 'com.disqt.census.events'
version = '1.0.0'

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(21)
    }
}

repositories {
    mavenCentral()
    maven { url = 'https://repo.papermc.io/repository/maven-public/' }
}

dependencies {
    compileOnly 'io.papermc.paper:paper-api:1.21.4-R0.1-SNAPSHOT'
}

tasks.jar {
    archiveBaseName = 'VillagerCensusEvents'
}
```

- [ ] **Step 3: Create `paper-plugin.yml`**

```yaml
name: VillagerCensusEvents
version: 1.0.0
main: com.disqt.census.events.VillagerCensusEventsPlugin
description: Tracks villager breeding and death events for census analytics
api-version: '1.21'
```

- [ ] **Step 4: Create source directory structure**

```bash
mkdir -p VillagerCensusEvents/src/main/java/com/disqt/census/events
```

- [ ] **Step 5: Commit**

```bash
git add VillagerCensusEvents/build.gradle VillagerCensusEvents/settings.gradle VillagerCensusEvents/src/main/resources/paper-plugin.yml
git commit -m "feat(plugin): scaffold Gradle project for VillagerCensusEvents"
```

---

## Task 2: EventWriter — thread-safe JSONL file appender

**Files:**
- Create: `VillagerCensusEvents/src/main/java/com/disqt/census/events/EventWriter.java`

- [ ] **Step 1: Write EventWriter.java**

```java
package com.disqt.census.events;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.logging.Logger;

/**
 * Thread-safe JSONL file appender. Opens file in append mode per write.
 * Creates the parent directory if it does not exist.
 */
public final class EventWriter {

    private final Path filePath;
    private final Logger logger;

    public EventWriter(Path filePath, Logger logger) {
        this.filePath = filePath;
        this.logger = logger;
    }

    /** Ensure the parent directory exists. Call once at plugin enable. */
    public void init() {
        try {
            Files.createDirectories(filePath.getParent());
        } catch (IOException e) {
            logger.warning("Failed to create events directory: " + e.getMessage());
        }
    }

    /** Append a single JSON line to the events file. */
    public synchronized void append(String json) {
        try (BufferedWriter writer = Files.newBufferedWriter(filePath,
                StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
            writer.write(json);
            writer.newLine();
        } catch (IOException e) {
            logger.warning("Failed to write event: " + e.getMessage());
        }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add VillagerCensusEvents/src/main/java/com/disqt/census/events/EventWriter.java
git commit -m "feat(plugin): add EventWriter thread-safe JSONL appender"
```

---

## Task 3: VillagerEventListener — breed and death handlers

**Files:**
- Create: `VillagerCensusEvents/src/main/java/com/disqt/census/events/VillagerEventListener.java`

- [ ] **Step 1: Write VillagerEventListener.java**

```java
package com.disqt.census.events;

import org.bukkit.entity.Entity;
import org.bukkit.entity.Villager;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityBreedEvent;
import org.bukkit.event.entity.EntityDeathEvent;
import org.bukkit.event.entity.EntityDamageEvent;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;

public final class VillagerEventListener implements Listener {

    private static final DateTimeFormatter ISO_FMT =
            DateTimeFormatter.ISO_INSTANT;

    private final EventWriter writer;

    public VillagerEventListener(EventWriter writer) {
        this.writer = writer;
    }

    @EventHandler
    public void onBreed(EntityBreedEvent event) {
        if (!(event.getEntity() instanceof Villager child)) return;

        Entity parent1 = event.getMother();
        Entity parent2 = event.getFather();
        String timestamp = ISO_FMT.format(Instant.now());

        String json = String.format(
            "{\"type\":\"breed\",\"timestamp\":\"%s\","
            + "\"child_uuid\":\"%s\","
            + "\"parent1_uuid\":\"%s\","
            + "\"parent2_uuid\":\"%s\","
            + "\"x\":%.1f,\"y\":%.1f,\"z\":%.1f}",
            timestamp,
            child.getUniqueId(),
            parent1.getUniqueId(),
            parent2.getUniqueId(),
            child.getLocation().getX(),
            child.getLocation().getY(),
            child.getLocation().getZ()
        );

        writer.append(json);
    }

    @EventHandler
    public void onDeath(EntityDeathEvent event) {
        if (!(event.getEntity() instanceof Villager villager)) return;

        EntityDamageEvent damage = villager.getLastDamageCause();
        String cause = damage != null ? damage.getCause().name() : "UNKNOWN";

        Entity killer = event.getEntity().getKiller();
        String killerType = killer != null ? killer.getType().name() : "null";

        String timestamp = ISO_FMT.format(Instant.now());

        // Get death message — Paper provides this via the event
        String message = event.deathMessage() != null
                ? net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer
                    .plainText().serialize(event.deathMessage())
                : "";

        String json = String.format(
            "{\"type\":\"death\",\"timestamp\":\"%s\","
            + "\"uuid\":\"%s\","
            + "\"cause\":\"%s\","
            + "\"killer\":%s,"
            + "\"x\":%.1f,\"y\":%.1f,\"z\":%.1f,"
            + "\"ticks_lived\":%d,"
            + "\"message\":\"%s\"}",
            timestamp,
            villager.getUniqueId(),
            cause,
            killerType.equals("null") ? "null" : "\"" + killerType + "\"",
            villager.getLocation().getX(),
            villager.getLocation().getY(),
            villager.getLocation().getZ(),
            villager.getTicksLived(),
            message.replace("\"", "\\\"")
        );

        writer.append(json);
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add VillagerCensusEvents/src/main/java/com/disqt/census/events/VillagerEventListener.java
git commit -m "feat(plugin): add VillagerEventListener for breed and death events"
```

---

## Task 4: Main plugin class

**Files:**
- Create: `VillagerCensusEvents/src/main/java/com/disqt/census/events/VillagerCensusEventsPlugin.java`

- [ ] **Step 1: Write VillagerCensusEventsPlugin.java**

```java
package com.disqt.census.events;

import org.bukkit.plugin.java.JavaPlugin;

import java.nio.file.Path;

public final class VillagerCensusEventsPlugin extends JavaPlugin {

    @Override
    public void onEnable() {
        Path eventsFile = getDataFolder().toPath().resolve("events.jsonl");
        EventWriter writer = new EventWriter(eventsFile, getLogger());
        writer.init();

        getServer().getPluginManager().registerEvents(
                new VillagerEventListener(writer), this);

        getLogger().info("VillagerCensusEvents enabled — writing to " + eventsFile);
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add VillagerCensusEvents/src/main/java/com/disqt/census/events/VillagerCensusEventsPlugin.java
git commit -m "feat(plugin): add main plugin class with listener registration"
```

---

## Task 5: Build the plugin JAR

- [ ] **Step 1: Build with Gradle**

```bash
cd VillagerCensusEvents
gradle build
```

Expected: `BUILD SUCCESSFUL`, JAR at `build/libs/VillagerCensusEvents-1.0.0.jar`.

- [ ] **Step 2: Verify the JAR contents**

```bash
jar tf build/libs/VillagerCensusEvents-1.0.0.jar | grep -E "(\.class|paper-plugin\.yml)"
```

Expected output should include:
```
paper-plugin.yml
com/disqt/census/events/VillagerCensusEventsPlugin.class
com/disqt/census/events/VillagerEventListener.class
com/disqt/census/events/EventWriter.class
```

- [ ] **Step 3: Commit build config refinements (if any)**

---

## Task 6: `villager_events` table + migration

**Files:**
- Modify: `census_db.py:17-144` (schema) and `census_db.py:161-185` (migration)
- Test: `tests/test_census_db.py`

- [ ] **Step 1: Write failing test for new table**

Add to `tests/test_census_db.py`:

```python
def test_init_db_creates_villager_events_table(tmp_path):
    conn = init_db(tmp_path / "test.db")
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='villager_events'"
    )
    assert cursor.fetchone() is not None
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_census_db.py::test_init_db_creates_villager_events_table -v
```

Expected: FAIL — table does not exist.

- [ ] **Step 3: Add `villager_events` table to `_SCHEMA` in `census_db.py`**

Add after the `bells` CREATE TABLE block (before the closing `"""`):

```sql
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_census_db.py::test_init_db_creates_villager_events_table -v
```

Expected: PASS

- [ ] **Step 5: Update `test_init_db_creates_all_tables` to expect the new table**

In `tests/test_census_db.py`, add `"villager_events"` to the `expected` set in `test_init_db_creates_all_tables`.

- [ ] **Step 6: Run full DB test suite**

```bash
python -m pytest tests/test_census_db.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add census_db.py tests/test_census_db.py
git commit -m "feat(db): add villager_events table to schema"
```

---

## Task 7: `death_cause` column migration

**Files:**
- Modify: `census_db.py:161-185` (`_migrate` function)
- Test: `tests/test_census_db_migration.py`

- [ ] **Step 1: Write failing test for death_cause migration**

Add to `tests/test_census_db_migration.py`:

```python
def test_migrate_adds_death_cause_column(tmp_path):
    """Existing DB without death_cause gets the column added."""
    import sqlite3
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
            death_snapshot INTEGER
        )
    """)
    conn.commit()
    conn.close()

    from census_db import init_db
    conn = init_db(db_path)
    cur = conn.execute("PRAGMA table_info(villagers)")
    cols = {row[1] for row in cur.fetchall()}
    assert "death_cause" in cols
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_census_db_migration.py::test_migrate_adds_death_cause_column -v
```

Expected: FAIL — `death_cause` not in cols.

- [ ] **Step 3: Add `death_cause` column to schema and migration**

In `census_db.py`, update the `villagers` CREATE TABLE to include `death_cause TEXT` after `death_snapshot`:

```sql
    death_snapshot      INTEGER REFERENCES snapshots(id),
    death_cause         TEXT
```

Add to `_migrate()` function:

```python
    cur = conn.execute("PRAGMA table_info(villagers)")
    cols = {row[1] for row in cur.fetchall()}
    if "death_cause" not in cols:
        conn.execute("ALTER TABLE villagers ADD COLUMN death_cause TEXT")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_census_db_migration.py::test_migrate_adds_death_cause_column -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add census_db.py tests/test_census_db_migration.py
git commit -m "feat(db): add death_cause column to villagers table with migration"
```

---

## Task 8: `insert_villager_event()` and `mark_dead()` with death_cause

**Files:**
- Modify: `census_db.py:381-392` (`mark_dead`)
- Modify: `census_db.py` (add `insert_villager_event`)
- Test: `tests/test_census_db.py`

- [ ] **Step 1: Write failing test for `insert_villager_event`**

Add to `tests/test_census_db.py`:

```python
from census_db import insert_villager_event, get_villager_events_for_snapshot


def test_insert_villager_event_death(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    insert_villager_event(
        conn,
        event_type="death",
        timestamp="2026-04-05T12:35:10Z",
        uuid="dead-1111",
        cause="FALL",
        killer=None,
        message="Villager hit the ground too hard",
        pos_x=3145.0,
        pos_y=63.0,
        pos_z=-965.0,
        ticks_lived=48000,
        snapshot_id=snap_id,
    )
    events = get_villager_events_for_snapshot(conn, snap_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "death"
    assert events[0]["uuid"] == "dead-1111"
    assert events[0]["cause"] == "FALL"
    assert events[0]["ticks_lived"] == 48000
    conn.close()


def test_insert_villager_event_breed(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    insert_villager_event(
        conn,
        event_type="breed",
        timestamp="2026-04-05T12:34:56Z",
        uuid="child-1111",
        parent1_uuid="parent-aaaa",
        parent2_uuid="parent-bbbb",
        pos_x=3150.5,
        pos_y=64.0,
        pos_z=-950.2,
        snapshot_id=snap_id,
    )
    events = get_villager_events_for_snapshot(conn, snap_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "breed"
    assert events[0]["parent1_uuid"] == "parent-aaaa"
    assert events[0]["parent2_uuid"] == "parent-bbbb"
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_census_db.py::test_insert_villager_event_death tests/test_census_db.py::test_insert_villager_event_breed -v
```

Expected: FAIL — `insert_villager_event` not defined.

- [ ] **Step 3: Implement `insert_villager_event` and `get_villager_events_for_snapshot`**

Add to `census_db.py` after `insert_bell`:

```python
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
```

Add to the query helpers section:

```python
def get_villager_events_for_snapshot(conn, snapshot_id):
    """Return all villager events for a given snapshot."""
    cur = conn.execute(
        "SELECT * FROM villager_events WHERE snapshot_id = ?",
        (snapshot_id,),
    )
    return [dict(row) for row in cur.fetchall()]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_census_db.py::test_insert_villager_event_death tests/test_census_db.py::test_insert_villager_event_breed -v
```

Expected: PASS

- [ ] **Step 5: Write failing test for `mark_dead` with death_cause**

Add to `tests/test_census_db.py`:

```python
def test_mark_dead_with_death_cause(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id, uuid="dead-2222")
    mark_dead(conn, "dead-2222", snap_id, death_cause="ENTITY_ATTACK")
    v = get_villager(conn, "dead-2222")
    assert v["presumed_dead"] == 1
    assert v["death_cause"] == "ENTITY_ATTACK"
    conn.close()


def test_mark_dead_without_death_cause(tmp_path):
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id, uuid="dead-3333")
    mark_dead(conn, "dead-3333", snap_id)
    v = get_villager(conn, "dead-3333")
    assert v["presumed_dead"] == 1
    assert v["death_cause"] is None
    conn.close()
```

- [ ] **Step 6: Run tests to verify they fail**

```bash
python -m pytest tests/test_census_db.py::test_mark_dead_with_death_cause -v
```

Expected: FAIL — `mark_dead()` does not accept `death_cause`.

- [ ] **Step 7: Update `mark_dead()` to accept `death_cause`**

Replace the `mark_dead` function in `census_db.py`:

```python
def mark_dead(conn, uuid, death_snapshot, death_cause=None):
    """Set presumed_dead=1 and record death_snapshot and optional death_cause."""
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

- [ ] **Step 8: Run tests to verify they pass**

```bash
python -m pytest tests/test_census_db.py::test_mark_dead_with_death_cause tests/test_census_db.py::test_mark_dead_without_death_cause -v
```

Expected: PASS

- [ ] **Step 9: Run full DB test suite**

```bash
python -m pytest tests/test_census_db.py -v
```

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add census_db.py tests/test_census_db.py
git commit -m "feat(db): add insert_villager_event and death_cause to mark_dead"
```

---

## Task 9: `get_villager_events()` collection function

**Files:**
- Modify: `census_collect.py` (add `get_villager_events`)
- Test: `tests/test_census_collect.py`

- [ ] **Step 1: Write failing test for `get_villager_events`**

Add to `tests/test_census_collect.py`:

```python
from census_collect import get_villager_events


def test_get_villager_events_parses_jsonl(monkeypatch):
    """get_villager_events reads JSONL lines and returns parsed dicts."""
    sample_lines = [
        '{"type":"breed","timestamp":"2026-04-05T12:34:56Z","child_uuid":"c-1","parent1_uuid":"p-1","parent2_uuid":"p-2","x":3150.5,"y":64.0,"z":-950.2}',
        '{"type":"death","timestamp":"2026-04-05T12:35:10Z","uuid":"d-1","cause":"FALL","killer":null,"x":3145.0,"y":63.0,"z":-965.0,"ticks_lived":48000,"message":"Villager hit the ground too hard"}',
    ]
    monkeypatch.setattr("census_collect._run_command",
                        lambda cmd: sample_lines if "cat" in cmd else [])

    events = get_villager_events()
    assert len(events) == 2
    assert events[0]["type"] == "breed"
    assert events[0]["child_uuid"] == "c-1"
    assert events[1]["type"] == "death"
    assert events[1]["cause"] == "FALL"
    assert events[1]["ticks_lived"] == 48000


def test_get_villager_events_empty_file(monkeypatch):
    """get_villager_events returns empty list when file is empty or missing."""
    monkeypatch.setattr("census_collect._run_command", lambda cmd: [])
    events = get_villager_events()
    assert events == []


def test_get_villager_events_skips_blank_lines(monkeypatch):
    """Blank lines in the JSONL file are silently skipped."""
    lines = [
        '{"type":"breed","timestamp":"2026-04-05T12:34:56Z","child_uuid":"c-1","parent1_uuid":"p-1","parent2_uuid":"p-2","x":0,"y":0,"z":0}',
        '',
        '   ',
    ]
    monkeypatch.setattr("census_collect._run_command", lambda cmd: lines)
    events = get_villager_events()
    assert len(events) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_census_collect.py::test_get_villager_events_parses_jsonl tests/test_census_collect.py::test_get_villager_events_empty_file tests/test_census_collect.py::test_get_villager_events_skips_blank_lines -v
```

Expected: FAIL — `get_villager_events` not defined.

- [ ] **Step 3: Implement `get_villager_events` in `census_collect.py`**

Add at the end of `census_collect.py`, after the log parsing section:

```python
# ---------------------------------------------------------------------------
# Plugin event ingestion
# ---------------------------------------------------------------------------

EVENTS_FILE = "/home/minecraft/serverfiles/plugins/VillagerCensusEvents/events.jsonl"


def get_villager_events():
    """Read villager events from the plugin's JSONL file and truncate it.

    Returns a list of event dicts. Truncates the file after reading so
    events are not re-ingested on the next run.
    """
    import json as _json

    lines = _run_command(f"cat {EVENTS_FILE} 2>/dev/null")
    events = []
    for line in lines:
        line = line.strip()
        if line:
            events.append(_json.loads(line))

    if events:
        _run_command(f": > {EVENTS_FILE}")

    return events
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_census_collect.py::test_get_villager_events_parses_jsonl tests/test_census_collect.py::test_get_villager_events_empty_file tests/test_census_collect.py::test_get_villager_events_skips_blank_lines -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add census_collect.py tests/test_census_collect.py
git commit -m "feat(collect): add get_villager_events to read plugin JSONL"
```

---

## Task 10: Wire event ingestion into census pipeline

**Files:**
- Modify: `census.py:10-35` (imports), `census.py:275-280` (deaths section)
- Test: `tests/test_census_pipeline.py`

- [ ] **Step 1: Write failing integration test**

Add to `tests/test_census_pipeline.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_census_pipeline.py::test_run_census_ingests_villager_events -v
```

Expected: FAIL — `get_villager_events` not imported in census.py.

- [ ] **Step 3: Wire event ingestion into `census.py`**

Add to imports in `census.py`:

```python
from census_collect import (
    check_players_online,
    configure as configure_transport,
    entity_region_coords,
    get_entity_files,
    get_entity_mtimes,
    get_poi_files,
    get_player_position,
    get_villager_events,
    save_all,
)
from census_db import (
    export_all_json,
    get_latest_snapshot,
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
    mark_dead,
)
```

In `run_census()`, replace the deaths section (after line 276 `deaths_uuids = prev_uuids - current_uuids`):

```python
    # Step 10: deaths and births
    deaths_uuids = prev_uuids - current_uuids
    births_uuids = current_uuids - prev_uuids

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

    for uuid in deaths_uuids:
        cause = death_causes.get(uuid)
        mark_dead(conn, uuid, snapshot_id, death_cause=cause)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_census_pipeline.py::test_run_census_ingests_villager_events -v
```

Expected: PASS

- [ ] **Step 5: Write test for death cause propagation to `mark_dead`**

Add to `tests/test_census_pipeline.py`:

```python
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
```

- [ ] **Step 6: Run test to verify it passes**

```bash
python -m pytest tests/test_census_pipeline.py::test_run_census_uses_plugin_death_cause -v
```

Expected: PASS

- [ ] **Step 7: Ensure existing pipeline tests still mock correctly**

The existing tests don't mock `get_villager_events`, so they'll call the real function which hits SSH. We need to add a mock to `_run_with_mocks`:

Update `_run_with_mocks` in `tests/test_census_pipeline.py`:

```python
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
```

- [ ] **Step 8: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add census.py tests/test_census_pipeline.py
git commit -m "feat: wire plugin event ingestion into census pipeline"
```

---

## Task 11: Backfill death causes from server logs

**Files:**
- Modify: `census_collect.py` (add `get_recent_deaths`)
- Modify: `census_db.py` (add `backfill_death_causes`)
- Modify: `census.py` (add `--backfill-death-causes` CLI flag)
- Test: `tests/test_census_collect.py`, `tests/test_census_db.py`

The existing `parse_death_log()` can extract UUID + death message from server log lines. We can backfill `death_cause` for villagers already marked dead but with no cause, by scanning available server logs. The death message (e.g. "Villager was slain by Drowned") is stored as the cause — less precise than the plugin's `DamageCause` enum, but better than NULL.

- [ ] **Step 1: Write failing test for `get_recent_deaths`**

Add to `tests/test_census_collect.py`:

```python
from census_collect import get_recent_deaths


def test_get_recent_deaths_parses_log(monkeypatch):
    """get_recent_deaths extracts villager death entries from log tail."""
    log_lines = [
        "[19:44:53] [Server thread/INFO]: Some unrelated log line",
        "[19:45:01] [Server thread/INFO]: Villager[Fisherman, uuid='aaaa-1111-bbbb-2222', l='ServerLevel[world_new]', x=3145.0, y=63.0, z=-965.0, cpos=[196, -61], tl=48000, v=true] died, message: 'Villager was slain by Drowned'",
        "[19:45:02] [Server thread/INFO]: Another unrelated line",
    ]
    monkeypatch.setattr("census_collect._run_command", lambda cmd: log_lines)
    deaths = get_recent_deaths()
    assert len(deaths) == 1
    assert deaths[0]["uuid"] == "aaaa-1111-bbbb-2222"
    assert deaths[0]["message"] == "Villager was slain by Drowned"


def test_get_recent_deaths_empty_log(monkeypatch):
    """get_recent_deaths returns empty list when no death lines found."""
    monkeypatch.setattr("census_collect._run_command", lambda cmd: ["[INFO]: Server started"])
    deaths = get_recent_deaths()
    assert deaths == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_census_collect.py::test_get_recent_deaths_parses_log tests/test_census_collect.py::test_get_recent_deaths_empty_log -v
```

Expected: FAIL — `get_recent_deaths` not defined.

- [ ] **Step 3: Implement `get_recent_deaths` in `census_collect.py`**

Add after the `parse_death_log` function:

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

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_census_collect.py::test_get_recent_deaths_parses_log tests/test_census_collect.py::test_get_recent_deaths_empty_log -v
```

Expected: PASS

- [ ] **Step 5: Write failing test for `backfill_death_causes`**

Add to `tests/test_census_db.py`:

```python
from census_db import backfill_death_causes


def test_backfill_death_causes(tmp_path):
    """backfill_death_causes updates dead villagers with matching log deaths."""
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)

    # Two dead villagers, no death cause
    make_villager(conn, snap_id, uuid="dead-aaaa")
    mark_dead(conn, "dead-aaaa", snap_id)
    make_villager(conn, snap_id, uuid="dead-bbbb")
    mark_dead(conn, "dead-bbbb", snap_id)
    # One alive villager (should not be touched)
    make_villager(conn, snap_id, uuid="alive-cccc")

    log_deaths = [
        {"uuid": "dead-aaaa", "x": 0, "y": 0, "z": 0, "ticks_lived": 100,
         "message": "Villager was slain by Zombie"},
        {"uuid": "unknown-dddd", "x": 0, "y": 0, "z": 0, "ticks_lived": 200,
         "message": "Villager drowned"},
    ]

    updated = backfill_death_causes(conn, log_deaths)
    assert updated == 1  # only dead-aaaa matched

    v1 = get_villager(conn, "dead-aaaa")
    assert v1["death_cause"] == "Villager was slain by Zombie"

    v2 = get_villager(conn, "dead-bbbb")
    assert v2["death_cause"] is None  # no matching log entry

    v3 = get_villager(conn, "alive-cccc")
    assert v3["presumed_dead"] == 0
    conn.close()


def test_backfill_death_causes_skips_already_filled(tmp_path):
    """backfill_death_causes does not overwrite existing death causes."""
    conn = init_db(tmp_path / "test.db")
    snap_id = make_snapshot(conn)
    make_villager(conn, snap_id, uuid="dead-eeee")
    mark_dead(conn, "dead-eeee", snap_id, death_cause="FALL")

    log_deaths = [
        {"uuid": "dead-eeee", "x": 0, "y": 0, "z": 0, "ticks_lived": 100,
         "message": "Villager hit the ground too hard"},
    ]

    updated = backfill_death_causes(conn, log_deaths)
    assert updated == 0  # already has a cause

    v = get_villager(conn, "dead-eeee")
    assert v["death_cause"] == "FALL"  # unchanged
    conn.close()
```

- [ ] **Step 6: Run tests to verify they fail**

```bash
python -m pytest tests/test_census_db.py::test_backfill_death_causes tests/test_census_db.py::test_backfill_death_causes_skips_already_filled -v
```

Expected: FAIL — `backfill_death_causes` not defined.

- [ ] **Step 7: Implement `backfill_death_causes` in `census_db.py`**

Add to the query helpers section:

```python
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
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
python -m pytest tests/test_census_db.py::test_backfill_death_causes tests/test_census_db.py::test_backfill_death_causes_skips_already_filled -v
```

Expected: PASS

- [ ] **Step 9: Add `--backfill-death-causes` CLI flag to `census.py`**

Add to the argparse section in `main()`, after the `--uninstall` argument:

```python
parser.add_argument("--backfill-death-causes", action="store_true",
                    help="Backfill death causes from server logs for existing dead villagers")
```

Add handler after the `--uninstall` block:

```python
if args.backfill_death_causes:
    from census_collect import get_recent_deaths
    from census_db import backfill_death_causes
    configure_transport(ssh_host=args.ssh)
    conn = init_db(args.db)
    log_deaths = get_recent_deaths(since_lines=5000)
    updated = backfill_death_causes(conn, log_deaths)
    conn.close()
    print(f"Backfilled {updated} death cause(s) from server logs ({len(log_deaths)} death entries found)")
    return
```

- [ ] **Step 10: Commit**

```bash
git add census_collect.py census_db.py census.py tests/test_census_collect.py tests/test_census_db.py
git commit -m "feat: add death cause backfill from server logs"
```

---

## Task 12: Deploy plugin and backfill

- [ ] **Step 1: Copy JAR to server**

```bash
scp VillagerCensusEvents/build/libs/VillagerCensusEvents-1.0.0.jar minecraft:/home/minecraft/serverfiles/plugins/
```

- [ ] **Step 2: Reload the server**

Via tmux on the minecraft server:

```
/reload confirm
```

- [ ] **Step 3: Verify plugin loaded**

Check server log for:
```
[VillagerCensusEvents] VillagerCensusEvents enabled — writing to plugins/VillagerCensusEvents/events.jsonl
```

- [ ] **Step 4: Deploy updated census Python code**

```bash
ssh dev "cd /home/dev/minecraft-villager-census && git pull"
```

- [ ] **Step 5: Run backfill for existing dead villagers**

```bash
ssh dev "cd /home/dev/minecraft-villager-census && python census.py --db census.db --ssh minecraft --backfill-death-causes"
```

Note: This scans the last 5000 lines of `latest.log`. Server logs rotate, so this will only find deaths from recent history. Earlier deaths (like the Great Culling) won't be found unless their log lines are still available. That's expected — we backfill what we can.

- [ ] **Step 6: Run a manual census to verify integration**

```bash
ssh dev "cd /home/dev/minecraft-villager-census && python census.py --config zones.toml --place piwigord --db census.db --ssh minecraft"
```

Verify it completes without errors.

---

## Task 13: Update `.gitignore` and CLAUDE.md

**Files:**
- Modify: `.gitignore` (whitelist `VillagerCensusEvents/` paths)
- Modify: `CLAUDE.md` (add plugin to structure)

- [ ] **Step 1: Update `.gitignore`**

Add whitelisting for the plugin directory:

```gitignore
# VillagerCensusEvents plugin
!VillagerCensusEvents/
!VillagerCensusEvents/**
```

- [ ] **Step 2: Update `CLAUDE.md` structure section**

Add `VillagerCensusEvents/` to the structure listing:

```
VillagerCensusEvents/  # PaperMC plugin — villager breed/death event logger (Java/Gradle)
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore CLAUDE.md
git commit -m "docs: add VillagerCensusEvents plugin to gitignore and CLAUDE.md"
```
