"""SNBT parser for Minecraft villager entity data from server logs."""

import re


def ints_to_uuid(ints):
    """Convert 4 signed int32s to a hex UUID string.

    E.g. [346464738, -1288157012, -1558611273, 949520682]
      -> "14a5a2e2-b37a-6e2c-a302-f4b7389dc42a"
    """
    hex_parts = [format(i & 0xFFFFFFFF, "08x") for i in ints]
    full = "".join(hex_parts)
    return f"{full[0:8]}-{full[8:12]}-{full[12:16]}-{full[16:20]}-{full[20:32]}"


def _int_array(text):
    """Parse [I; a, b, c, d] into a list of ints."""
    m = re.search(r'\[I;\s*([-\d,\s]+)\]', text)
    if not m:
        return None
    return [int(x.strip()) for x in m.group(1).split(",")]


def _scalar(pattern, text, cast=str, default=None):
    """Search for a regex pattern, return cast(group(1)) or default."""
    m = re.search(pattern, text)
    if m:
        return cast(m.group(1))
    return default


def _parse_pos_array(label, text):
    """Extract [Xd, Yd, Zd] from a named field like 'Pos: [...]'."""
    pat = rf'{re.escape(label)}:\s*\[([^\]]+)\]'
    m = re.search(pat, text)
    if not m:
        return None, None, None
    parts = m.group(1).split(",")
    coords = [float(p.strip().rstrip("d")) for p in parts]
    return coords[0], coords[1], coords[2]


def _parse_brain_pos(memory_key, brain_text):
    """Extract pos: [I; x, y, z] from a named brain memory key."""
    pat = rf'"{re.escape(memory_key)}":\s*\{{value:\s*\{{pos:\s*(\[I;[^\]]+\])'
    m = re.search(pat, brain_text)
    if not m:
        return None, None, None
    arr = _int_array(m.group(1))
    if arr and len(arr) == 3:
        return arr[0], arr[1], arr[2]
    return None, None, None


def _parse_brain_long(memory_key, brain_text):
    """Extract a single long value from a named brain memory."""
    pat = rf'"{re.escape(memory_key)}":\s*\{{value:\s*([-\d]+)L\}}'
    m = re.search(pat, brain_text)
    if m:
        return int(m.group(1))
    return None


def _extract_balanced(text, open_pos, open_char="{", close_char="}"):
    """Extract the interior content of a balanced open/close pair starting at open_pos."""
    depth = 0
    for i in range(open_pos, len(text)):
        if text[i] == open_char:
            depth += 1
        elif text[i] == close_char:
            depth -= 1
            if depth == 0:
                return text[open_pos + 1 : i]
    return None


def _extract_brain(snbt):
    """Return the content of Brain: {memories: {...}} as a string.

    Uses balanced brace extraction to handle nested structures correctly.
    """
    m = re.search(r'Brain:\s*\{memories:\s*(\{)', snbt)
    if not m:
        return ""
    content = _extract_balanced(snbt, m.start(1))
    return content if content is not None else ""


