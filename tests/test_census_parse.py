"""Tests for census_parse.py — SNBT parser for villager entity data."""

import pytest
from census_parse import ints_to_uuid, parse_entity_line

SAMPLE_LINE = (
    "[19:44:53] [Server thread/INFO]: Fisherman has the following entity data: "
    "{Paper.SpawnReason: \"BREEDING\", DeathTime: 0s, Bukkit.updateLevel: 2, RestocksToday: 0, "
    "Xp: 0, OnGround: 1b, LeftHanded: 0b, AbsorptionAmount: 0.0f, FoodLevel: 0b, "
    "LastRestock: 1001127489L, AgeLocked: 0b, Invulnerable: 0b, "
    "Brain: {memories: {\"minecraft:last_woken\": {value: 1018112423L}, "
    "\"minecraft:job_site\": {value: {pos: [I; 3172, 70, -754], dimension: \"minecraft:overworld\"}}, "
    "\"minecraft:last_slept\": {value: 1018111156L}, "
    "\"minecraft:last_worked_at_poi\": {value: 1001132966L}, "
    "\"minecraft:meeting_point\": {value: {pos: [I; 3170, 66, -883], dimension: \"minecraft:overworld\"}}}}, "
    "Paper.Origin: [3145.9453962812213d, 63.9375d, -1006.4578843209587d], Age: 0, "
    "Rotation: [44.46672f, 0.0f], HurtByTimestamp: 0, Bukkit.Aware: 1b, ForcedAge: 0, "
    "attributes: [{base: 0.5d, id: \"minecraft:movement_speed\"}, {base: 16.0d, id: \"minecraft:follow_range\", "
    "modifiers: [{operation: \"add_multiplied_base\", amount: -0.04554609496891499d, id: \"minecraft:random_spawn_bonus\"}]}], "
    "WorldUUIDMost: -8821679170295479734L, fall_distance: 0.0d, Air: 300s, "
    "Offers: {Recipes: [{buy: {id: \"minecraft:emerald\", count: 1}, sell: {id: \"minecraft:cooked_cod\", count: 6}, "
    "priceMultiplier: 0.05f, buyB: {id: \"minecraft:cod\", count: 6}, maxUses: 16}, "
    "{xp: 2, buy: {id: \"minecraft:string\", count: 20}, sell: {id: \"minecraft:emerald\", count: 1}, "
    "priceMultiplier: 0.05f, maxUses: 16}]}, "
    "UUID: [I; 346464738, -1288157012, -1558611273, 949520682], "
    "Inventory: [{id: \"minecraft:beetroot\", count: 2}, {id: \"minecraft:beetroot_seeds\", count: 7}, "
    "{id: \"minecraft:wheat_seeds\", count: 2}], "
    "Spigot.ticksLived: 821095, Paper.OriginWorld: [I; -2053957240, -1408023990, -1113309832, -1718626039], "
    "Gossips: [], VillagerData: {type: \"minecraft:taiga\", profession: \"minecraft:fisherman\", level: 1}, "
    "WorldUUIDLeast: -4781629316178913015L, Motion: [0.0d, -0.0784000015258789d, 0.0d], "
    "Pos: [3173.038130397757d, 70.0d, -755.0478646574805d], Fire: 0s, CanPickUpLoot: 1b, "
    "Health: 16.0f, HurtTime: 0s, FallFlying: 0b, PersistenceRequired: 0b, "
    "LastGossipDecay: 1024984001L, PortalCooldown: 0}"
)

SAMPLE_LINE_WITH_GOSSIP = (
    "[19:44:53] [Server thread/INFO]: Villager has the following entity data: "
    "{Paper.SpawnReason: \"DEFAULT\", DeathTime: 0s, Bukkit.updateLevel: 2, RestocksToday: 0, "
    "Xp: 0, OnGround: 1b, LeftHanded: 0b, AbsorptionAmount: 0.0f, FoodLevel: 0b, "
    "LastRestock: 991883132L, AgeLocked: 0b, Invulnerable: 0b, "
    "Brain: {memories: {\"minecraft:last_worked_at_poi\": {value: 991884047L}}}, "
    "Paper.Origin: [135.74785481367292d, 66.0d, 223.8206487666246d], Age: 0, "
    "Rotation: [92.51944f, 0.0f], HurtByTimestamp: 0, Bukkit.Aware: 1b, ForcedAge: 0, "
    "attributes: [{base: 20.0d, id: \"minecraft:max_health\"}, {base: 0.5d, id: \"minecraft:movement_speed\"}, "
    "{base: 16.0d, id: \"minecraft:follow_range\", modifiers: [{operation: \"add_multiplied_base\", "
    "amount: 0.026338384861324084d, id: \"minecraft:random_spawn_bonus\"}]}], "
    "WorldUUIDMost: -8821679170295479734L, fall_distance: 0.0d, Air: 300s, "
    "UUID: [I; -1857840997, 1245274443, -1362517790, 67902458], Inventory: [], "
    "Spigot.ticksLived: 3703310, Paper.OriginWorld: [I; -1845599319, -946321560, -1589277455, 1153834771], "
    "Gossips: [{Type: \"minor_negative\", Target: [I; -2075606571, 174605987, -2012950428, -563128421], Value: 5}, "
    "{Type: \"major_negative\", Target: [I; 456626118, 894125023, -1403978413, 486402248], Value: 25}], "
    "VillagerData: {type: \"minecraft:plains\", profession: \"minecraft:none\", level: 1}, "
    "WorldUUIDLeast: -4781629316178913015L, Motion: [0.0d, -0.0784000015258789d, 0.0d], "
    "Pos: [3177.0658599948592d, 70.0d, -763.9250000119209d], Fire: 0s, CanPickUpLoot: 1b, "
    "Health: 12.0f, HurtTime: 0s, FallFlying: 0b, PersistenceRequired: 0b, "
    "LastGossipDecay: 1025345203L, PortalCooldown: 0}"
)


