"""Tests for census_poi.py — POI region file parser."""

import io
import struct
import zlib
import pytest

from census_poi import parse_poi_region, parse_poi_regions


# ---------------------------------------------------------------------------
# NBT fixture builders
# ---------------------------------------------------------------------------

def _nbt_byte(value):
    return struct.pack(">b", value)

def _nbt_int(value):
    return struct.pack(">i", value)

def _nbt_string_payload(s):
    encoded = s.encode("utf-8")
    return struct.pack(">H", len(encoded)) + encoded

def _nbt_named_tag(tag_type, name, payload):
    """Encode a named NBT tag: type byte + name string + payload."""
    name_bytes = name.encode("utf-8")
    return struct.pack(">bH", tag_type, len(name_bytes)) + name_bytes + payload

def _nbt_compound_payload(named_tags):
    """Payload for a Compound: sequence of named tags + TAG_End."""
    return b"".join(named_tags) + b"\x00"

def _nbt_list_payload(item_type, items_payload_list):
    """Payload for a List: item_type byte + count int + item payloads."""
    count = len(items_payload_list)
    header = struct.pack(">bi", item_type, count)
    return header + b"".join(items_payload_list)

def _nbt_int_array_payload(values):
    """Payload for an Int Array: length int + int values."""
    data = struct.pack(">i", len(values))
    for v in values:
        data += struct.pack(">i", v)
    return data


def _build_record_compound(type_str, pos, free_tickets):
    """Build NBT compound payload for one POI record (no wrapping named tag)."""
    # type: String
    type_tag = _nbt_named_tag(8, "type", _nbt_string_payload(type_str))
    # pos: Int Array [x, y, z]
    pos_tag = _nbt_named_tag(11, "pos", _nbt_int_array_payload(pos))
    # free_tickets: Int
    tickets_tag = _nbt_named_tag(3, "free_tickets", _nbt_int(free_tickets))
    return _nbt_compound_payload([type_tag, pos_tag, tickets_tag])


def _build_poi_nbt(sections):
    """Build valid NBT bytes for a POI chunk.

    sections: dict like {"4": [{"type": "minecraft:home", "pos": [x, y, z], "free_tickets": 0}]}
    """
    # Build each section compound payload
    section_named_tags = []
    for section_key, records in sections.items():
        # Records list: TAG_List of TAG_Compound (10)
        record_payloads = [_build_record_compound(r["type"], r["pos"], r["free_tickets"])
                           for r in records]
        records_list_payload = _nbt_list_payload(10, record_payloads)
        records_tag = _nbt_named_tag(9, "Records", records_list_payload)

        # Valid: Byte
        valid_tag = _nbt_named_tag(1, "Valid", _nbt_byte(1))

        section_payload = _nbt_compound_payload([valid_tag, records_tag])
        section_named_tags.append(_nbt_named_tag(10, section_key, section_payload))

    # Sections compound
    sections_payload = _nbt_compound_payload(section_named_tags)
    sections_tag = _nbt_named_tag(10, "Sections", sections_payload)

    # DataVersion: Int
    data_version_tag = _nbt_named_tag(3, "DataVersion", _nbt_int(4671))

    # Root compound payload
    root_payload = _nbt_compound_payload([data_version_tag, sections_tag])

    # Root tag: TAG_Compound (10), empty name ""
    root = struct.pack(">bH", 10, 0) + root_payload
    return root


