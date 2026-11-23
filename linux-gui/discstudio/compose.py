# SPDX-License-Identifier: GPL-3.0-or-later
"""Layer compositing and local tone preview (pure Qt, no CLI)."""
from __future__ import annotations

import math

import numpy as np

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen

from .core import Project

_cache: dict[str, QImage] = {}


def load_image(path: str) -> QImage:
    img = _cache.get(path)
    if img is None:
        img = QImage(path)
        if not img.isNull():
            img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        _cache[path] = img
    return img


def drop_cache(path: str | None = None) -> None:
    if path is None:
        _cache.clear()
    else:
        _cache.pop(path, None)


def compose(p: Project, size: int) -> QImage:
    """Square image: centre = disc centre, side = 2 x canvas radius (mm)."""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    bg = {"white": QColor("white"), "black": QColor("black")}.get(p.background, QColor(0, 0, 0, 0))
    img.fill(bg)
    ppm = size / (2.0 * p.canvas_radius)
    qp = QPainter(img)
    qp.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
    for layer in reversed(p.layers):          # index 0 is the top layer
        if not layer.visible:
            continue
        src = load_image(layer.path)
        if src.isNull():
            continue
        qp.save()
        qp.translate(size / 2 + layer.x * ppm, size / 2 + layer.y * ppm)
        qp.rotate(layer.rotation)
        s = layer.scale * ppm
        qp.scale(s, s)
        qp.setOpacity(layer.opacity)
        qp.drawImage(QPointF(-src.width() / 2, -src.height() / 2), src)
        qp.restore()
    qp.end()
    return img


_BAYER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=np.float32)


def tone_preview(p: Project, size: int = 640) -> QImage:
    """Quick local approximation of the result inside the recording ring (guide only)."""
    src = compose(p, size).convertToFormat(QImage.Format.Format_ARGB32)
    ptr = src.constBits()
    ptr.setsize(size * size * 4)
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(size, size, 4).astype(np.float32)
    b, g, r, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    t = p.tone
    lum = 0.299 * r + 0.587 * g + 0.114 * b + t.brightness
    if t.gamma:
        lum = 255.0 * np.power(np.clip(lum, 0, 255) / 255.0, 2.2)
    lum = np.clip(lum, 0, 255)
    levels = max(2, t.levels if p.kind == "cd" else 2)
    step = 255.0 / (levels - 1)
    strength = t.dither / 100.0
    yy, xx = np.mgrid[0:size, 0:size]
    thr = (np.tile(_BAYER, (size // 4 + 1, size // 4 + 1))[:size, :size] + 0.5) / 16.0
    thr = 0.5 + (thr - 0.5) * strength
    base = np.floor(lum / step)
    frac = lum / step - base
    v = np.minimum(levels - 1, base + (frac > thr))
    gray = (v * step).astype(np.uint8)
    ppm = size / (2.0 * p.canvas_radius)
    dist = np.hypot(xx - size / 2, yy - size / 2)
    ring = (dist >= p.geo.r0 * ppm) & (dist <= p.geo.r1 * ppm)
    out = np.zeros((size, size, 4), dtype=np.uint8)
    out[..., 0] = out[..., 1] = out[..., 2] = gray
    out[..., 3] = 255
    out[a < 8] = (128, 128, 128, 255)
    out[~ring] = 0
    img = QImage(out.data, size, size, size * 4, QImage.Format.Format_ARGB32)
    return img.copy()


def disc_outline(p: Project, size: int, extras: bool = True) -> QImage:
    """Transparent image with the ring outlines, used over previews."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    qp = QPainter(img)
    qp.setRenderHint(QPainter.RenderHint.Antialiasing)
    ppm = size / (2.0 * p.canvas_radius)
    c = size / 2
    qp.setPen(QPen(QColor(120, 160, 255, 200), 1.5))
    qp.setBrush(Qt.BrushStyle.NoBrush)
    for r in (p.geo.r0, p.geo.r1):
        qp.drawEllipse(QPointF(c, c), r * ppm, r * ppm)
    qp.end()
    return img


def disc_path(p: Project) -> QPainterPath:
    path = QPainterPath()
    r = {"cd": 60.0, "dvd": 60.0, "bd": 60.0}[p.kind]
    path.addEllipse(QRectF(-r, -r, 2 * r, 2 * r))
    hole = 7.5 if p.kind == "cd" else 7.5
    inner = QPainterPath()
    inner.addEllipse(QRectF(-hole, -hole, 2 * hole, 2 * hole))
    return path.subtracted(inner)


_ = QBrush
