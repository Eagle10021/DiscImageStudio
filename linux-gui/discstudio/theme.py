# SPDX-License-Identifier: GPL-3.0-or-later
"""Material 3 Expressive look driven by the system's Material You colours.

The palette is read from ~/.config/kdeglobals (written by kde-material-you-colors whenever the wallpaper or
scheme changes) and expanded into M3 tonal surface and container roles. Light and dark schemes both work.
"""
from __future__ import annotations

import colorsys
import configparser
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtGui import QColor

import os as _os
KDEGLOBALS = Path(_os.environ.get("DISCSTUDIO_KDEGLOBALS", str(Path.home() / ".config" / "kdeglobals")))


def _rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


def _hex(c: tuple[float, float, float]) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in c)


def mix(a: str, b: str, t: float) -> str:
    """t = share of b."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def lum(h: str) -> float:
    r, g, b = _rgb(h)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def hls(h: str) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*_rgb(h))


def from_hls(hh: float, ll: float, ss: float) -> str:
    return _hex(colorsys.hls_to_rgb(hh % 1.0, max(0, min(1, ll)), max(0, min(1, ss))))


@dataclass
class Palette:
    dark: bool
    surface: str
    surface_lowest: str
    surface_low: str
    surface_container: str
    surface_high: str
    surface_highest: str
    on_surface: str
    on_surface_variant: str
    outline: str
    outline_variant: str
    primary: str
    on_primary: str
    primary_container: str
    on_primary_container: str
    secondary_container: str
    on_secondary_container: str
    tertiary: str
    tertiary_container: str
    error: str
    error_container: str
    on_error_container: str


def _read_scheme() -> dict[str, str]:
    cp = configparser.RawConfigParser()
    cp.optionxform = str
    try:
        cp.read(KDEGLOBALS, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    def rgb(section: str, key: str, default: str) -> str:
        """kdeglobals stores colours either as '#rrggbb' or as 'r,g,b'."""
        try:
            raw = cp.get(section, key).strip()
            if raw.startswith("#") and len(raw) in (7, 9):
                return raw[:7].lower()
            v = raw.split(",")
            return "#%02x%02x%02x" % (int(v[0]), int(v[1]), int(v[2]))
        except Exception:  # noqa: BLE001
            return default

    return {
        "surface": rgb("Colors:Window", "BackgroundNormal", "#1b1a10"),
        "on_surface": rgb("Colors:Window", "ForegroundNormal", "#ebe5d2"),
        "variant": rgb("Colors:Window", "ForegroundInactive", "#b0ab99"),
        "primary": rgb("Colors:Selection", "BackgroundNormal", "#d1c88b"),
        "on_primary": rgb("Colors:Selection", "ForegroundNormal", "#464111"),
        "button": rgb("Colors:Button", "BackgroundNormal", "#212015"),
    }


def load_palette() -> Palette:
    s = _read_scheme()
    surface, primary = s["surface"], s["primary"]
    dark = lum(surface) < 0.5
    toward = "#000000" if dark else "#ffffff"          # pushes surfaces away from the content colour
    on_surface = s["on_surface"]
    pH, pL, pS = hls(primary)
    tint = lambda t: mix(surface, primary, t)         # M3 surface tint overlays

    sec_c = from_hls(pH, 0.26 if dark else 0.86, min(pS, 0.30))
    on_sec_c = from_hls(pH, 0.86 if dark else 0.20, min(pS, 0.35))
    pri_c = mix(surface, primary, 0.30 if dark else 0.28)
    tert = from_hls(pH + 0.18, 0.78 if dark else 0.38, 0.45)
    tert_c = from_hls(pH + 0.18, 0.28 if dark else 0.88, 0.30)
    return Palette(
        dark=dark,
        surface=surface,
        surface_lowest=mix(surface, toward, 0.28 if dark else 0.04),
        surface_low=tint(0.04),
        surface_container=tint(0.07),
        surface_high=tint(0.11),
        surface_highest=tint(0.15),
        on_surface=on_surface,
        on_surface_variant=s["variant"],
        outline=mix(s["variant"], surface, 0.38),
        outline_variant=mix(s["variant"], surface, 0.72),
        primary=primary,
        on_primary=s["on_primary"],
        primary_container=pri_c,
        on_primary_container=mix(primary, "#ffffff" if dark else "#000000", 0.35),
        secondary_container=sec_c,
        on_secondary_container=on_sec_c,
        tertiary=tert,
        tertiary_container=tert_c,
        error="#f2b8b5" if dark else "#b3261e",
        error_container="#8c1d18" if dark else "#f9dedc",
        on_error_container="#f9dedc" if dark else "#410e0b",
    )


P: Palette = load_palette()


def reload() -> Palette:
    global P
    P = load_palette()
    return P


def qcolor(h: str, alpha: int = 255) -> QColor:
    c = QColor(h)
    c.setAlpha(alpha)
    return c


def _check_icon(p: Palette) -> str:
    """Draws the tick for checked boxes (on_primary on primary) and returns its file path."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QImage, QPainter, QPen
    d = Path.home() / ".cache" / "disc-image-studio"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"check-{p.on_primary.lstrip('#')}.png"
    if not f.exists():
        img = QImage(40, 40, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        q = QPainter(img)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setPen(QPen(QColor(p.on_primary), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        q.drawPolyline([QPointF(9, 21), QPointF(17, 29), QPointF(31, 11)])
        q.end()
        img.save(str(f))
    return str(f)


SCALE = 1.0


def set_scale(s: float) -> None:
    global SCALE
    SCALE = s


def stylesheet(p: Palette | None = None, scale: float | None = None) -> str:
    import re
    css = _stylesheet(p)
    s = SCALE if scale is None else scale
    if abs(s - 1.0) < 0.01:
        return css
    return re.sub(r"(\d+(?:\.\d+)?)px", lambda m: f"{max(1, round(float(m.group(1)) * s))}px", css)


def _stylesheet(p: Palette | None = None) -> str:
    p = p or P
    check = _check_icon(p)
    state = lambda base, ov, t: mix(base, ov, t)       # hover = +8% state layer, pressed = +12%
    return f"""
* {{ font-family: 'Roboto', 'Noto Sans', sans-serif; font-size: 14px; }}
QMainWindow, QWidget#page {{ background: {p.surface}; color: {p.on_surface}; }}
QLabel, QCheckBox, QRadioButton {{ color: {p.on_surface}; background: transparent; }}
QLabel#h1 {{ font-size: 28px; font-weight: 500; color: {p.on_surface}; }}
QLabel#sub {{ color: {p.on_surface_variant}; }}
QLabel#card {{ background: {p.surface_container}; border-radius: 28px; padding: 18px; }}
QToolTip {{ background: {p.surface_highest}; color: {p.on_surface}; border: 1px solid transparent; border-radius: 8px; padding: 6px 10px; }}

QMenuBar, QMenuBar::item {{ background: {p.surface_lowest}; color: {p.on_surface_variant}; padding: 4px 10px; }}
QMenuBar::item:selected {{ background: {p.surface_high}; border-radius: 10px; }}
QMenu {{ background: {p.surface_container}; color: {p.on_surface}; border-radius: 16px; padding: 8px; }}
QMenu::item {{ padding: 8px 20px; border-radius: 12px; }}
QMenu::item:selected {{ background: {p.secondary_container}; color: {p.on_secondary_container}; }}
QStatusBar {{ background: {p.surface_lowest}; color: {p.on_surface_variant}; }}

/* navigation rail: pill active indicator */
QWidget#rail {{ background: {p.surface_lowest}; }}
QListWidget#nav {{ background: transparent; border: none; outline: 0; padding: 4px 0; }}
QListWidget#nav::item {{ padding: 14px 18px; margin: 3px 10px; border-radius: 22px; color: {p.on_surface_variant}; }}
QListWidget#nav::item:hover {{ background: {mix(p.surface_lowest, p.on_surface, 0.08)}; }}
QListWidget#nav::item:selected {{ background: {p.secondary_container}; color: {p.on_secondary_container}; font-weight: 500; }}
QLabel#brand {{ font-size: 17px; font-weight: 500; color: {p.primary}; padding: 0px; }}

/* cards */
QGroupBox {{ background: {p.surface_low}; border: 1px solid transparent; border-radius: 28px; margin-top: 18px; padding: 16px 12px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 22px; padding: 0 8px; color: {p.primary}; font-weight: 500; }}

/* buttons: tonal by default, filled for primary, error container for danger */
QPushButton {{ background: {p.secondary_container}; color: {p.on_secondary_container}; border: 1px solid transparent; border-radius: 20px;
  padding: 9px 14px; min-height: 20px; min-width: 0; font-weight: 500; }}
QPushButton:hover {{ background: {state(p.secondary_container, p.on_secondary_container, 0.10)}; }}
QPushButton:pressed {{ background: {state(p.secondary_container, p.on_secondary_container, 0.18)}; border-radius: 14px; }}
QPushButton:disabled {{ background: {mix(p.surface, p.on_surface, 0.10)}; color: {mix(p.surface, p.on_surface, 0.40)}; }}
QPushButton#primary {{ background: {p.primary}; color: {p.on_primary}; border-radius: 24px; padding: 13px 26px; font-size: 15px; }}
QPushButton#primary:hover {{ background: {state(p.primary, p.on_primary, 0.10)}; }}
QPushButton#primary:pressed {{ background: {state(p.primary, p.on_primary, 0.18)}; border-radius: 16px; }}
QPushButton#danger {{ background: {p.error_container}; color: {p.on_error_container}; border-radius: 24px; padding: 13px 26px; font-size: 15px; }}
QPushButton#danger:hover {{ background: {state(p.error_container, p.on_error_container, 0.10)}; }}

/* filled text fields */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {p.surface_highest}; color: {p.on_surface}; border: 2px solid transparent;
  border-radius: 14px; padding: 8px 12px; selection-background-color: {p.primary}; selection-color: {p.on_primary}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 2px solid {p.primary}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {mix(p.surface, p.on_surface, 0.40)}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{ background: {p.surface_container}; color: {p.on_surface}; border: 1px solid transparent; border-radius: 16px; padding: 6px;
  selection-background-color: {p.secondary_container}; selection-color: {p.on_secondary_container}; outline: 0; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 18px; border: none; background: transparent; }}

QPlainTextEdit, QListWidget#layers {{ background: {p.surface_container}; color: {p.on_surface}; border: 1px solid transparent; border-radius: 20px; padding: 10px; }}
QListWidget#layers::item {{ padding: 10px 12px; border-radius: 14px; }}
QListWidget#layers::item:selected {{ background: {p.secondary_container}; color: {p.on_secondary_container}; }}
QListWidget#layers::item:hover:!selected {{ background: {p.surface_high}; }}

QGraphicsView {{ background: {p.surface_lowest}; border: 1px solid transparent; border-radius: 28px; }}

QCheckBox::indicator {{ width: 20px; height: 20px; border-radius: 6px; border: 2px solid {p.outline}; background: transparent; }}
QCheckBox::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; image: url({check}); }}

QSlider::groove:horizontal {{ height: 6px; background: {p.surface_highest}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {p.primary}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {p.primary}; width: 6px; height: 28px; margin: -11px 2px; border-radius: 3px; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: {p.outline_variant}; border-radius: 4px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: {p.outline}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 4px; }}
QScrollBar::handle:horizontal {{ background: {p.outline_variant}; border-radius: 4px; min-width: 40px; }}
QMessageBox, QFileDialog, QDialog {{ background: {p.surface_container}; }}
"""