def test_ints_to_uuid():
    result = ints_to_uuid([346464738, -1288157012, -1558611273, 949520682])
    # 346464738   -> 0x14a6a1e2
    # -1288157012 -> 0xb33848ac
    # -1558611273 -> 0xa3197ab7
    # 949520682   -> 0x3898892a
    assert result == "14a6a1e2-b338-48ac-a319-7ab73898892a"


def test_parse_core_fields():
    data = parse_entity_line(SAMPLE_LINE)
    assert data["uuid"] == "14a6a1e2-b338-48ac-a319-7ab73898892a"
    assert data["profession"] == "fisherman"
    assert data["profession_level"] == 1
    assert data["villager_type"] == "taiga"
    assert data["spawn_reason"] == "BREEDING"
    assert data["health"] == pytest.approx(16.0)
    assert data["food_level"] == 0
    assert data["ticks_lived"] == 821095
    assert data["age"] == 0
    assert data["on_ground"] == 1
    assert data["xp"] == 0
    assert data["restocks_today"] == 0


def test_parse_position():
    data = parse_entity_line(SAMPLE_LINE)
    assert data["pos_x"] == pytest.approx(3173.04, rel=1e-3)
    assert data["pos_y"] == pytest.approx(70.0)
    assert data["pos_z"] == pytest.approx(-755.05, rel=1e-3)


def test_parse_origin():
    data = parse_entity_line(SAMPLE_LINE)
    assert data["origin_x"] == pytest.approx(3145.95, rel=1e-3)
    assert data["origin_y"] == pytest.approx(63.94, rel=1e-3)
    assert data["origin_z"] == pytest.approx(-1006.46, rel=1e-3)


def test_parse_brain_job_site():
    data = parse_entity_line(SAMPLE_LINE)
    assert data["job_site_x"] == 3172
    assert data["job_site_y"] == 70
    assert data["job_site_z"] == -754


def test_parse_brain_meeting_point():
    data = parse_entity_line(SAMPLE_LINE)
    assert data["meeting_point_x"] == 3170
    assert data["meeting_point_y"] == 66
    assert data["meeting_point_z"] == -883


def test_parse_brain_no_home():
    data = parse_entity_line(SAMPLE_LINE)
    assert data["home_x"] is None
    assert data["home_y"] is None
    assert data["home_z"] is None


def test_parse_brain_sleep_ticks():
    data = parse_entity_line(SAMPLE_LINE)
    assert data["last_slept"] == 1018111156
    assert data["last_woken"] == 1018112423
    assert data["last_worked"] == 1001132966


def test_parse_trades():
    data = parse_entity_line(SAMPLE_LINE)
    trades = data["trades"]
    assert len(trades) == 2

    t0 = trades[0]
    assert t0["buy_item"] == "emerald"
    assert t0["buy_count"] == 1
    assert t0["sell_item"] == "cooked_cod"
    assert t0["sell_count"] == 6
    assert t0["buy_b_item"] == "cod"
    assert t0["buy_b_count"] == 6

    t1 = trades[1]
    assert t1["buy_item"] == "string"
    assert t1["buy_count"] == 20
    assert t1["sell_item"] == "emerald"
    assert t1["sell_count"] == 1


def test_parse_inventory():
    data = parse_entity_line(SAMPLE_LINE)
    inv = data["inventory"]
    assert len(inv) == 3
    assert inv[0] == {"item": "beetroot", "count": 2}
    assert inv[1] == {"item": "beetroot_seeds", "count": 7}
    assert inv[2] == {"item": "wheat_seeds", "count": 2}


def test_parse_empty_inventory():
    data = parse_entity_line(SAMPLE_LINE_WITH_GOSSIP)
    assert data["inventory"] == []


def test_parse_gossip():
    data = parse_entity_line(SAMPLE_LINE_WITH_GOSSIP)
    gossip = data["gossip"]
    assert len(gossip) == 2

    g0 = gossip[0]
    assert g0["gossip_type"] == "minor_negative"
    assert g0["value"] == 5
    assert isinstance(g0["target_uuid"], str)
    assert len(g0["target_uuid"]) == 36  # uuid format: 8-4-4-4-12

    g1 = gossip[1]
    assert g1["gossip_type"] == "major_negative"
    assert g1["value"] == 25


def test_parse_empty_gossip():
    data = parse_entity_line(SAMPLE_LINE)
    assert data["gossip"] == []


def test_parse_last_gossip_decay():
    data = parse_entity_line(SAMPLE_LINE)
    assert data["last_gossip_decay"] == 1024984001


def test_parse_last_restock():
    data = parse_entity_line(SAMPLE_LINE)
    assert data["last_restock"] == 1001127489


def test_parse_villager_type_plains():
    data = parse_entity_line(SAMPLE_LINE_WITH_GOSSIP)
    assert data["villager_type"] == "plains"
    assert data["profession"] == "none"
