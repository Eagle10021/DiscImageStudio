# SPDX-License-Identifier: GPL-3.0-or-later
"""A real text file on the disc: 'Burn info.txt', stored in the safe tail at the very end.

The encoder fills the disc with picture data right up to the last sector, so there is no room to append a file
the usual way. Instead, after the image is generated this module
  1. zeroes the tail (ordinary, readable data),
  2. writes the note text at the start of the tail,
  3. adds a directory entry for it to the ISO 9660 and Joliet root directories (using the free space at the end
     of the root directory's last sector).
Nothing else in the image changes, so the stored files and the picture are untouched.

The same parser reads a note back from a disc (/dev/sr0) or an image file.
"""
from __future__ import annotations

import datetime as _dt
import os
import platform
import socket
import struct
from typing import BinaryIO

SECTOR = 2048
NOTE_BYTES = 4096                              # fixed allocation, so the burn details can be rewritten in place
ISO_NAME = b"BURNINFO.TXT;1"
JOLIET_NAME = "Burn info.txt"
BURN_MARK = "[burn]"


def _ascii(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def _os_name() -> str:
    try:
        for line in open("/etc/os-release", encoding="utf-8"):
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.system()


def build_note(project_name: str, disc: str, picture: str, files: str, app_version: str,
               burn: dict | None = None) -> bytes:
    """Fixed-size ASCII text. `burn` holds drive / disc / speed once the burn is about to start."""
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "Disc Image Studio - burn info",
        "=============================",
        f"Project  : {project_name}",
        f"Created  : {now}",
        f"Machine  : {socket.gethostname()}",
        f"System   : {_os_name()}, kernel {platform.release()}",
        f"Software : Disc Image Studio (Linux GUI {app_version})",
        f"Disc     : {disc}",
        f"Picture  : {picture}",
        f"Files    : {files}",
        "",
        BURN_MARK,
    ]
    b = burn or {}
    lines += [
        f"Burnt on : {b.get('when', '(filled in when burned)')}",
        f"Burnt by : {b.get('by', '-')}",
        f"Drive    : {b.get('drive', '-')}",
        f"Disc     : {b.get('media', '-')}",
        f"Speed    : {b.get('speed', '-')}",
        "",
        "This disc carries a picture made of its own data. This file sits in the safe tail at the end of",
        "the disc so that drives and players find ordinary, readable data there.",
    ]
    text = _ascii("\n".join(lines) + "\n")
    data = text.encode("ascii")[:NOTE_BYTES - 1]
    return data + b" " * (NOTE_BYTES - 1 - len(data)) + b"\n"


# --- ISO 9660 / Joliet directory handling ------------------------------------------------------------

def _both32(v: int) -> bytes:
    return struct.pack("<I", v) + struct.pack(">I", v)


def _record(name: bytes, lba: int, size: int, when: _dt.datetime) -> bytes:
    fi = len(name)
    dr = 33 + fi + (1 if fi % 2 == 0 else 0)
    rec = bytearray(dr)
    rec[0] = dr
    rec[2:10] = _both32(lba)
    rec[10:18] = _both32(size)
    rec[18:25] = bytes([when.year - 1900, when.month, when.day, when.hour, when.minute, when.second, 0])
    rec[25] = 0                                      # a plain file
    rec[28:32] = struct.pack("<H", 1) + struct.pack(">H", 1)
    rec[32] = fi
    rec[33:33 + fi] = name
    return bytes(rec)


def _roots(f: BinaryIO) -> list[tuple[str, int, int]]:
    """(kind, root_lba, root_length) for the primary tree and, if present, the Joliet tree."""
    out = []
    for lba in range(16, 40):
        f.seek(lba * SECTOR)
        d = f.read(SECTOR)
        if len(d) < SECTOR or d[1:6] != b"CD001":
            break
        t = d[0]
        if t == 255:
            break
        if t in (1, 2):
            joliet = t == 2 and d[88:91] in (b"%/@", b"%/C", b"%/E")
            if t == 1 or joliet:
                root = d[156:190]
                out.append(("joliet" if joliet else "iso", struct.unpack_from("<I", root, 2)[0],
                            struct.unpack_from("<I", root, 10)[0]))
    return out


