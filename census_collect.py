"""census_collect.py — Data collection from PaperMC server (local or SSH)."""

import os
import re
import subprocess
import time
from pathlib import Path

# Defaults — assume local execution on the minecraft server
TMUX_SOCKET = "/tmp/tmux-1000/pmcserver-bb664df1"
TMUX_SESSION = "pmcserver"
LOG_PATH = "/home/minecraft/serverfiles/logs/latest.log"
POI_DIR = "/home/minecraft/serverfiles/world_new/poi"
ENTITY_DIR = "/home/minecraft/serverfiles/world_new/entities"

# Set via configure() — None means local mode
_ssh_host = None


def configure(*, ssh_host=None):
    """Set the transport mode. Call once at startup.

    ssh_host=None: local mode (default, for running on the VPS)
    ssh_host="minecraft": SSH mode (for running remotely)
    """
    global _ssh_host
    _ssh_host = ssh_host


def _run_command(cmd):
    """Run a command locally (as minecraft user) or via SSH, return stdout lines."""
    if _ssh_host:
        full_cmd = ["ssh", _ssh_host, cmd]
    else:
        full_cmd = ["sudo", "-u", "minecraft", "bash", "-c", cmd]
    result = subprocess.run(
        full_cmd, capture_output=True, text=True, timeout=30,
    )
    return result.stdout.splitlines()


def _send_tmux(command):
    """Send a command to the tmux session."""
    tmux_cmd = f"tmux -S {TMUX_SOCKET} send-keys -t {TMUX_SESSION} '{command}' Enter"
    if _ssh_host:
        full_cmd = ["ssh", _ssh_host, tmux_cmd]
    else:
        full_cmd = ["sudo", "-u", "minecraft", "bash", "-c", tmux_cmd]
    subprocess.run(full_cmd, capture_output=True, text=True, timeout=10)


def _tail_log_after_command(command, wait_seconds=5, tail_lines=200):
    """Send tmux command, sleep, then tail the server log. Return lines."""
    _send_tmux(command)
    time.sleep(wait_seconds)
    return _run_command(f"tail -n {tail_lines} {LOG_PATH}")


# ---------------------------------------------------------------------------
# High-level collection functions
# ---------------------------------------------------------------------------

def check_players_online():
    """Send 'list' command and return a list of online player names.

    Returns an empty list if no players are online.
    """
    lines = _run_command(f"tail -n 50 {LOG_PATH}")
    pattern = re.compile(
        r"There are (\d+) of a max of \d+ players online:(.*)"
    )
    for line in lines:
        m = pattern.search(line)
        if m:
            count = int(m.group(1))
            if count == 0:
                return []
            names_raw = m.group(2).strip()
            if not names_raw:
                return []
            return [n.strip() for n in names_raw.split(",") if n.strip()]
    return []


def get_player_position(player_name):
    """Return (x, y, z) for a player, or None if not found.

    Sends `data get entity <name> Pos` via tmux and parses the log output.
    """
    lines = _tail_log_after_command(f"data get entity {player_name} Pos")
    pattern = re.compile(
        re.escape(player_name)
        + r" has the following entity data: \[(-?[\d.]+)d, (-?[\d.]+)d, (-?[\d.]+)d\]"
    )
    for line in lines:
        m = pattern.search(line)
        if m:
            x, y, z = float(m.group(1)), float(m.group(2)), float(m.group(3))
            return (x, y, z)
    return None