def _build_poi_region(tmp_path, chunks):
    """Build a .mca file at tmp_path/r.0.0.mca.

    chunks: list of {"slot": int (0-1023), "sections": dict}
    Returns the file path.
    """
    region_path = tmp_path / "r.0.0.mca"

    # Build compressed chunk data for each slot
    slot_data = {}
    for chunk in chunks:
        nbt_bytes = _build_poi_nbt(chunk["sections"])
        compressed = zlib.compress(nbt_bytes)
        # 4-byte length (includes the 1-byte compression type), 1-byte compression=2, data
        length = 1 + len(compressed)
        chunk_bytes = struct.pack(">I", length) + b"\x02" + compressed
        # Pad to multiple of 4096 bytes
        padded_len = ((len(chunk_bytes) + 4095) // 4096) * 4096
        chunk_bytes = chunk_bytes.ljust(padded_len, b"\x00")
        slot_data[chunk["slot"]] = chunk_bytes

    # Build location header (4096 bytes = 1024 * 4)
    # Chunks start after the two header sectors (offset 2)
    current_offset = 2  # sector offset
    location_entries = [b"\x00\x00\x00\x00"] * 1024
    chunk_blobs = []

    for slot in sorted(slot_data.keys()):
        data = slot_data[slot]
        sector_count = len(data) // 4096
        # 3-byte big-endian offset + 1-byte sector count
        entry = struct.pack(">I", (current_offset << 8) | sector_count)
        location_entries[slot] = entry
        chunk_blobs.append(data)
        current_offset += sector_count

    header = b"".join(location_entries)
    # Timestamps header (4096 bytes, all zeros)
    timestamps = b"\x00" * 4096

    with open(region_path, "wb") as f:
        f.write(header)
        f.write(timestamps)
        for blob in chunk_blobs:
            f.write(blob)

    return region_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_parse_poi_region_finds_beds(tmp_path):
    """1 chunk with 2 beds + 1 non-bed → returns 2 beds."""
    region_path = _build_poi_region(tmp_path, [
        {
            "slot": 0,
            "sections": {
                "4": [
                    {"type": "minecraft:home", "pos": [100, 64, 200], "free_tickets": 0},
                    {"type": "minecraft:home", "pos": [116, 64, 200], "free_tickets": 1},
                    {"type": "minecraft:armorer", "pos": [108, 64, 204], "free_tickets": 2},
                ]
            }
        }
    ])
    results = parse_poi_region(region_path)
    assert len(results) == 2
    positions = [r["pos"] for r in results]
    assert [100, 64, 200] in positions
    assert [116, 64, 200] in positions
    # free_tickets preserved
    tickets = {tuple(r["pos"]): r["free_tickets"] for r in results}
    assert tickets[(100, 64, 200)] == 0
    assert tickets[(116, 64, 200)] == 1


def test_parse_poi_region_empty(tmp_path):
    """No chunks → empty list."""
    region_path = _build_poi_region(tmp_path, [])
    results = parse_poi_region(region_path)
    assert results == []


def test_parse_poi_region_multiple_sections(tmp_path):
    """1 chunk with beds in 2 Y sections → returns 2 beds."""
    region_path = _build_poi_region(tmp_path, [
        {
            "slot": 5,
            "sections": {
                "3": [
                    {"type": "minecraft:home", "pos": [50, 48, 80], "free_tickets": 0},
                ],
                "5": [
                    {"type": "minecraft:home", "pos": [50, 80, 80], "free_tickets": 0},
                ],
            }
        }
    ])
    results = parse_poi_region(region_path)
    assert len(results) == 2
    positions = [r["pos"] for r in results]
    assert [50, 48, 80] in positions
    assert [50, 80, 80] in positions


def test_parse_poi_region_finds_bells(tmp_path):
    """Bell POIs (minecraft:meeting) are returned with type field."""
    region_path = _build_poi_region(tmp_path, [
        {
            "slot": 0,
            "sections": {
                "4": [
                    {"type": "minecraft:home", "pos": [100, 64, 200], "free_tickets": 0},
                    {"type": "minecraft:meeting", "pos": [110, 65, 210], "free_tickets": 30},
                    {"type": "minecraft:meeting", "pos": [120, 65, 220], "free_tickets": 28},
                ]
            }
        }
    ])
    results = parse_poi_region(region_path)
    assert len(results) == 3
    beds = [r for r in results if r["type"] == "minecraft:home"]
    bells = [r for r in results if r["type"] == "minecraft:meeting"]
    assert len(beds) == 1
    assert len(bells) == 2
    assert bells[0]["pos"] == [110, 65, 210]
    assert bells[0]["free_tickets"] == 30


def test_parse_poi_regions_combines(tmp_path):
    """parse_poi_regions merges beds from multiple region files."""
    r1_dir = tmp_path / "r1"
    r1_dir.mkdir()
    r1 = _build_poi_region(r1_dir, [
        {
            "slot": 0,
            "sections": {
                "4": [{"type": "minecraft:home", "pos": [10, 64, 20], "free_tickets": 0}]
            }
        }
    ])
    r2_dir = tmp_path / "r2"
    r2_dir.mkdir()
    r2 = _build_poi_region(r2_dir, [
        {
            "slot": 1,
            "sections": {
                "4": [{"type": "minecraft:home", "pos": [30, 64, 40], "free_tickets": 0}]
            }
        }
    ])
    results = parse_poi_regions([r1, r2])
    positions = [r["pos"] for r in results]
    assert [10, 64, 20] in positions
    assert [30, 64, 40] in positions
    assert len(results) == 2