def _entries(f: BinaryIO, lba: int, length: int):
    """Yield (offset_in_dir, record_bytes) for every directory record."""
    f.seek(lba * SECTOR)
    data = f.read(length)
    pos = 0
    while pos < len(data):
        n = data[pos]
        if n == 0:
            pos = (pos // SECTOR + 1) * SECTOR
            continue
        yield pos, data[pos:pos + n]
        pos += n


def find_note(f: BinaryIO) -> tuple[int, int] | None:
    """(lba, size) of 'Burn info.txt' / 'BURNINFO.TXT' if it exists in either tree."""
    for kind, lba, length in _roots(f):
        for _pos, rec in _entries(f, lba, length):
            fi = rec[32]
            name = rec[33:33 + fi]
            ok = (name == ISO_NAME) if kind == "iso" else (name.decode("utf-16-be", "ignore").lower() == JOLIET_NAME.lower())
            if ok:
                return struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0]
    return None


def _add_entry(f: BinaryIO, kind: str, root_lba: int, root_len: int, name: bytes, note_lba: int) -> bool:
    """Writes the new record into the free space of the root directory's last used sector. False if it is full."""
    when = _dt.datetime.now(_dt.timezone.utc)
    rec = _record(name, note_lba, NOTE_BYTES, when)
    f.seek(root_lba * SECTOR)
    data = bytearray(f.read(root_len))
    # last sector that holds records
    last_sector = None
    for pos, _r in _entries_from_bytes(data):
        last_sector = pos // SECTOR
    if last_sector is None:
        return False
    base = last_sector * SECTOR
    pos = 0
    while pos < SECTOR and data[base + pos] != 0:
        pos += data[base + pos]
    if SECTOR - pos < len(rec):
        return False
    data[base + pos:base + pos + len(rec)] = rec
    f.seek((root_lba + last_sector) * SECTOR)
    f.write(bytes(data[base:base + SECTOR]))
    return True


def _entries_from_bytes(data: bytes):
    pos = 0
    while pos < len(data):
        n = data[pos]
        if n == 0:
            pos = (pos // SECTOR + 1) * SECTOR
            continue
        yield pos, data[pos:pos + n]
        pos += n


def add_note(iso: str, tail_sectors: int, note: bytes) -> dict:
    """Writes the note at the start of the tail and lists it in the filesystem. Returns what was done."""
    result = {"written": False, "iso": False, "joliet": False, "lba": None}
    size = os.path.getsize(iso)
    total = size // SECTOR
    if tail_sectors * SECTOR < NOTE_BYTES or tail_sectors > total:
        return result
    note_lba = total - tail_sectors
    with open(iso, "r+b") as f:
        roots = _roots(f)
        if not roots:
            return result
        if find_note(f):
            return {**result, "written": True, "lba": find_note(f)[0], "iso": True, "joliet": True}
        f.seek(note_lba * SECTOR)
        f.write(note)
        result["written"], result["lba"] = True, note_lba
        for kind, lba, length in roots:
            name = ISO_NAME if kind == "iso" else JOLIET_NAME.encode("utf-16-be")
            result[kind] = _add_entry(f, kind, lba, length, name, note_lba)
    return result


def read_note(f: BinaryIO) -> str | None:
    """The note text from an open image file or disc device, or None if there is no note."""
    found = find_note(f)
    if not found:
        return None
    lba, size = found
    f.seek(lba * SECTOR)
    return f.read(min(size, NOTE_BYTES)).decode("ascii", "replace").rstrip()


def stamp_burn(iso: str, drive: str, media: str, speed: str) -> bool:
    """Rewrites the [burn] block of an existing note in place (same size). False if the image has no note."""
    when = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(iso, "r+b") as f:
        found = find_note(f)
        if not found:
            return False
        lba, _size = found
        f.seek(lba * SECTOR)
        text = f.read(NOTE_BYTES).decode("ascii", "replace")
        head, sep, tail = text.partition(BURN_MARK)
        if not sep:
            return False
        rest = tail.split("\n\n", 1)
        keep = rest[1] if len(rest) > 1 else ""
        block = (f"{BURN_MARK}\nBurnt on : {when}\nBurnt by : {_ascii(socket.gethostname())}, {_ascii(_os_name())}\n"
                 f"Drive    : {_ascii(drive)}\nDisc     : {_ascii(media)}\nSpeed    : {_ascii(speed)}\n\n")
        data = (head + block + keep).rstrip().encode("ascii", "replace")[:NOTE_BYTES - 1]
        data += b" " * (NOTE_BYTES - 1 - len(data)) + b"\n"
        f.seek(lba * SECTOR)
        f.write(data)
    return True
