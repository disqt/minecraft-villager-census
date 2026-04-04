"""Entity region file parser — extracts villager entities from .mca files."""

import io
import struct
import zlib

from census_parse import ints_to_uuid
from census_poi import read_nbt


def _strip_ns(s):
    """Strip 'minecraft:' namespace prefix from a string."""
    if s and s.startswith("minecraft:"):
        return s[len("minecraft:"):]
    return s


def _extract_memory_pos(memories, key):
    """Return (x, y, z) from a brain memory pos entry, or (None, None, None)."""
    if not memories or key not in memories:
        return None, None, None
    entry = memories[key]
    try:
        pos = entry["value"]["pos"]
        return int(pos[0]), int(pos[1]), int(pos[2])
    except (KeyError, TypeError, IndexError):
        return None, None, None


def _extract_memory_value(memories, key):
    """Return the scalar value from a brain memory entry, or None."""
    if not memories or key not in memories:
        return None
    entry = memories[key]
    try:
        return entry["value"]
    except (KeyError, TypeError):
        return None


def _parse_trade(recipe, slot):
    """Convert one trade recipe NBT dict to the standard trade shape."""
    def item_and_count(field):
        slot_data = recipe.get(field)
        if not slot_data:
            return None, None
        item = _strip_ns(slot_data.get("id"))
        count = slot_data.get("count")
        return item, count

    buy_item, buy_count = item_and_count("buy")
    buy_b_item, buy_b_count = item_and_count("buyB")
    sell_item, sell_count = item_and_count("sell")

    return {
        "slot": slot,
        "buy_item": buy_item,
        "buy_count": buy_count,
        "buy_b_item": buy_b_item,
        "buy_b_count": buy_b_count,
        "sell_item": sell_item,
        "sell_count": sell_count,
        "price_multiplier": recipe.get("priceMultiplier"),
        "max_uses": recipe.get("maxUses"),
        "xp": recipe.get("xp"),
    }


def _parse_gossip_entry(g):
    """Convert one gossip entry NBT dict to the standard gossip shape."""
    target_ints = g.get("Target")
    target_uuid = ints_to_uuid(target_ints) if target_ints and len(target_ints) == 4 else None
    return {
        "gossip_type": g.get("Type"),
        "target_uuid": target_uuid,
        "value": g.get("Value"),
    }


