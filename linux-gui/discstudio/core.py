# SPDX-License-Identifier: GPL-3.0-or-later
"""Project model, presets and CLI argument building for Disc Image Studio (Linux front-end).

The encoders live in the upstream .NET CLI (`disc-image-studio`). This module only
describes a project and turns it into CLI argument lists.
"""
from __future__ import annotations

import json
import math
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

CLI_DIR = Path(os.environ.get("DISCSTUDIO_CLI", Path.home() / ".local/share/disc-image-studio/cli"))
CLI_BIN = CLI_DIR / "disc-image-studio"
DATA_DIR = Path.home() / ".local/share/disc-image-studio"
CONFIG_DIR = Path.home() / ".config/disc-image-studio"
PRESET_FILE = Path(__file__).with_name("presets.json")

KINDS = ("cd", "dvd", "bd")
KIND_NAMES = {"cd": "CD", "dvd": "DVD", "bd": "Blu-ray"}


def cli_available() -> bool:
    return CLI_BIN.exists()


def load_presets() -> dict[str, list[dict]]:
    data = json.loads(PRESET_FILE.read_text("utf-8"))
    return {"cd": data["cdPresets"], "dvd": data["dvdPresets"], "bd": data["bluRayPresets"]}


PRESET_NAMES = {
    "ritek-dvd-plus-rw-4x": "RiTEK Excellent X DVD+RW 4x",
    "cd-80": "Standard 80 min CD", "cd-74": "Standard 74 min CD",
    "ritek-medical-aqua": "Ritek medical aqua CD (measured)",
    "verbatim-azo-43438": "Verbatim AZO CD-R 43438 (measured)",
    "dvd-5-120mm": "Standard 12 cm single-layer DVD", "dvd-5-80mm": "Standard 8 cm DVD",
    "verbatim-dvd-r-azo-43533": "Verbatim DVD-R AZO 43533 (measured)",
    "verbatim-dvd-r-azo-43523": "Verbatim DVD-R AZO 43523 (measured)",
    "verbatim-dvd-plus-r-azo-43498": "Verbatim DVD+R AZO 43498 (measured)",
    "verbatim-dvd-plus-rw-94520-95043": "Verbatim DVD+RW 94520/95043 (measured)",
    "philips-dvd-plus-r": "Philips DVD+R", "ritek-dvd-plus-r-e-series": "Ritek DVD+R E-series",
    "ritek-dvd-r-e-series": "Ritek DVD-R E-series",
    "bd-r-sl-25gb": "Standard 25 GB single-layer BD-R", "bd-r-ritek-10x": "Ritek BD-R 10x (measured)",
    "bd-r-ritek-12x": "Ritek BD-R 12x (measured)", "bd-r-verbatim-64099": "Verbatim BD-R 64099 (measured)",
    "bd-r-verbatim-64293": "Verbatim BD-R 64293 (measured)", "bd-re-verbatim-43614": "Verbatim BD-RE 43614 (measured)",
}


def preset_title(p: dict) -> str:
    return PRESET_NAMES.get(p.get("id", ""), p.get("displayName") or p.get("id", "?"))


@dataclass
class Layer:
    path: str
    x: float = 0.0          # mm from disc centre
    y: float = 0.0
    scale: float = 1.0      # 1.0 = one pixel per canvas pixel, set on import to fit
    rotation: float = 0.0
    opacity: float = 1.0
    visible: bool = True
    name: str = ""


@dataclass
class Geometry:
    r0: float = 24.5
    r1: float = 56.8
    sectors: int = 359849
    usable: int = 359847
    velocity: float = 1200.0
    channel_bit_nm: float = 133.3
    pitch: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass
class Tone:
    dither: int = 75          # percent
    levels: int = 2           # CD only: 2 or 4
    brightness: int = 0
    gamma: bool = False


