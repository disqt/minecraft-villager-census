"""Tests for census_collect.py — SSH/tmux data collection module."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import census_collect
from census_collect import (
    check_players_online,
    get_player_position,
    parse_death_log,
    save_all,
    get_entity_files,
    get_entity_mtimes,
    entity_region_coords,
)
from census_zones import make_single_zone

SAMPLE_LIST_OUTPUT = "[19:20:22] [Server thread/INFO]: There are 1 of a max of 20 players online: Termiduck"
SAMPLE_LIST_EMPTY = "[19:20:22] [Server thread/INFO]: There are 0 of a max of 20 players online: "
SAMPLE_POS_OUTPUT = "[19:20:31] [Server thread/INFO]: Termiduck has the following entity data: [3159.209198957126d, 58.0d, -930.0230847671345d]"
SAMPLE_DEATH_LINE = "[19:54:24] [Server thread/INFO]: Villager Villager['Villager'/15678, uuid='d68d9d96-4802-4899-9b8e-bb8709eda5c0', l='ServerLevel[world_new]', x=3145.37, y=63.00, z=-965.30, cpos=[196, -61], tl=59771, v=true] died, message: 'Villager was killed'"
SAMPLE_DEATH_LINE_NAMED = "[18:32:16] [Server thread/INFO]: Villager Villager['Villager'/214, uuid='0a077d31-a230-41b5-bf50-c74d83892338', l='ServerLevel[world_new]', x=3158.63, y=64.00, z=-917.15, cpos=[197, -58], tl=708, v=true] died, message: 'Villager hit the ground too hard'"


# --- parse_death_log ---

def test_parse_death_log_extracts_fields():
    result = parse_death_log(SAMPLE_DEATH_LINE)
    assert result is not None
    assert result["uuid"] == "d68d9d96-4802-4899-9b8e-bb8709eda5c0"
    assert result["x"] == pytest.approx(3145.37)
    assert result["y"] == pytest.approx(63.0)
    assert result["z"] == pytest.approx(-965.30)
    assert result["ticks_lived"] == 59771
    assert result["message"] == "Villager was killed"


def test_parse_death_log_hit_ground():
    result = parse_death_log(SAMPLE_DEATH_LINE_NAMED)
    assert result is not None
    assert result["uuid"] == "0a077d31-a230-41b5-bf50-c74d83892338"
    assert result["ticks_lived"] == 708
    assert result["message"] == "Villager hit the ground too hard"


def test_parse_death_log_returns_none_on_non_match():
    result = parse_death_log("[19:20:22] [Server thread/INFO]: Some other log line")
    assert result is None


# --- check_players_online ---

def test_check_players_online():
    with patch("census_collect._run_command", return_value=[SAMPLE_LIST_OUTPUT]):
        players = check_players_online()
    assert players == ["Termiduck"]


def test_check_players_online_empty():
    with patch("census_collect._run_command", return_value=[SAMPLE_LIST_EMPTY]):
        players = check_players_online()
    assert players == []


def test_check_players_online_multiple():
    line = "[19:20:22] [Server thread/INFO]: There are 3 of a max of 20 players online: Alice, Bob, Charlie"
    with patch("census_collect._run_command", return_value=[line]):
        players = check_players_online()
    assert players == ["Alice", "Bob", "Charlie"]


# --- get_player_position ---

def test_get_player_position():
    with patch("census_collect._tail_log_after_command", return_value=[SAMPLE_POS_OUTPUT]):
        pos = get_player_position("Termiduck")
    assert pos is not None
    x, y, z = pos
    assert x == pytest.approx(3159.21, rel=1e-3)
    assert y == pytest.approx(58.0)
    assert z == pytest.approx(-930.02, rel=1e-3)


def test_get_player_position_not_found():
    with patch("census_collect._tail_log_after_command", return_value=["some unrelated log line"]):
        pos = get_player_position("Termiduck")
    assert pos is None


# --- save_all ---

def test_save_all_waits_for_confirmation():
    """save_all sends marker + 'save-all', returns when log shows marker then 'Saved the game'."""
    sent = []

    def fake_run(cmd):
        return [
            "[12:00:00] [Server thread/INFO]: [Server] SAVEALL_100",
            "[12:00:01] [Server thread/INFO]: Saved the game",
        ]

    with (
        patch("census_collect._send_tmux", side_effect=lambda cmd: sent.append(cmd)),
        patch("census_collect._run_command", side_effect=fake_run),
        patch("census_collect.time.sleep"),
        patch("census_collect.time.time", side_effect=[100, 100, 101]),
    ):
        save_all(timeout=30)

    assert any("SAVEALL_100" in s for s in sent)
    assert "save-all" in sent


def test_save_all_timeout():
    """save_all raises TimeoutError if 'Saved the game' never appears after marker."""
    def fake_run(cmd):
        # Marker present but no "Saved the game" after it
        return [
            "[12:00:00] [Server thread/INFO]: [Server] SAVEALL_200",
            "[12:00:01] Some other line",
        ]

    with (
        patch("census_collect._send_tmux"),
        patch("census_collect._run_command", side_effect=fake_run),
        patch("census_collect.time.sleep"),
        patch("census_collect.time.time", side_effect=[200, 200, 231]),
    ):
        with pytest.raises(TimeoutError):
            save_all(timeout=30)


# --- get_entity_mtimes ---

def test_get_entity_mtimes():
    """get_entity_mtimes parses stat output into {filename: mtime} dict."""
    stat_output = [
        "1712200000 r.6.-3.mca",
        "1712200100 r.6.-2.mca",
    ]

    with patch("census_collect._run_command", return_value=stat_output):
        result = get_entity_mtimes([(6, -3), (6, -2)])

    assert result == {
        "r.6.-3.mca": 1712200000,
        "r.6.-2.mca": 1712200100,
    }


# --- get_entity_files (SSH mode) ---

def test_get_entity_files_ssh():
    """get_entity_files downloads files via SCP when _ssh_host is set."""
    original_ssh_host = census_collect._ssh_host
    census_collect._ssh_host = "minecraft"

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_dir = Path(tmpdir)

            def fake_scp(cmd, **kwargs):
                # Simulate SCP by creating the target file
                target = cmd[-1]
                Path(target).write_bytes(b"fake mca data")
                result = MagicMock()
                result.returncode = 0
                return result

            with patch("subprocess.run", side_effect=fake_scp):
                paths = get_entity_files([(6, -3)], local_dir)

            assert len(paths) == 1
            assert paths[0].name == "r.6.-3.mca"
    finally:
        census_collect._ssh_host = original_ssh_host


# --- entity_region_coords ---

def test_entity_region_coords():
    """entity_region_coords returns correct region coords for a rect zone."""
    zones = [{"name": "a", "type": "rect", "x_min": 3090, "z_min": -1040, "x_max": 3220, "z_max": -826}]
    result = entity_region_coords(zones)
    # 3090 // 512 = 6, 3220 // 512 = 6
    # -1040 // 512 = -3 (Python floor div), -826 // 512 = -2
    assert (6, -3) in result
    assert (6, -2) in result


def test_entity_region_coords_circle():
    """entity_region_coords works for circle zones."""
    zones = [make_single_zone(center_x=3150, center_z=-950, radius=300)]
    result = entity_region_coords(zones)
    assert len(result) > 0