def get_poi_files(region_coords, local_dir):
    """Get POI .mca files — copy locally or download via SCP.

    Returns a list of Path objects for files that were successfully obtained.
    """
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    for rx, rz in region_coords:
        filename = f"r.{rx}.{rz}.mca"
        local_path = local_dir / filename

        if _ssh_host:
            remote = f"{_ssh_host}:{POI_DIR}/{filename}"
            result = subprocess.run(
                ["scp", remote, str(local_path)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0 and local_path.exists():
                downloaded.append(local_path)
        else:
            source = Path(POI_DIR) / filename
            result = subprocess.run(
                ["sudo", "cp", str(source), str(local_path)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and local_path.exists():
                # Fix ownership so current user can read
                subprocess.run(["sudo", "chown", f"{os.getuid()}:{os.getgid()}", str(local_path)],
                               capture_output=True, timeout=5)
                downloaded.append(local_path)

    return downloaded


def save_all(timeout=30):
    """Send 'save-all' via tmux and wait for 'Saved the game' in the log.

    Uses a unique marker to avoid matching stale log lines from previous saves.
    """
    timestamp = int(time.time())
    marker = f"SAVEALL_{timestamp}"
    _send_tmux(f"say {marker}")
    time.sleep(0.5)
    _send_tmux("save-all")
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(2)
        lines = _run_command(f"tail -n 50 {LOG_PATH}")
        # Only look for "Saved the game" AFTER our marker
        after_marker = False
        for line in lines:
            if marker in line:
                after_marker = True
                continue
            if after_marker and "Saved the game" in line:
                return
    raise TimeoutError(f"save-all did not complete within {timeout}s")


def get_entity_files(region_coords, local_dir):
    """Get entity .mca files — copy locally or download via SCP.

    Returns a list of Path objects for files that were successfully obtained.
    """
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    for rx, rz in region_coords:
        filename = f"r.{rx}.{rz}.mca"
        local_path = local_dir / filename

        if _ssh_host:
            remote = f"{_ssh_host}:{ENTITY_DIR}/{filename}"
            result = subprocess.run(
                ["scp", remote, str(local_path)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0 and local_path.exists():
                downloaded.append(local_path)
        else:
            source = Path(ENTITY_DIR) / filename
            result = subprocess.run(
                ["sudo", "cp", str(source), str(local_path)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and local_path.exists():
                # Fix ownership so current user can read
                subprocess.run(["sudo", "chown", f"{os.getuid()}:{os.getgid()}", str(local_path)],
                               capture_output=True, timeout=5)
                downloaded.append(local_path)

    return downloaded


def get_entity_mtimes(region_coords):
    """Stat entity .mca files and return {filename: mtime_epoch} dict."""
    filenames = [f"r.{rx}.{rz}.mca" for rx, rz in region_coords]
    stat_cmd = " && ".join(
        f'stat -c "%Y {fn}" {ENTITY_DIR}/{fn}' for fn in filenames
    )
    lines = _run_command(stat_cmd)
    result = {}
    for line in lines:
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            mtime, fname = int(parts[0]), parts[1]
            result[fname] = mtime
    return result


def entity_region_coords(zones):
    """Compute the set of entity region (rx, rz) coords covering all zones."""
    from census_zones import bounding_box
    x_min, z_min, x_max, z_max = bounding_box(zones)
    regions = set()
    for x in range(x_min // 512, (x_max // 512) + 1):
        for z in range(z_min // 512, (z_max // 512) + 1):
            regions.add((x, z))
    return sorted(regions)


# ---------------------------------------------------------------------------
# Log parsing helpers
# ---------------------------------------------------------------------------

_DEATH_PATTERN = re.compile(
    r"Villager\[.*?uuid='([0-9a-f-]+)'.*?"
    r"x=(-?[\d.]+),\s*y=(-?[\d.]+),\s*z=(-?[\d.]+),\s*"
    r"cpos=\[.*?\],\s*tl=(\d+),.*?\]"
    r"\s+died,\s+message:\s+'(.+?)'"
)


def parse_death_log(line):
    """Parse a villager death log line.

    Returns a dict with keys: uuid, x, y, z, ticks_lived, message
    or None if the line does not match.
    """
    m = _DEATH_PATTERN.search(line)
    if not m:
        return None
    return {
        "uuid": m.group(1),
        "x": float(m.group(2)),
        "y": float(m.group(3)),
        "z": float(m.group(4)),
        "ticks_lived": int(m.group(5)),
        "message": m.group(6),
    }
