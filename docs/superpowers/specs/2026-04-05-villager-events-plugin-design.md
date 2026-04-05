# Villager Events Plugin

Date: 2026-04-05
Repos: new plugin in `disqt/minecraft-villager-census` (or separate repo), census backend integration

## Overview

A lightweight PaperMC plugin that captures real-time villager events (breeding, deaths) that the snapshot-based census system cannot track. The plugin writes events as JSONL to a file on disk. The census pipeline reads and ingests this file each run.

No existing public plugin covers this use case (researched Modrinth, Hangar, SpigotMC, GitHub — see research notes below).

## Server Environment

- PaperMC 1.21.11 (build 69)
- Java 21 (OpenJDK 21.0.4)
- Server path: `/home/minecraft/serverfiles/`
- Plugins dir: `/home/minecraft/serverfiles/plugins/`
- Existing custom plugins: Disquests (Fabric client + PaperMC server)

## Plugin Design

### Events Captured

**EntityBreedEvent** (`org.bukkit.event.entity.EntityBreedEvent`):
- Fires when two villagers breed successfully
- Data captured: child UUID, parent 1 UUID, parent 2 UUID, position (x/y/z), timestamp
- Only fires for Villager entity type (filter in handler)

**EntityDeathEvent** (`org.bukkit.event.entity.EntityDeathEvent`):
- Fires when a villager dies
- Data captured: UUID, death cause (from `getLastDamageCause().getCause()`), killer entity type (if any), position (x/y/z), ticks lived, timestamp
- Only fires for Villager entity type (filter in handler)

### Output Format

Events written as JSONL (one JSON object per line) to:
`/home/minecraft/serverfiles/plugins/VillagerCensusEvents/events.jsonl`

```jsonl
{"type":"breed","timestamp":"2026-04-05T12:34:56Z","child_uuid":"...","parent1_uuid":"...","parent2_uuid":"...","x":3150.5,"y":64.0,"z":-950.2}
{"type":"death","timestamp":"2026-04-05T12:35:10Z","uuid":"...","cause":"FALL","killer":null,"x":3145.0,"y":63.0,"z":-965.0,"ticks_lived":48000,"message":"Villager hit the ground too hard"}
```

**Death cause values** (from `EntityDamageEvent.DamageCause` enum):
`CONTACT`, `ENTITY_ATTACK`, `ENTITY_SWEEP_ATTACK`, `PROJECTILE`, `SUFFOCATION`, `FALL`, `FIRE`, `FIRE_TICK`, `LAVA`, `DROWNING`, `BLOCK_EXPLOSION`, `ENTITY_EXPLOSION`, `VOID`, `LIGHTNING`, `STARVATION`, `POISON`, `MAGIC`, `WITHER`, `FALLING_BLOCK`, `THORNS`, `DRAGON_BREATH`, `CUSTOM`, `FLY_INTO_WALL`, `HOT_FLOOR`, `CRAMMING`, `DRYOUT`, `FREEZE`, `SONIC_BOOM`, `KILL`

### File Rotation

The census pipeline reads the events file each run and processes new entries. After successful ingestion:
- Census renames `events.jsonl` to `events.jsonl.processed.{timestamp}`
- Plugin detects missing file and creates a new one
- Alternatively: plugin appends, census truncates after read (simpler but risks race condition)

**Recommended approach**: Plugin always appends to `events.jsonl`. Census reads the file, ingests all lines, then truncates it to zero bytes. File locking via `.lock` file to prevent race conditions.

### Plugin Structure

```
VillagerCensusEvents/
  src/main/java/com/disqt/census/events/
    VillagerCensusEventsPlugin.java   — main plugin class, registers listeners
    VillagerEventListener.java        — @EventHandler for breed + death
    EventWriter.java                  — thread-safe JSONL file writer
  src/main/resources/
    paper-plugin.yml                  — plugin metadata (Paper 1.19.4+ format)
  build.gradle                        — Gradle build config
```

### paper-plugin.yml

```yaml
name: VillagerCensusEvents
version: 1.0.0
main: com.disqt.census.events.VillagerCensusEventsPlugin
description: Tracks villager breeding and death events for census analytics
api-version: '1.21'
```