def _parse_trades(snbt):
    """Extract trades from Offers: {Recipes: [...]}."""
    m = re.search(r'Offers:\s*\{Recipes:\s*\[(.+?)\]\}', snbt, re.DOTALL)
    if not m:
        return []

    recipes_text = m.group(1)

    # Split recipes by finding top-level { } blocks
    trades = []
    depth = 0
    start = None
    slot = 0
    for i, ch in enumerate(recipes_text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                recipe = recipes_text[start:i + 1]
                trade = _parse_recipe(recipe, slot)
                trades.append(trade)
                slot += 1
                start = None
    return trades


def _parse_recipe(recipe, slot):
    """Parse a single trade recipe SNBT block."""
    def item_and_count(field_name):
        pat = rf'{re.escape(field_name)}:\s*\{{id:\s*"minecraft:([^"]+)",\s*count:\s*(\d+)\}}'
        m = re.search(pat, recipe)
        if m:
            return m.group(1), int(m.group(2))
        # try reversed order: count before id
        pat2 = rf'{re.escape(field_name)}:\s*\{{count:\s*(\d+),\s*id:\s*"minecraft:([^"]+)"\}}'
        m2 = re.search(pat2, recipe)
        if m2:
            return m2.group(2), int(m2.group(1))
        return None, None

    buy_item, buy_count = item_and_count("buy")
    sell_item, sell_count = item_and_count("sell")
    buy_b_item, buy_b_count = item_and_count("buyB")

    price_mult = _scalar(r'priceMultiplier:\s*([-\d.]+)f', recipe, float, 0.0)
    max_uses = _scalar(r'maxUses:\s*(\d+)', recipe, int, 0)
    xp = _scalar(r'(?<![a-zA-Z])xp:\s*(\d+)', recipe, int, 0)

    return {
        "slot": slot,
        "buy_item": buy_item,
        "buy_count": buy_count,
        "buy_b_item": buy_b_item,
        "buy_b_count": buy_b_count,
        "sell_item": sell_item,
        "sell_count": sell_count,
        "price_multiplier": price_mult,
        "max_uses": max_uses,
        "xp": xp,
    }


def _parse_inventory(snbt):
    """Extract Inventory: [{id: ..., count: N}, ...] items."""
    m = re.search(r'Inventory:\s*\[([^\]]*)\]', snbt)
    if not m:
        return []
    content = m.group(1).strip()
    if not content:
        return []

    items = []
    for item_m in re.finditer(r'\{id:\s*"minecraft:([^"]+)",\s*count:\s*(\d+)\}', content):
        items.append({"item": item_m.group(1), "count": int(item_m.group(2))})
    return items


def _parse_gossip(snbt):
    """Extract Gossips: [{Type: ..., Target: [I; ...], Value: N}, ...]."""
    m = re.search(r'Gossips:\s*(\[)', snbt)
    if not m:
        return []
    content = _extract_balanced(snbt, m.start(1), open_char="[", close_char="]")
    if content is None:
        return []
    content = content.strip()
    if not content:
        return []

    gossip_list = []
    # Find each gossip entry as a {...} block
    depth = 0
    start = None
    for i, ch in enumerate(content):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                entry = content[start:i + 1]
                g = _parse_gossip_entry(entry)
                if g:
                    gossip_list.append(g)
                start = None
    return gossip_list


def _parse_gossip_entry(entry):
    """Parse one gossip entry block."""
    type_m = re.search(r'Type:\s*"([^"]+)"', entry)
    value_m = re.search(r'Value:\s*(\d+)', entry)
    target_m = re.search(r'Target:\s*(\[I;[^\]]+\])', entry)

    if not (type_m and value_m and target_m):
        return None

    arr = _int_array(target_m.group(1))
    target_uuid = ints_to_uuid(arr) if arr and len(arr) == 4 else None

    return {
        "gossip_type": type_m.group(1),
        "target_uuid": target_uuid,
        "value": int(value_m.group(1)),
    }


def parse_entity_line(line):
    """Parse a full server log line with villager entity data.

    Returns a dict with all extracted fields.
    """
    # Strip the log prefix and extract the raw SNBT block
    m = re.search(r'entity data:\s*(\{.+\})\s*$', line, re.DOTALL)
    if not m:
        raise ValueError(f"Could not find entity data in line: {line[:80]}")
    snbt = m.group(1)

    # UUID
    uuid_m = re.search(r'UUID:\s*(\[I;[^\]]+\])', snbt)
    uuid_ints = _int_array(uuid_m.group(1)) if uuid_m else None
    uuid = ints_to_uuid(uuid_ints) if uuid_ints else None

    # Position and origin
    pos_x, pos_y, pos_z = _parse_pos_array("Pos", snbt)
    origin_x, origin_y, origin_z = _parse_pos_array("Paper.Origin", snbt)

    # Spawn reason
    spawn_reason = _scalar(r'Paper\.SpawnReason:\s*"([^"]+)"', snbt)

    # VillagerData
    profession = _scalar(r'profession:\s*"minecraft:([^"]+)"', snbt)
    profession_level = _scalar(r'VillagerData:[^}]*level:\s*(\d+)', snbt, int)
    villager_type = _scalar(r'VillagerData:\s*\{type:\s*"minecraft:([^"]+)"', snbt)

    # Health and food
    health = _scalar(r'Health:\s*([-\d.]+)f', snbt, float)
    food_level = _scalar(r'FoodLevel:\s*(\d+)b', snbt, int)

    # XP, ticks, age, ground
    xp = _scalar(r'(?<![a-zA-Z])Xp:\s*(\d+)', snbt, int)
    ticks_lived = _scalar(r'Spigot\.ticksLived:\s*(\d+)', snbt, int)
    age = _scalar(r'(?<![a-zA-Z])Age:\s*(-?\d+)', snbt, int)
    on_ground = _scalar(r'OnGround:\s*(\d+)b', snbt, int)

    # Commerce / trading fields
    restocks_today = _scalar(r'RestocksToday:\s*(\d+)', snbt, int)
    last_restock = _scalar(r'LastRestock:\s*([-\d]+)L', snbt, int)
    last_gossip_decay = _scalar(r'LastGossipDecay:\s*([-\d]+)L', snbt, int)

    # Brain memories
    brain_text = _extract_brain(snbt)
    home_x, home_y, home_z = _parse_brain_pos("minecraft:home", brain_text)
    job_site_x, job_site_y, job_site_z = _parse_brain_pos("minecraft:job_site", brain_text)
    meeting_x, meeting_y, meeting_z = _parse_brain_pos("minecraft:meeting_point", brain_text)
    last_slept = _parse_brain_long("minecraft:last_slept", brain_text)
    last_woken = _parse_brain_long("minecraft:last_woken", brain_text)
    last_worked = _parse_brain_long("minecraft:last_worked_at_poi", brain_text)

    # Nested collections
    trades = _parse_trades(snbt)
    inventory = _parse_inventory(snbt)
    gossip = _parse_gossip(snbt)

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