@dataclass
class Project:
    name: str = "Untitled"
    kind: str = "cd"
    preset_id: str = "cd-80"
    geo: Geometry = field(default_factory=Geometry)
    tone: Tone = field(default_factory=Tone)
    layers: list[Layer] = field(default_factory=list)
    background: str = "transparent"      # transparent | white | black
    data_dir: str = ""
    volume_label: str = "DISC_IMAGE"
    files_outer: bool = False
    output_dir: str = str(Path.home() / "Documents")
    cd_audio: bool = True               # CD: audio WAV+CUE (True) or Mode 1 data ISO (False)
    cd_interleave: bool = True
    bd_invert: bool = False
    dvd_compat: int = 0                  # 0 off, 1..3
    image_path: str = ""                 # existing image chosen with "Load image…" (used for preview/burn)
    path: str = ""                       # .discproj location, not serialised

    # --- derived -------------------------------------------------------------
    @property
    def canvas_radius(self) -> float:
        """Radius on the composite image that maps to the square edge (mm)."""
        return self.geo.r1

    def apply_preset(self, p: dict) -> None:
        g = self.geo
        g.r0 = p["innerRadiusMm"]
        g.r1 = p["outerRadiusMm"]
        g.sectors = p.get("totalSectors", p.get("sectors"))
        g.usable = p.get("usableSectors", g.sectors)
        g.velocity = p.get("linearVelocityMmPerSecond", 1200.0)
        g.channel_bit_nm = p.get("channelBitLengthNm", 133.3)
        g.pitch = (p.get("pitchLinear", 0.0), p.get("pitchQuadratic", 0.0), p.get("pitchCubic", 0.0))
        if "invertMapping" in p:
            self.bd_invert = bool(p["invertMapping"])
        self.preset_id = p["id"]

    # --- persistence ---------------------------------------------------------
    def to_json(self) -> str:
        d = asdict(self)
        d.pop("path", None)
        d["format"] = "disc-image-studio-linux-project-1"
        return json.dumps(d, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Project":
        d = json.loads(text)
        p = cls()
        for k, v in d.items():
            if k == "geo":
                v["pitch"] = tuple(v.get("pitch", (0, 0, 0)))
                p.geo = Geometry(**v)
            elif k == "tone":
                p.tone = Tone(**v)
            elif k == "layers":
                p.layers = [Layer(**x) for x in v]
            elif hasattr(p, k) and k != "path":
                setattr(p, k, v)
        return p


# ---------------------------------------------------------------------------
# Output naming / argument building
# ---------------------------------------------------------------------------

def safe_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_ ." else "_" for c in name).strip()
    return keep or "disc"


def output_path(p: Project) -> Path:
    base = Path(p.output_dir) / safe_name(p.name)
    if p.kind == "cd" and p.cd_audio:
        return base.with_suffix(".wav")
    return base.with_suffix(".iso")


def burn_image(p: Project) -> Path:
    """Image used for read-back preview and burning: a loaded one, else the generated output."""
    return Path(p.image_path) if p.image_path else output_path(p)


def _tone_args(p: Project) -> list[str]:
    t = p.tone
    args = ["--tone-dither", f"{t.dither / 100:.3f}",
            "--tone-brightness", str(t.brightness),
            "--tone-gamma", "true" if t.gamma else "false"]
    if p.kind == "cd":
        args += ["--tone-levels", str(t.levels)]
    elif p.kind == "bd":
        args += ["--tone-levels", "2"]
    else:
        args += ["--tone-levels", "2"]
    return args


def _pitch_args(prefix: str, pitch: tuple[float, float, float]) -> list[str]:
    return [f"--{prefix}-linear", repr(pitch[0]), f"--{prefix}-quadratic", repr(pitch[1]),
            f"--{prefix}-cubic", repr(pitch[2])]


def generate_args(p: Project, composite: str, out: str | None = None) -> list[str]:
    g = p.geo
    out = out or str(output_path(p))
    if p.kind == "cd":
        a = ["cd-generate", "--input", composite, "--output", out,
             "--r0", repr(g.r0), "--r1", repr(g.r1), "--sectors", str(g.sectors),
             "--usable-sectors", str(g.usable), "--velocity", repr(g.velocity),
             *_pitch_args("pitch", g.pitch), *_tone_args(p)]
        if p.cd_audio:
            a += ["--interleave", "true" if p.cd_interleave else "false", "--cue", "true"]
        else:
            if p.data_dir:
                a += ["--data-dir", p.data_dir]
            a += ["--volume-label", p.volume_label,
                  "--file-position", "outer" if p.files_outer else "inner"]
        return a
    if p.kind == "dvd":
        a = ["solve", "--image", composite, "--iso-output", out,
             "--total-sectors", str(g.sectors),
             "--inner-radius-mm", repr(g.r0), "--outer-radius-mm", repr(g.r1),
             "--channel-bit-nm", repr(g.channel_bit_nm),
             *_pitch_args("pitch", g.pitch), *_tone_args(p)]
        if not p.data_dir:
            a += ["--fill-sectors", str(g.usable // 16 * 16)]
        if p.data_dir:
            a += ["--data-dir", p.data_dir, "--volume-label", p.volume_label,
                  "--file-position", "outer" if p.files_outer else "inner"]
        if p.dvd_compat:
            a += ["--read-compatibility", "true", "--read-compatibility-mode", str(p.dvd_compat)]
        return a
    a = ["bd-generate", "--input", composite, "--output", out,
         "--total-sectors", str(g.sectors), "--usable-sectors", str(g.usable),
         "--r0", repr(g.r0), "--r1", repr(g.r1), *_pitch_args("pitch", g.pitch),
         "--volume-label", p.volume_label, *_tone_args(p)]
    if p.bd_invert:
        a += ["--invert", "true"]
    if p.data_dir:
        a += ["--data-dir", p.data_dir, "--file-position", "outer" if p.files_outer else "inner"]
    return a


def projection_args(p: Project, composite: str, out_png: str, size: int) -> list[str] | None:
    """CLI command that renders the design through the generated geometry, if one exists."""
    g = p.geo
    if p.kind == "cd":
        return ["cd-preview-warp", "--input", composite, "--output", out_png,
                "--r0", repr(g.r0), "--r1", repr(g.r1), "--sectors", str(g.sectors),
                "--usable-sectors", str(g.usable), "--velocity", repr(g.velocity),
                *_pitch_args("pitch", g.pitch),
                "--actual-r0", repr(g.r0), "--actual-r1", repr(g.r1),
                *_pitch_args("actual-pitch", g.pitch),
                *_tone_args(p), "--size", str(size)]
    if p.kind == "dvd":
        return ["calibrate", "--image", composite, "--output", out_png,
                "--total-sectors", str(g.sectors),
                "--generated-inner-radius-mm", repr(g.r0), "--generated-outer-radius-mm", repr(g.r1),
                "--actual-inner-radius-mm", repr(g.r0), "--actual-outer-radius-mm", repr(g.r1),
                *_pitch_args("pitch", g.pitch), *_pitch_args("actual-pitch", g.pitch),
                "--channel-bit-nm", repr(g.channel_bit_nm)]
    return None


def readback_args(p: Project, image: str, out_png: str, size: int) -> list[str] | None:
    g = p.geo
    if p.kind == "cd":
        return ["cd-preview-track", "--track", image, "--output", out_png,
                "--r0", repr(g.r0), "--r1", repr(g.r1), "--sectors", str(g.sectors),
                "--velocity", repr(g.velocity), *_pitch_args("pitch", g.pitch),
                "--size", str(size),
                "--deinterleave", "true" if p.cd_interleave and p.cd_audio else "false"]
    if p.kind == "dvd":
        return ["simulate", "--iso", image, "--output", out_png,
                "--total-sectors", str(g.sectors),
                "--inner-radius-mm", repr(g.r0), "--outer-radius-mm", repr(g.r1),
                *_pitch_args("pitch", g.pitch), "--channel-bit-nm", repr(g.channel_bit_nm)]
    return None


# ---------------------------------------------------------------------------
# Burning (external tools)
# ---------------------------------------------------------------------------

def list_drives() -> list[str]:
    import glob
    return sorted(glob.glob("/dev/sr*"))


def burn_tools() -> dict[str, str | None]:
    return {"cdrecord": shutil.which("cdrecord") or shutil.which("wodim"),
            "growisofs": shutil.which("growisofs"),
            "xorriso": shutil.which("xorriso")}


def burn_command(p: Project, image: Path, device: str, speed: int | None) -> list[str] | None:
    tools = burn_tools()
    if p.kind == "cd":
        cr = tools["cdrecord"]
        if not cr:
            return None
        cmd = [cr, f"dev={device}", "-v", "-eject"]
        if speed:
            cmd.append(f"speed={speed}")
        if p.cd_audio:
            return cmd + ["-dao", "-audio", str(image)]
        return cmd + ["-dao", "-data", str(image)]
    gw = tools["growisofs"]
    if gw:
        cmd = [gw, "-dvd-compat", "-use-the-force-luke=tty"]   # no terminal under the GUI: don't refuse to overwrite
        if speed:
            cmd.append(f"-speed={speed}")
        return cmd + ["-Z", f"{device}={image}"]
    xo = tools["xorriso"]
    if xo:
        cmd = [xo, "-as", "cdrecord", f"dev={device}", "-v", "-dao", "-eject"]
        if speed:
            cmd.append(f"speed={speed}")
        return cmd + [str(image)]
    return None


# Media IDs recorded in the upstream preset descriptions (confirmed matches only).
MEDIA_ID_PRESETS = {
    "MKM/A02": "verbatim-dvd-plus-rw-94520-95043",
    "MCC/03RG20": "verbatim-dvd-r-azo-43533",
}


def detect_disc(device: str) -> dict:
    """Read the inserted disc with dvd+rw-mediainfo. Returns a dict, or {"error": ...}."""
    import re
    import subprocess
    tool = shutil.which("dvd+rw-mediainfo")
    if not tool:
        return {"error": "dvd+rw-mediainfo not installed (pacman -S dvd+rw-tools)"}
    try:
        out = subprocess.run([tool, device], capture_output=True, text=True, timeout=40).stdout
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}

    def grab(pat):
        m = re.search(pat, out)
        return m.group(1).strip() if m else ""

    media = grab(r"Mounted Media:\s*\w+,\s*(.+)")
    if not media:
        return {"error": "No disc, or the drive could not read it."}
    free = grab(r"Free Blocks:\s*(\d+)\*2KB")
    cap = grab(r"(?:unformatted|formatted):\s*(\d+)\*2048") or grab(r"00/(\d+)\s+R@")
    exact = bool(grab(r"(?:unformatted|formatted):\s*(\d+)\*2048"))
    cap_blocks = (int(cap) + (0 if exact else 1)) if cap.isdigit() else 0
    d = {"media": media, "media_id": re.sub(r"\s+", "/", grab(r"Media ID:\s*(.+)")), "status": grab(r"Disc status:\s*(\S+)"),
         "free_bytes": int(free) * 2048 if free.isdigit() else 0, "capacity_bytes": cap_blocks * 2048 if cap else 0, "max_speed": grab(r"Write Speed #0:\s*([\d.]+x)"),
         "rewritable": "RW" in media or "RAM" in media}
    m = media.upper()
    d["kind"] = "bd" if "BD" in m else "dvd" if "DVD" in m else "cd" if "CD" in m else ""
    d["preset"] = MEDIA_ID_PRESETS.get(d["media_id"], "")
    return d


def data_region(p: Project) -> tuple[float, float] | None:
    """Estimated (inner_mm, outer_mm) band the stored files occupy, or None."""
    if not p.data_dir or (p.kind == "cd" and p.cd_audio) or not Path(p.data_dir).is_dir():
        return None
    total = 0
    for root, _dirs, files in os.walk(p.data_dir):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    sectors = -(-total // 2048) + 512            # file data + rough filesystem overhead
    frac = min(1.0, sectors / max(1, p.geo.usable))
    g = p.geo

    def radius(f: float) -> float:
        return (g.r0 ** 2 + (g.r1 ** 2 - g.r0 ** 2) * f) ** 0.5

    return (g.r0, radius(frac)) if not p.files_outer else (radius(1 - frac), g.r1)


def spin_rpm(p: Project, speed_x: float, frac: float) -> float:
    """Approximate disc RPM while writing: the drive holds a constant linear speed, so RPM = v / (2 pi r).

    frac = share of the disc written so far, mapped to a radius by area (ignores the pitch curve).
    """
    g = p.geo
    r_mm = (g.r0 ** 2 + (g.r1 ** 2 - g.r0 ** 2) * max(0.0, min(1.0, frac))) ** 0.5
    v1x = {"dvd": 3.49, "bd": 4.917}.get(p.kind, g.velocity / 1000.0)     # m/s at 1x
    return speed_x * v1x * 1000.0 / (2 * math.pi * max(r_mm, 1.0)) * 60.0


def human_size(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def disc_ring(p: Project) -> tuple[float, float]:
    return p.geo.r0, p.geo.r1


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


__all__ = [n for n in dir() if not n.startswith("_")]
_ = math