### Key Implementation Details

**VillagerEventListener.java:**
```java
@EventHandler
public void onBreed(EntityBreedEvent event) {
    if (!(event.getEntity() instanceof Villager child)) return;
    Entity parent1 = event.getMother();
    Entity parent2 = event.getFather();
    // Write breed event with child UUID, parent UUIDs, position
}

@EventHandler
public void onDeath(EntityDeathEvent event) {
    if (!(event.getEntity() instanceof Villager villager)) return;
    EntityDamageEvent damage = villager.getLastDamageCause();
    String cause = damage != null ? damage.getCause().name() : "UNKNOWN";
    // Write death event with UUID, cause, position, ticks lived
}
```

**EventWriter.java:**
- Synchronized `append(String json)` method
- Opens file in append mode per write (or keeps handle open with flush)
- Creates plugin data folder if missing
- Handles IOException gracefully (log warning, don't crash server)

## Census Integration

### New DB table: `villager_events`

```sql
CREATE TABLE villager_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT NOT NULL,           -- 'breed' or 'death'
    timestamp   TEXT NOT NULL,           -- ISO 8601
    uuid        TEXT NOT NULL,           -- child UUID (breed) or dead villager UUID (death)
    parent1_uuid TEXT,                   -- breed only
    parent2_uuid TEXT,                   -- breed only
    cause       TEXT,                    -- death only (DamageCause enum name)
    killer      TEXT,                    -- death only (entity type or null)
    message     TEXT,                    -- death only (death message)
    pos_x       REAL,
    pos_y       REAL,
    pos_z       REAL,
    ticks_lived INTEGER,                -- death only
    snapshot_id INTEGER REFERENCES snapshots(id)  -- snapshot that ingested this event
);
```

### New collection function: `get_villager_events()`

In `census_collect.py`:

```python
EVENTS_FILE = "/home/minecraft/serverfiles/plugins/VillagerCensusEvents/events.jsonl"

def get_villager_events():
    """Read and return villager events from the plugin's JSONL file.
    
    Returns list of event dicts. Truncates the file after reading.
    """
    # Read the file
    lines = _run_command(f"cat {EVENTS_FILE} 2>/dev/null")
    events = []
    for line in lines:
        line = line.strip()
        if line:
            events.append(json.loads(line))
    
    # Truncate after successful read
    if events:
        _run_command(f": > {EVENTS_FILE}")
    
    return events
```

### Pipeline integration

In `census.py`, after snapshot data is stored, ingest events:

```python
# After step 10 (deaths and births)
events = get_villager_events()
for event in events:
    insert_villager_event(conn, event, snapshot_id)
```

### Relationship to death cause tracking

This plugin provides a **more precise** death cause than log parsing (spec: `2026-04-05-death-cause-tracking-design.md`). Once the plugin is active:
- Plugin events are the primary source for death cause (exact enum, killer entity)
- Log parsing serves as fallback for deaths that happened before the plugin was installed
- Both feed into the same `death_cause` field on the `villagers` table

The `mark_dead()` call should prefer plugin event cause over log-parsed cause when both are available.

## Build & Deploy

```bash
# Build
cd VillagerCensusEvents
gradle build

# Deploy
scp build/libs/VillagerCensusEvents-1.0.0.jar minecraft:/home/minecraft/serverfiles/plugins/

# Reload (or restart server)
# Via tmux: /reload confirm
```

## Research Notes

Plugins evaluated and rejected:
- **CoreProtect**: Logs villager kills but no breeding, no DamageCause enum
- **Prism**: Grief logger, zero breed event support
- **VillagerAnnouncer**: Broadcasts deaths to Discord, no persistence, no UUIDs, no breeding
- **VillagerSaver**: Prevents villager loss, no event logging
- None cover EntityBreedEvent with parent UUID capture

## Out of Scope

- Real-time dashboard push (events are ingested at census interval)
- Tracking non-villager entities
- Plugin configuration GUI
- Event replay/backfill for pre-plugin history
