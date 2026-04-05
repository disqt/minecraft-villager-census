# Villager Census

Minecraft villager population census tool. Collects entity data via SSH, parses NBT from `.mca` region files, stores snapshots in SQLite, detects births/deaths across time.

## Structure

```
census.py              # CLI entry point + pipeline orchestrator
census_collect.py      # SSH/tmux transport, entity/POI file download
census_db.py           # SQLite schema, insert/query helpers, export
census_entities.py     # Entity region .mca parser
census_parse.py        # Minimal NBT reader
census_poi.py          # POI region parser (beds, bells)
census_seed.py         # Historical data seeder from server logs
census_zones.py        # Zone geometry (rect/circle), classification
zones.toml             # Zone definitions (places + named zones)
skills/SKILL.md        # Claude Code skill definition
tests/                 # 135 tests, all stdlib (no pip deps)
VillagerCensusEvents/  # PaperMC plugin — villager breed/death event logger (Java/Gradle)
```

## Usage

```bash
# Configured place (from zones.toml)
python census.py --config zones.toml --place piwigord --db census.db --ssh minecraft

# Ad-hoc scan
python census.py --center 3150,-950 --radius 300 --db census.db --ssh minecraft

# Export DB as JSON
python census.py --db census.db --export-json

# Install cron (every 30 min)
python census.py --config zones.toml --place piwigord --db census.db --ssh minecraft --install 30

# Uninstall cron
python census.py --uninstall
```

## Testing

```bash
python -m pytest tests/ -v
```

All stdlib -- no pip dependencies except optional `lz4` for MC 1.20.5+ chunks.

## VPS Deployment

- Census runs on cron at `/home/dev/minecraft-villager-census/` on the VPS
- SQLite DB served by nginx at `disqt.com/minecraft/villagers/census.db`
- Frontend viewer lives in `disqt/minecraft-frontend` (Astro app at `disqt.com/minecraft/villagers/`)

## Key APIs

- SSH to `minecraft` server for entity data and POI files
- tmux console for `save-all` and player list commands
- Entity `.mca` files at `/home/minecraft/serverfiles/world_new/entities/`
- POI `.mca` files at `/home/minecraft/serverfiles/world_new/poi/`