def nbt_to_villager(nbt):
    """Convert a villager entity NBT compound dict to the standard villager dict shape.

    Returns the same field layout as census_parse.parse_entity_line().
    All fields are direct dict lookups — no regex parsing.
    """
    # UUID
    uuid_ints = nbt.get("UUID")
    uuid = ints_to_uuid(uuid_ints) if uuid_ints and len(uuid_ints) == 4 else None

    # Position
    pos = nbt.get("Pos") or []
    pos_x = pos[0] if len(pos) > 0 else None
    pos_y = pos[1] if len(pos) > 1 else None
    pos_z = pos[2] if len(pos) > 2 else None

    # Paper-specific fields (stored as flat dotted keys in NBT)
    origin = nbt.get("Paper.Origin") or []
    origin_x = origin[0] if len(origin) > 0 else None
    origin_y = origin[1] if len(origin) > 1 else None
    origin_z = origin[2] if len(origin) > 2 else None
    spawn_reason = nbt.get("Paper.SpawnReason")

    # VillagerData
    vd = nbt.get("VillagerData") or {}
    profession = _strip_ns(vd.get("profession"))
    profession_level = vd.get("level")
    villager_type = _strip_ns(vd.get("type"))

    # Health / food
    health = nbt.get("Health")
    food_level = nbt.get("FoodLevel")

    # XP / ticks / age / ground
    xp = nbt.get("Xp")
    ticks_lived = nbt.get("Spigot.ticksLived")
    age = nbt.get("Age")
    on_ground = nbt.get("OnGround")

    # Commerce
    restocks_today = nbt.get("RestocksToday")
    last_restock = nbt.get("LastRestock")
    last_gossip_decay = nbt.get("LastGossipDecay")

    # Brain memories
    brain = nbt.get("Brain") or {}
    memories = brain.get("memories") or {}

    home_x, home_y, home_z = _extract_memory_pos(memories, "minecraft:home")
    job_site_x, job_site_y, job_site_z = _extract_memory_pos(memories, "minecraft:job_site")
    meeting_x, meeting_y, meeting_z = _extract_memory_pos(memories, "minecraft:meeting_point")
    last_slept = _extract_memory_value(memories, "minecraft:last_slept")
    last_woken = _extract_memory_value(memories, "minecraft:last_woken")
    last_worked = _extract_memory_value(memories, "minecraft:last_worked_at_poi")

    # Nested collections
    offers = nbt.get("Offers") or {}
    recipes = offers.get("Recipes") or []
    trades = [_parse_trade(r, slot) for slot, r in enumerate(recipes)]

    raw_inventory = nbt.get("Inventory") or []
    inventory = [
        {"item": _strip_ns(item.get("id")), "count": item.get("count")}
        for item in raw_inventory
    ]

    raw_gossip = nbt.get("Gossips") or []
    gossip = [_parse_gossip_entry(g) for g in raw_gossip]

    return {
        "uuid": uuid,
        "pos_x": pos_x,
        "pos_y": pos_y,
        "pos_z": pos_z,
        "origin_x": origin_x,
        "origin_y": origin_y,
        "origin_z": origin_z,
        "spawn_reason": spawn_reason,
        "profession": profession,
        "profession_level": profession_level,
        "villager_type": villager_type,
        "health": health,
        "food_level": food_level,
        "xp": xp,
        "ticks_lived": ticks_lived,
        "age": age,
        "on_ground": on_ground,
        "restocks_today": restocks_today,
        "last_restock": last_restock,
        "last_gossip_decay": last_gossip_decay,
        "home_x": home_x,
        "home_y": home_y,
        "home_z": home_z,
        "job_site_x": job_site_x,
        "job_site_y": job_site_y,
        "job_site_z": job_site_z,
        "meeting_point_x": meeting_x,
        "meeting_point_y": meeting_y,
        "meeting_point_z": meeting_z,
        "last_slept": last_slept,
        "last_woken": last_woken,
        "last_worked": last_worked,
        "trades": trades,
        "inventory": inventory,
        "gossip": gossip,
    }


# ---------------------------------------------------------------------------
# MCA / entity region parser
# ---------------------------------------------------------------------------

def parse_entity_region(region_path):
    """Parse an entity .mca file. Returns list of villager dicts."""
    results = []
    with open(region_path, "rb") as f:
        location_header = f.read(4096)
        f.read(4096)  # skip timestamp header

        for slot in range(1024):
            entry_bytes = location_header[slot * 4: slot * 4 + 4]
            entry = struct.unpack(">I", entry_bytes)[0]
            offset = (entry >> 8) & 0xFFFFFF
            sector_count = entry & 0xFF
            if offset == 0 and sector_count == 0:
                continue

            f.seek(offset * 4096)
            length = struct.unpack(">I", f.read(4))[0]
            compression_type = struct.unpack(">B", f.read(1))[0]
            compressed_data = f.read(length - 1)

            if compression_type == 2:
                raw = zlib.decompress(compressed_data)
            elif compression_type == 1:
                import gzip
                raw = gzip.decompress(compressed_data)
            else:
                raw = compressed_data

            nbt = read_nbt(io.BytesIO(raw))
            entities = nbt.get("Entities", [])
            for entity in entities:
                if entity.get("id") == "minecraft:villager":
                    results.append(nbt_to_villager(entity))

    return results


def parse_entity_regions(region_paths):
    """Parse multiple entity region files. Returns combined list of villager dicts."""
    results = []
    for path in region_paths:
        results.extend(parse_entity_region(path))
    return results
