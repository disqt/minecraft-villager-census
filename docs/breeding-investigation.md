# Villager Breeding Investigation

## The Problem

Villagers reproduce far beyond the bed count. After culling, population grows back to 4-5x the number of beds within a week.

## Timeline

| Date | Event | Population | Beds |
|------|-------|------------|------|
| ~2026-03-30 | First cull | ~37 (post-cull) | ~37 |
| 2026-04-06 | Population regrown | 169 | 37 |
| 2026-04-06 | Second cull (132 /kill via RCON) | 37 (post-cull) | 37 |
| 2026-04-06 | 2 births within 28 min of cull | 39+ | 37 |

## Expected Behavior

Per Minecraft wiki, villagers should only breed when the birthing parent can pathfind to an unclaimed bed within 48 blocks (with 2 empty blocks above it). No global population census -- it's purely "does a free bed exist nearby?"

## Bed Audit (2026-04-06)

37 total beds. 27 claimed, 10 unclaimed. Of the 10 unclaimed:

| # | Position | Zone | Y | Reachable? | Notes |
|---|----------|------|---|------------|-------|
| 1 | (3160, 6, -946) | old-city | 6 | **No** | Deep in a mine |
| 2 | (3163, 40, -896) | old-city | 40 | **No** | Underground forge |
| 3 | (3164, 40, -896) | old-city | 40 | **No** | Underground forge |
| 4 | (3165, 40, -896) | old-city | 40 | **No** | Underground forge |
| 5 | (3139, 63, -967) | old-city | 63 | **Yes** | |
| 6 | (3107, 64, -879) | farm | 64 | **Yes** | |
| 7 | (3140, 64, -1028) | north-village | 64 | **Yes** | Near breeding site |
| 8 | (3140, 64, -1027) | north-village | 64 | **No** | In a tree |
| 9 | (3154, 70, -921) | old-city | 70 | **No** | On a roof |
| 10 | (3193, 80, -945) | old-city | 80 | **No** | On a roof |

**Summary: 3 reachable, 7 unreachable unclaimed beds.**

## Key Finding: Post-Cull Breeding

Within 28 minutes of the second cull, 2 births occurred near (3140, -1010). Both sets of parents share the same bell at (3141, -1009). One baby claimed bed at (3165, 69, -995), the other is homeless.

## Open Questions

1. **Are unreachable beds triggering breeding?** The game checks if an unclaimed bed exists within 48 blocks. Does "exists" mean pathfindable, or just within coordinate range? If the latter, the 7 unreachable beds are a permanent breeding signal.

2. **Do bed claims churn?** Villagers may temporarily unclaim beds (sleep/wake cycle, wander too far). If a bed flickers to unclaimed even briefly, a nearby pair could breed during that window.

3. **Is the 48-block check taxicab or euclidean?** Underground beds at y=40 are only ~25 blocks below surface villagers at y=65 -- within 48 blocks vertically even if not pathfindable.

## Hypotheses (ranked by likelihood)

### 1. Unreachable beds count as "available" (most likely)
The breeding check may only require an unclaimed bed to exist within 48-block range, without verifying pathfinding. The 7 permanently unclaimed unreachable beds would act as an infinite breeding signal.

**Test:** Break all 7 unreachable beds, monitor if breeding stops.

### 2. Bed claim churn
Villagers temporarily lose bed claims, creating brief windows for breeding.

**Test:** Run census every 5 min for an hour, compare bed claims between snapshots.

### 3. POI data divergence
On-disk POI data doesn't match the game's runtime state.

**Test:** Compare POI file bed count vs `/data get` on POI blocks in-game.

### 4. Farmer auto-feeding keeps willingness maxed
Not a root cause (need both food AND bed), but accelerates the problem.

## Context: World Migration

Piwigord was migrated to a new seed using MCA Edit after Minecraft lowered the world floor (1.18 Caves & Cliffs, y=-64). This could be relevant:

- POI data may not have migrated cleanly -- beds could exist in the POI index that no longer correspond to real blocks in the world
- The underground beds at y=6 and y=40 could be artifacts from the migration (old structures that got buried or corrupted)
- The POI system stores bed locations independently from the actual blocks -- if MCA Edit moved chunks but didn't update the POI files consistently, the game could "see" beds that don't physically exist anymore

**This would explain why unreachable beds exist in weird places.** They might not even be real beds -- just ghost entries in the POI data from the migration.

**Test:** Go to the unreachable bed locations and check if there's actually a bed block there, or if it's just stone/air.

## Next Steps

- [ ] Test hypothesis #1: break the 7 unreachable beds, monitor breeding
- [ ] If breeding continues, investigate bed claim churn (hypothesis #2)
- [ ] Track breeding rate: births per hour after cull
