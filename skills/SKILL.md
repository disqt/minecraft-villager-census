---
name: villager-census
description: Run a villager population census on the PaperMC server. Collects entity data via SSH/tmux, parses POI files for beds, stores everything in SQLite, detects births and deaths since the last census, and opens an interactive HTML playground to inspect results and compare snapshots. Supports zone-based analysis via TOML config.
---

# Villager Census

Collect a population snapshot of Minecraft villagers in named zones, store it in a SQLite database, and produce an interactive visual report with per-zone breakdown.

## Prerequisites

- A player must be online and near the target area (chunks must be loaded for entity data to be available)
- SSH access to the Minecraft server via `ssh minecraft`
- The server console is accessible via tmux at `/tmp/tmux-1000/pmcserver-bb664df1`

## Inputs

Ask for any not already known:

- **Place name** — a named place from `villager-census/zones.toml` (e.g. "piwigord"), OR a custom center + radius for ad-hoc scans
- **Notes** — optional free-text annotation for this snapshot (e.g. "post-culling", "after bed expansion")

## Zone Configuration

Zones are defined in `villager-census/zones.toml`. Each place has one or more named zones:

```toml
# Rectangle zones (two corners)
[[places.piwigord.zones]]
name = "north-village"
corners = [[3090, -1040], [3220, -960]]

# Circle zones (center + radius)
[[places.hamlet.zones]]
name = "center"
center = [50, 50]
radius = 30
```

Every villager and bed gets classified into a zone. Entities outside all zones appear as "unclassified" in the summary.

For ad-hoc scans without a TOML entry, use a single circle zone with a meaningful name (the place or landmark name, not "default").

## Step 1 — Verify server access

1. Run `ssh minecraft "tmux -S /tmp/tmux-1000/pmcserver-bb664df1 send-keys -t pmcserver 'list' Enter"` and check the log for players online
2. If no players are online, STOP and tell the user: "No players online — chunks aren't loaded, so villager data is unavailable. Someone needs to be near the target area for the census to work."
3. Get the nearest player's position and verify they're within range of the target area

## Step 2 — Run the census pipeline

Run the Python census tool from the repo root. For a configured place:

```python
from census_zones import load_place
from census import run_census

place = load_place("piwigord")
summary = run_census(
    db_path="villager-census/census.db",
    zones=place["zones"],
    poi_regions=place["poi_regions"],
    notes="optional note",
)
```

For an ad-hoc single-point scan:

```python
from census_zones import make_single_zone
from census import run_census

zones = [make_single_zone(center_x=3150, center_z=-950, radius=300, name="piwigord")]
summary = run_census(
    db_path="villager-census/census.db",
    zones=zones,
    poi_regions=[(5, -3), (5, -2), (6, -3), (6, -2)],
)
```

If this is the first run and `census.db` doesn't exist yet, first run the seeding script to reconstruct historical data from the March 30 culling:

```bash
scp minecraft:/home/minecraft/serverfiles/logs/2026-03-30-3.log.gz /tmp/
gunzip -k /tmp/2026-03-30-3.log.gz
grep "died" /tmp/2026-03-30-3.log | grep "Villager" > /tmp/culling_deaths.txt
cd villager-census && python census_seed.py --db census.db --deaths /tmp/culling_deaths.txt
```

The pipeline will:
1. Compute bounding box from all zones
2. Send `execute as @e[type=minecraft:villager,x=..,y=-64,z=..,dx=..,dy=384,dz=..]` to the server console
3. Parse all entity data from the server log
4. Download POI region files and extract bed locations
5. Classify each villager and bed into its zone
6. Write everything to the SQLite database
7. Detect births (new UUIDs) and deaths (missing UUIDs) since last snapshot

## Step 3 — Report summary

Print the census summary to the user with per-zone breakdown:

```
## Census Summary — [date]

**Population:** [count] villagers ([+/-delta] from last census)
**Beds:** [count] ([claimed]/[total] claimed)
**Births:** [count] new villagers since last census
**Deaths:** [count] villagers disappeared since last census
**Homeless:** [count] villagers without a bed

### Zone breakdown
| Zone | Villagers | Beds |
|------|-----------|------|
| north-village | 12 | 15 |
| old-city | 45 | 50 |
| farm | 66 | 70 |

### Profession breakdown
| Profession | Count | Change |
|---|---|---|
| farmer | 31 | +2 |
| ... | ... | ... |
```

## Step 4 — Launch playground

Invoke the `playground` skill to generate an interactive HTML viewer. The playground should:

1. Read the full database export from `villager-census/census.db` using `census.export_census_json()`
2. Embed the JSON data directly in the HTML
3. Include these views:
   - **Population timeline** — line chart of villager count and bed count across all snapshots, with per-zone lines
   - **Current census table** — sortable list of all villagers with profession, health, bed status, position, zone
   - **Map view** — 2D scatter plot of villager positions, color-coded by zone, with bed markers and zone boundaries
   - **Snapshot comparison** — dropdown to select two snapshots, shows births, deaths, movement, bed changes
   - **Villager detail** — click a villager to see full history across snapshots (position trail, profession changes, gossip)
4. Open the playground in the user's browser

## Database location

The SQLite database lives at `villager-census/census.db` in this repo. It is gitignored.
