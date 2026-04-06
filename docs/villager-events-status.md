# Villager Events Plugin — Status

Deployed 2026-04-05. Captures real-time villager breed/death events that the snapshot-based census cannot track.

## What's Available

### New DB table: `villager_events`

```sql
SELECT * FROM villager_events;
-- columns: id, event_type, timestamp, uuid, parent1_uuid, parent2_uuid,
--          cause, killer, message, pos_x, pos_y, pos_z, ticks_lived, snapshot_id
```

- `event_type`: `'breed'` or `'death'`
- `uuid`: child UUID (breed) or dead villager UUID (death)
- `parent1_uuid`, `parent2_uuid`: breed events only
- `cause`: `DamageCause` enum name (death events only) — e.g. `FALL`, `ENTITY_ATTACK`, `DROWNING`, `CRAMMING`
- `killer`: entity type name or NULL (death events only)
- `snapshot_id`: which census run ingested this event

### New column: `villagers.death_cause`

Dead villagers now have a `death_cause` field populated from plugin events. NULL for pre-plugin deaths where logs were unavailable.

### Stats (as of 2026-04-06 20:30 UTC)

- 114 events captured (72 breeds, 42 deaths)
- 46/141 dead villagers have a known death cause
- 95 dead villagers have no cause (died before plugin was installed, logs rotated)

## Querying

```sql
-- Recent deaths with causes
SELECT timestamp, uuid, cause, killer, pos_x, pos_z
FROM villager_events
WHERE event_type = 'death'
ORDER BY timestamp DESC;

-- Breeding activity
SELECT timestamp, uuid AS child, parent1_uuid, parent2_uuid, pos_x, pos_z
FROM villager_events
WHERE event_type = 'breed'
ORDER BY timestamp DESC;

-- Death cause breakdown
SELECT cause, count(*) as n
FROM villager_events
WHERE event_type = 'death'
GROUP BY cause
ORDER BY n DESC;

-- Dead villagers with known cause
SELECT uuid, death_cause, death_snapshot
FROM villagers
WHERE presumed_dead = 1 AND death_cause IS NOT NULL;
```

## How It Works

1. PaperMC plugin (`VillagerCensusEvents`) listens to `EntityBreedEvent` and `EntityDeathEvent`
2. Writes JSONL to `/home/minecraft/serverfiles/plugins/VillagerCensusEvents/events.jsonl`
3. Census pipeline reads + truncates the file each run (every 30 min)
4. Events stored in `villager_events` table, death causes written to `villagers.death_cause`

## Files

- Plugin source: `VillagerCensusEvents/` (Java/Gradle)
- Plugin JAR on server: `/home/minecraft/serverfiles/plugins/VillagerCensusEvents-1.0.0.jar`
- Census integration: `census_collect.py` (`get_villager_events()`), `census.py` (pipeline wiring)
- DB: `census_db.py` (`insert_villager_event`, `backfill_death_causes`, `mark_dead` with `death_cause`)
- Design spec: `docs/superpowers/specs/2026-04-05-villager-events-plugin-design.md`
