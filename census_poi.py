"""POI region file parser — extracts bed locations (minecraft:home) from .mca files."""

import io
import struct
import zlib


# ---------------------------------------------------------------------------
# NBT reader
# ---------------------------------------------------------------------------

def _read_payload(f, tag_type):
    """Read the payload for a tag of the given type from f."""
    if tag_type == 0:  # TAG_End
        return None
    elif tag_type == 1:  # TAG_Byte
        return struct.unpack(">b", f.read(1))[0]
    elif tag_type == 2:  # TAG_Short
        return struct.unpack(">h", f.read(2))[0]
    elif tag_type == 3:  # TAG_Int
        return struct.unpack(">i", f.read(4))[0]
    elif tag_type == 4:  # TAG_Long
        return struct.unpack(">q", f.read(8))[0]
    elif tag_type == 5:  # TAG_Float
        return struct.unpack(">f", f.read(4))[0]
    elif tag_type == 6:  # TAG_Double
        return struct.unpack(">d", f.read(8))[0]
    elif tag_type == 7:  # TAG_Byte_Array
        length = struct.unpack(">i", f.read(4))[0]
        return f.read(length)
    elif tag_type == 8:  # TAG_String
        length = struct.unpack(">H", f.read(2))[0]
        return f.read(length).decode("utf-8")
    elif tag_type == 9:  # TAG_List
        list_type = struct.unpack(">b", f.read(1))[0]
        count = struct.unpack(">i", f.read(4))[0]
        return [_read_payload(f, list_type) for _ in range(count)]
    elif tag_type == 10:  # TAG_Compound
        result = {}
        while True:
            child_type = struct.unpack(">b", f.read(1))[0]
            if child_type == 0:  # TAG_End
                break
            name_len = struct.unpack(">H", f.read(2))[0]
            name = f.read(name_len).decode("utf-8")
            result[name] = _read_payload(f, child_type)
        return result
    elif tag_type == 11:  # TAG_Int_Array
        length = struct.unpack(">i", f.read(4))[0]
        return list(struct.unpack(f">{length}i", f.read(length * 4)))
    elif tag_type == 12:  # TAG_Long_Array
        length = struct.unpack(">i", f.read(4))[0]
        return list(struct.unpack(f">{length}q", f.read(length * 8)))
    else:
        raise ValueError(f"Unknown NBT tag type: {tag_type}")


def read_nbt(f):
    """Read NBT binary data from a file-like object. Returns a nested dict.

    The root tag is a named TAG_Compound; the name is read and discarded.
    Returns the compound payload dict.
    """
    tag_type = struct.unpack(">b", f.read(1))[0]
    name_len = struct.unpack(">H", f.read(2))[0]
    f.read(name_len)  # skip root name
    return _read_payload(f, tag_type)


# ---------------------------------------------------------------------------
# MCA / POI region parser
# ---------------------------------------------------------------------------

def parse_poi_region(region_path):
    """Parse a POI .mca file. Returns list of
    {"type": str, "pos": [x, y, z], "free_tickets": int} dicts,
    filtered to minecraft:home and minecraft:meeting types.
    """
    _WANTED_TYPES = {b"minecraft:home", b"minecraft:meeting"}
    _WANTED_STRS = {"minecraft:home", "minecraft:meeting"}
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
                continue  # empty slot

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
                raw = compressed_data  # uncompressed

            # Fast pre-filter: skip chunks without any wanted POI type
            if not any(t in raw for t in _WANTED_TYPES):
                continue

            nbt = read_nbt(io.BytesIO(raw))
            sections = nbt.get("Sections", {})
            for section_key, section in sections.items():
                records = section.get("Records", [])
                for record in records:
                    rtype = record.get("type")
                    if rtype in _WANTED_STRS:
                        results.append({
                            "type": rtype,
                            "pos": record["pos"],
                            "free_tickets": record.get("free_tickets", 0),
                        })

    return results


def parse_poi_regions(region_paths):
    """Parse multiple POI region files. Returns combined list of POI records."""
    results = []
    for path in region_paths:
        results.extend(parse_poi_region(path))
    return results
