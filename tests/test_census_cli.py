"""Tests for the census.py CLI (main function)."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import census
from census_db import init_db


SAMPLE_TOML = b"""\
[places.testville]
poi_regions = [[1, 2]]

[[places.testville.zones]]
name = "center"
center = [100, 200]
radius = 50

[[places.testville.zones]]
name = "outskirts"
corners = [[200, 200], [300, 300]]

[places.hamlet]
poi_regions = [[3, 4]]

[[places.hamlet.zones]]
name = "square"
corners = [[0, 0], [50, 50]]
"""

MOCK_SUMMARY = {
    "snapshot_id": 1,
    "timestamp": "2026-04-04T12:00:00+00:00",
    "villager_count": 10,
    "bed_count": 8,
    "bell_count": 1,
    "births": 2,
    "deaths": 1,
    "homeless": 3,
    "players_online": ["Termiduck"],
    "zones": {"center": {"villagers": 10, "beds": 8, "bells": 1}},
}


@pytest.fixture
def toml_file(tmp_path):
    p = tmp_path / "zones.toml"
    p.write_bytes(SAMPLE_TOML)
    return str(p)


@pytest.fixture
def db_file():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        return f.name


# --- --config ---

def test_cli_config_first_place(toml_file, db_file, capsys):
    """--config without --place uses the first place in the file."""
    with (
        patch("sys.argv", ["census.py", "--config", toml_file, "--db", db_file]),
        patch("census.save_all"),
        patch("census.get_entity_mtimes", return_value={"r.1.2.mca": 9999}),
        patch("census.entity_region_coords", return_value=[(1, 2)]),
        patch("census.run_census", return_value=MOCK_SUMMARY) as mock_run,
    ):
        census.main()

    zones = mock_run.call_args.kwargs["zones"]
    assert len(zones) == 2
    assert zones[0]["name"] == "center"
    assert zones[1]["name"] == "outskirts"
    assert mock_run.call_args.kwargs["poi_regions"] == [(1, 2)]


def test_cli_config_with_place(toml_file, db_file):
    """--config --place selects the named place."""
    with (
        patch("sys.argv", ["census.py", "--config", toml_file, "--place", "hamlet", "--db", db_file]),
        patch("census.save_all"),
        patch("census.get_entity_mtimes", return_value={"r.1.2.mca": 9999}),
        patch("census.entity_region_coords", return_value=[(1, 2)]),
        patch("census.run_census", return_value=MOCK_SUMMARY) as mock_run,
    ):
        census.main()

    zones = mock_run.call_args.kwargs["zones"]
    assert zones[0]["name"] == "square"
    assert zones[0]["type"] == "rect"


# --- --center ---

def test_cli_center_with_radius(db_file):
    """--center x,z --radius R creates a circle zone."""
    with (
        patch("sys.argv", ["census.py", "--center", "3150,-950", "--radius", "300",
                           "--name", "piwigord", "--db", db_file]),
        patch("census.save_all"),
        patch("census.get_entity_mtimes", return_value={"r.1.2.mca": 9999}),
        patch("census.entity_region_coords", return_value=[(1, 2)]),
        patch("census.run_census", return_value=MOCK_SUMMARY) as mock_run,
    ):
        census.main()

    zones = mock_run.call_args.kwargs["zones"]
    assert len(zones) == 1
    assert zones[0]["name"] == "piwigord"
    assert zones[0]["type"] == "circle"
    assert zones[0]["center_x"] == 3150
    assert zones[0]["center_z"] == -950
    assert zones[0]["radius"] == 300


def test_cli_center_default_name(db_file):
    """--center without --name generates a name from coordinates."""
    with (
        patch("sys.argv", ["census.py", "--center", "100,-200", "--radius", "50", "--db", db_file]),
        patch("census.save_all"),
        patch("census.get_entity_mtimes", return_value={"r.1.2.mca": 9999}),
        patch("census.entity_region_coords", return_value=[(1, 2)]),
        patch("census.run_census", return_value=MOCK_SUMMARY) as mock_run,
    ):
        census.main()

    assert mock_run.call_args.kwargs["zones"][0]["name"] == "scan-100--200"


def test_cli_center_without_radius_errors(db_file):
    """--center without --radius is an error."""
    with (
        patch("sys.argv", ["census.py", "--center", "100,-200", "--db", db_file]),
        pytest.raises(SystemExit),
    ):
        census.main()


def test_cli_center_bad_format_errors(db_file):
    """--center with wrong format is an error."""
    with (
        patch("sys.argv", ["census.py", "--center", "100", "--radius", "50", "--db", db_file]),
        pytest.raises(SystemExit),
    ):
        census.main()


# --- --rect ---

def test_cli_rect(db_file):
    """--rect creates a rect zone."""
    with (
        patch("sys.argv", ["census.py", "--rect", "0,-100,200,0", "--name", "area", "--db", db_file]),
        patch("census.save_all"),
        patch("census.get_entity_mtimes", return_value={"r.1.2.mca": 9999}),
        patch("census.entity_region_coords", return_value=[(1, 2)]),
        patch("census.run_census", return_value=MOCK_SUMMARY) as mock_run,
    ):
        census.main()

    zones = mock_run.call_args.kwargs["zones"]
    assert zones[0]["type"] == "rect"
    assert zones[0]["name"] == "area"
    assert zones[0]["x_min"] == 0
    assert zones[0]["z_min"] == -100
    assert zones[0]["x_max"] == 200
    assert zones[0]["z_max"] == 0


def test_cli_rect_with_radius_errors(db_file):
    """--rect --radius is an error."""
    with (
        patch("sys.argv", ["census.py", "--rect", "0,0,100,100", "--radius", "50", "--db", db_file]),
        pytest.raises(SystemExit),
    ):
        census.main()


def test_cli_rect_bad_format_errors(db_file):
    """--rect with wrong number of values is an error."""
    with (
        patch("sys.argv", ["census.py", "--rect", "0,0,100", "--db", db_file]),
        pytest.raises(SystemExit),
    ):
        census.main()


# --- --export-json ---

def test_cli_export_json(db_file, capsys):
    """--export-json dumps the DB as JSON."""
    # Create a DB with one snapshot so there's data to export
    from census_db import init_db, insert_snapshot
    conn = init_db(db_file)
    insert_snapshot(conn, timestamp="2026-04-04T00:00:00Z", players_online="[]",
                    area_center_x=0, area_center_z=0, scan_radius=100,
                    villager_count=0, bed_count=0, notes=None)
    conn.close()

    with patch("sys.argv", ["census.py", "--export-json", "--db", db_file]):
        census.main()

    output = capsys.readouterr().out
    data = json.loads(output)
    assert "snapshots" in data
    assert len(data["snapshots"]) == 1


# --- no mode ---

def test_cli_no_mode_errors():
    """No --config, --center, or --rect is an error."""
    with (
        patch("sys.argv", ["census.py", "--db", "test.db"]),
        pytest.raises(SystemExit),
    ):
        census.main()


# --- --poi-regions ---

def test_cli_poi_regions_parsed(db_file):
    """--poi-regions string is parsed into tuples."""
    with (
        patch("sys.argv", ["census.py", "--center", "0,0", "--radius", "10",
                           "--poi-regions", "5,-3;6,-2", "--db", db_file]),
        patch("census.save_all"),
        patch("census.get_entity_mtimes", return_value={"r.1.2.mca": 9999}),
        patch("census.entity_region_coords", return_value=[(1, 2)]),
        patch("census.run_census", return_value=MOCK_SUMMARY) as mock_run,
    ):
        census.main()

    assert mock_run.call_args.kwargs["poi_regions"] == [(5, -3), (6, -2)]


# --- summary output ---

def test_cli_prints_zone_table(db_file, capsys):
    """CLI prints a zone breakdown table."""
    with (
        patch("sys.argv", ["census.py", "--center", "0,0", "--radius", "10", "--db", db_file]),
        patch("census.save_all"),
        patch("census.get_entity_mtimes", return_value={"r.1.2.mca": 9999}),
        patch("census.entity_region_coords", return_value=[(1, 2)]),
        patch("census.run_census", return_value=MOCK_SUMMARY),
    ):
        census.main()

    output = capsys.readouterr().out
    assert "| center | 10 | 8 |" in output
    assert "Population" in output


# --- mtime noop gate ---

def test_cli_skips_when_mtimes_unchanged(toml_file, db_file, capsys):
    """When entity file mtimes match the last run, census is skipped."""
    conn = init_db(db_file)
    from census_db import insert_census_run
    insert_census_run(conn, timestamp="2026-04-04T00:00:00Z", status="completed",
                      entity_mtimes='{"r.6.-3.mca": 1000, "r.6.-2.mca": 2000}')
    conn.close()

    with (
        patch("sys.argv", ["census.py", "--config", toml_file, "--db", db_file]),
        patch("census.save_all"),
        patch("census.get_entity_mtimes", return_value={"r.6.-3.mca": 1000, "r.6.-2.mca": 2000}),
        patch("census.entity_region_coords", return_value=[(6, -3), (6, -2)]),
        patch("census.run_census") as mock_run,
    ):
        census.main()

    mock_run.assert_not_called()
    output = capsys.readouterr().out
    assert "Skipped" in output


def test_cli_runs_when_mtimes_changed(toml_file, db_file):
    """When entity file mtimes differ from last run, full census runs."""
    conn = init_db(db_file)
    from census_db import insert_census_run
    insert_census_run(conn, timestamp="2026-04-04T00:00:00Z", status="completed",
                      entity_mtimes='{"r.6.-3.mca": 1000, "r.6.-2.mca": 2000}')
    conn.close()

    with (
        patch("sys.argv", ["census.py", "--config", toml_file, "--db", db_file]),
        patch("census.save_all"),
        patch("census.get_entity_mtimes", return_value={"r.6.-3.mca": 1000, "r.6.-2.mca": 3000}),
        patch("census.entity_region_coords", return_value=[(6, -3), (6, -2)]),
        patch("census.run_census", return_value=MOCK_SUMMARY) as mock_run,
    ):
        census.main()

    mock_run.assert_called_once()


def test_cli_runs_on_first_run(toml_file, db_file):
    """First run (no previous mtimes) always proceeds."""
    with (
        patch("sys.argv", ["census.py", "--config", toml_file, "--db", db_file]),
        patch("census.save_all"),
        patch("census.get_entity_mtimes", return_value={"r.1.2.mca": 1000}),
        patch("census.entity_region_coords", return_value=[(1, 2)]),
        patch("census.run_census", return_value=MOCK_SUMMARY) as mock_run,
    ):
        census.main()

    mock_run.assert_called_once()


# --- --install / --uninstall ---

def test_cli_install_cron(toml_file, db_file, capsys):
    """--install adds a cron entry with the correct schedule and command."""
    import subprocess
    installed_crontab = []

    def fake_run(cmd, **kwargs):
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="# existing job\n")
        if cmd == ["crontab", "-"]:
            installed_crontab.append(kwargs.get("input", ""))
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sys.argv", ["census.py", "--config", toml_file, "--install", "15", "--db", db_file]),
        patch("census.subprocess.run", side_effect=fake_run),
    ):
        census.main()

    output = capsys.readouterr().out
    assert "every 15 min" in output

    crontab = installed_crontab[0]
    assert "*/15 * * * *" in crontab
    assert "--lazy" not in crontab  # force mode by default
    assert "--config" in crontab
    assert "# villager-census" in crontab
    # Existing entries preserved
    assert "# existing job" in crontab


def test_cli_install_default_30min(toml_file, db_file, capsys):
    """--install without a value defaults to 30 min."""
    import subprocess

    installed_crontab = []

    def fake_run(cmd, **kwargs):
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd == ["crontab", "-"]:
            installed_crontab.append(kwargs.get("input", ""))
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sys.argv", ["census.py", "--config", toml_file, "--install", "--db", db_file]),
        patch("census.subprocess.run", side_effect=fake_run),
    ):
        census.main()

    assert "*/30 * * * *" in installed_crontab[0]


def test_cli_install_replaces_existing(toml_file, db_file):
    """--install replaces an existing census cron entry."""
    import subprocess

    installed_crontab = []
    old_crontab = "*/60 * * * * /old/command # villager-census\n# other job\n"

    def fake_run(cmd, **kwargs):
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=old_crontab)
        if cmd == ["crontab", "-"]:
            installed_crontab.append(kwargs.get("input", ""))
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sys.argv", ["census.py", "--config", toml_file, "--install", "--db", db_file]),
        patch("census.subprocess.run", side_effect=fake_run),
    ):
        census.main()

    crontab = installed_crontab[0]
    assert "/old/command" not in crontab
    assert "# other job" in crontab
    assert crontab.count("# villager-census") == 1


def test_cli_uninstall_cron(capsys):
    """--uninstall removes the census cron entry."""
    import subprocess

    installed_crontab = []
    existing = "# other job\n*/30 * * * * /some/cmd # villager-census\n"

    def fake_run(cmd, **kwargs):
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=existing)
        if cmd == ["crontab", "-"]:
            installed_crontab.append(kwargs.get("input", ""))
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sys.argv", ["census.py", "--uninstall"]),
        patch("census.subprocess.run", side_effect=fake_run),
    ):
        census.main()

    output = capsys.readouterr().out
    assert "Removed" in output
    assert "# villager-census" not in installed_crontab[0]
    assert "# other job" in installed_crontab[0]


def test_cli_uninstall_no_crontab(capsys):
    """--uninstall with no crontab prints a message."""
    import subprocess

    def fake_run(cmd, **kwargs):
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="")
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sys.argv", ["census.py", "--uninstall"]),
        patch("census.subprocess.run", side_effect=fake_run),
    ):
        census.main()

    assert "No crontab found" in capsys.readouterr().out


def test_cli_uninstall_no_entry(capsys):
    """--uninstall with no census entry prints a message."""
    import subprocess

    def fake_run(cmd, **kwargs):
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="# other stuff\n")
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sys.argv", ["census.py", "--uninstall"]),
        patch("census.subprocess.run", side_effect=fake_run),
    ):
        census.main()

    assert "No villager-census cron job found" in capsys.readouterr().out


def test_cli_install_uses_absolute_paths(toml_file, db_file):
    """--install resolves config and db to absolute paths in the cron command."""
    import subprocess

    installed_crontab = []

    def fake_run(cmd, **kwargs):
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd == ["crontab", "-"]:
            installed_crontab.append(kwargs.get("input", ""))
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("sys.argv", ["census.py", "--config", toml_file, "--install", "--db", db_file]),
        patch("census.subprocess.run", side_effect=fake_run),
    ):
        census.main()

    crontab = installed_crontab[0]
    # All paths should be absolute (start with /)
    for part in crontab.split():
        if part.startswith("--"):
            continue
        if "/" in part and not part.startswith("*"):
            assert part.startswith("/") or part.startswith("#"), f"Non-absolute path: {part}"
