# SPDX-License-Identifier: GPL-3.0-or-later
"""Disc Image Studio for Linux: PyQt6 front-end for the upstream disc-image-studio CLI."""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import QElapsedTimer, QPointF, QProcess, QRectF, QSize, QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QAction, QBrush, QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPen,
                         QPixmap)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                             QFrame, QGridLayout, QGraphicsEllipseItem, QGraphicsPixmapItem, QGraphicsScene,
                             QGraphicsView, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
                             QPushButton, QSizePolicy, QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
                             QGraphicsItem, QGraphicsPathItem)

from . import compose, theme
from .core import (CONFIG_DIR, CLI_BIN, KIND_NAMES, KINDS, Layer, Project, burn_command, burn_tools,
                   cli_available, data_region, spin_rpm, detect_disc, generate_args, human_size, burn_image, list_drives, load_presets, output_path,
                   preset_title, projection_args, readback_args)

STYLE = theme.stylesheet()   # kept for tests that import it; the app re-applies it when the Material You palette changes

ASSETS = Path(__file__).with_name("assets")


def logo_pixmap() -> QPixmap:
    return QPixmap(str(ASSETS / "logo.png"))


def rounded_logo(size: int) -> QPixmap:
    """The project logo with soft corners, scaled for the rail."""
    from PyQt6.QtGui import QPainterPath as _P
    src = logo_pixmap()
    out = QPixmap(size * 2, size * 2)
    out.fill(Qt.GlobalColor.transparent)
    q = QPainter(out)
    q.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    path = _P()
    path.addRoundedRect(QRectF(0, 0, size * 2, size * 2), size * 0.45, size * 0.45)
    q.setClipPath(path)
    q.drawPixmap(0, 0, src.scaled(size * 2, size * 2, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    q.end()
    out.setDevicePixelRatio(2.0)
    return out


CACHE = Path(tempfile.gettempdir()) / f"discstudio-{os.getuid()}"


def h1(text: str, sub: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 4)
    a = QLabel(text)
    a.setObjectName("h1")
    lay.addWidget(a)
    if sub:
        b = QLabel(sub)
        b.setObjectName("sub")
        b.setProperty("hdr", True)
        b.setWordWrap(True)
        lay.addWidget(b)
    return w


def spin(lo, hi, val, dec=2, step=None, suffix="") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    if step:
        s.setSingleStep(step)
    if suffix:
        s.setSuffix(suffix)
    return s


class ScaledImage(QLabel):
    """Shows a pixmap scaled to whatever space it gets (keeps aspect ratio), so layouts can shrink and grow."""

    def __init__(self, text: str = ""):
        super().__init__(text)
        self._pm: QPixmap | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(48, 48)

    def minimumSizeHint(self):  # noqa: N802
        return QSize(48, 48)

    def sizeHint(self):  # noqa: N802
        return QSize(240, 240)

    def setPixmap(self, pm) -> None:  # noqa: N802
        self._pm = pm
        self.setText("")
        self.update()

    def paintEvent(self, e):  # noqa: N802
        if self._pm is None or self._pm.isNull():
            return super().paintEvent(e)
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pm = self._pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        qp.drawPixmap((self.width() - pm.width()) // 2, (self.height() - pm.height()) // 2, pm)


class ElidedLabel(QLabel):
    """One-line label that shortens long paths in the middle instead of forcing the layout wide."""

    def __init__(self, text: str = "", strong: bool = False):
        super().__init__()
        self._full = ""
        self._strong = strong                 # True = main text colour, False = secondary colour
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self.setToolTip(text)
        self.update()

    def minimumSizeHint(self):  # noqa: N802
        return QSize(40, self.fontMetrics().height() + 4)

    def sizeHint(self):  # noqa: N802
        return QSize(self.fontMetrics().horizontalAdvance(self._full) + 4, self.fontMetrics().height() + 4)

    def paintEvent(self, _e):  # noqa: N802
        qp = QPainter(self)
        qp.setPen(QColor(theme.P.on_surface if self._strong else theme.P.on_surface_variant))   # QSS does not set the palette
        qp.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, self.width()))


class WavyProgress(QProgressBar):
    """M3 Expressive wavy progress indicator: a moving wave for the done part, a flat track for the rest."""

    def __init__(self):
        super().__init__()
        self.setTextVisible(True)
        self.setMinimumHeight(34)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._phase = (self._phase + 0.35) % 6.2832
        self.update()

    def showEvent(self, e):  # noqa: N802
        self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e):  # noqa: N802
        self._timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _e):  # noqa: N802
        import math
        pal = theme.P
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        text = self.text() if self.minimum() != self.maximum() else ""
        tw = qp.fontMetrics().horizontalAdvance(text) + 34 if text else 0
        x0, x1 = 6.0, float(w - 6 - tw)
        cy = h / 2
        span = self.maximum() - self.minimum()
        frac = 1.0 if span == 0 else (self.value() - self.minimum()) / span
        frac = max(0.0, min(1.0, frac))
        xe = x0 + (x1 - x0) * frac
        # inactive track, with a small gap after the wave
        qp.setPen(QPen(qcolor_(pal.surface_highest), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if xe + 8 < x1:
            qp.drawLine(QPointF(xe + 8, cy), QPointF(x1, cy))
        # active wave
        amp, wl = 4.0, 26.0
        qp.setPen(QPen(qcolor_(pal.primary), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if xe > x0 + 1:
            from PyQt6.QtGui import QPainterPath as _Path
            path = _Path()
            x = x0
            path.moveTo(x, cy + amp * math.sin(self._phase))
            while x < xe:
                x = min(xe, x + 2)
                path.lineTo(x, cy + amp * math.sin((x - x0) / wl * 6.2832 + self._phase))
            qp.setBrush(Qt.BrushStyle.NoBrush)
            qp.drawPath(path)
        if text:
            qp.setPen(qcolor_(pal.on_surface_variant))
            qp.drawText(QRectF(x1 + 6, 0, tw - 12, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)


def qcolor_(h: str, a: int = 255):
    return theme.qcolor(h, a)


class Runner:
    """Runs the CLI (or any command) with QProcess and streams lines to a callback."""

    def __init__(self, on_line, on_done):
        self.on_line, self.on_done = on_line, on_done
        self.proc: QProcess | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning

    def start(self, program: str, args: list[str]) -> None:
        self.proc = QProcess()
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(lambda code, _s: self.on_done(code))
        self.proc.errorOccurred.connect(lambda e: self.on_done(-1) if e == QProcess.ProcessError.FailedToStart else None)
        self.proc.start(program, args)

    def _read(self) -> None:
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in data.replace("\r", "\n").split("\n"):
            if line.strip():
                self.on_line(line)

    def stop(self) -> None:
        if self.running:
            self.proc.terminate()


class Studio(QMainWindow):
    NAV = [("Home", "⌂"), ("Design", "✎"), ("Preview", "◉"), ("Export", "⇪"), ("Burn", "🔥")]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Disc Image Studio")
        self.setAcceptDrops(True)
        self.resize(1360, 860)
        self.presets = load_presets()
        self.p = Project()
        self.apply_kind("cd", "cd-80")
        self.dirty = False
        self._building = False

        root = QWidget()
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        side = QWidget()
        side.setObjectName("rail")
        self.rail = side
        side.setFixedWidth(196)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 12, 0, 8)
        brand_row = QWidget()
        br = QHBoxLayout(brand_row)
        br.setContentsMargins(14, 0, 6, 6)
        br.setSpacing(10)
        self.logo = QLabel()
        self.logo.setFixedSize(40, 40)
        self.logo.setPixmap(rounded_logo(40))
        title = QLabel("Disc Image\nStudio")
        title.setObjectName("brand")
        br.addWidget(self.logo)
        br.addWidget(title, 1)
        self.brand = title                       # the text hides when the rail collapses; the logo stays
        sl.addWidget(brand_row)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        for name, icon in self.NAV:
            self.nav.addItem(f"{icon}   {name}")
        self._level = 0
        self._collapsed = False
        self.nav.currentRowChanged.connect(self.goto)
        sl.addWidget(self.nav, 1)
        self.proj_label = QLabel("")
        self.proj_label.setObjectName("sub")
        self.proj_label.setWordWrap(True)
        self.proj_label.setContentsMargins(14, 0, 8, 4)
        sl.addWidget(self.proj_label)
        h.addWidget(side)

        self.stack = QStackedWidget()
        h.addWidget(self.stack, 1)
        self.home = HomePage(self)
        self.design = DesignPage(self)
        self.preview = PreviewPage(self)
        self.export = ExportPage(self)
        self.burn = BurnPage(self)
        self.pages = [self.home, self.design, self.preview, self.export, self.burn]
        for cb in self.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(8)
        for pg in self.pages:
            self.stack.addWidget(pg)

        self.statusBar().showMessage("Ready" if cli_available() else f"CLI missing at {CLI_BIN}: run install.sh")
        self._menu()
        self.nav.setCurrentRow(0)
        self.refresh_all()

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):  # noqa: N802
        files = dropped_files(e)
        if files:
            e.acceptProposedAction()
            self.nav.setCurrentRow(1)
            self.design.add_paths(files)


    # --- adaptive layout -----------------------------------------------------
    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self.apply_density()

    def apply_density(self) -> None:
        """Tighter spacing and a smaller rail as the window shrinks, so nothing needs a scroll bar."""
        H, W = self.height(), self.width()
        level = 0 if H >= 880 else 1 if H >= 760 else 2
        collapsed = W < 1300
        if level != self._level:
            self._level = level
            theme.set_scale((1.0, 0.88, 0.78)[level])
            QApplication.instance().setStyleSheet(theme.stylesheet())
            m = (22, 14, 8)[level]
            for pg in self.pages:
                lay = pg.layout()
                if lay is not None:
                    lay.setContentsMargins(m, m, m, m)
            for pg in self.pages:
                for lab in pg.findChildren(QLabel):
                    if lab.property("hdr"):
                        lab.setVisible(level < 2)
        if collapsed != self._collapsed:
            self._collapsed = collapsed
            self.rail.setFixedWidth(76 if collapsed else 196)
            for i, (name, icon) in enumerate(self.NAV):
                self.nav.item(i).setText(icon if collapsed else f"{icon}   {name}")
                self.nav.item(i).setToolTip(name)
            self.brand.setVisible(not collapsed)
            self.logo.parentWidget().layout().setContentsMargins(14 if not collapsed else 18, 0, 6, 6)
            self.proj_label.setVisible(not collapsed)

    # --- menu / project -----------------------------------------------------
    def _menu(self) -> None:
        m = self.menuBar().addMenu("&File")
        for text, key, fn in (("&New project…", QKeySequence.StandardKey.New, self.home.new_project),
                              ("&Open project…", QKeySequence.StandardKey.Open, self.open_project),
                              ("&Save", QKeySequence.StandardKey.Save, self.save_project),
                              ("Save &as…", QKeySequence("Ctrl+Shift+S"), lambda: self.save_project(True)),
                              ("&Quit", QKeySequence.StandardKey.Quit, self.close)):
            a = QAction(text, self)
            a.setShortcut(key)
            a.triggered.connect(fn)
            m.addAction(a)

    def goto(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        pg = self.pages[row]
        if hasattr(pg, "on_show"):
            pg.on_show()

    def apply_kind(self, kind: str, preset_id: str | None = None) -> None:
        self.p.kind = kind
        pl = self.presets[kind]
        pr = next((x for x in pl if x["id"] == preset_id), pl[0])
        self.p.apply_preset(pr)
        if kind == "cd":
            self.p.volume_label = "CD_IMAGE"
        elif kind == "dvd":
            self.p.volume_label = "DVD_IMAGE"
        else:
            self.p.volume_label = "BD_IMAGE"

    def refresh_all(self) -> None:
        self.proj_label.setText(f"{self.p.name}\n{KIND_NAMES[self.p.kind]} · {self.p.preset_id}")
        for pg in (self.home, self.design, self.preview, self.export, self.burn):
            if hasattr(pg, "refresh"):
                pg.refresh()

    def open_project(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Open project", self.p.output_dir, "Projects (*.discproj)")
        if f:
            self.load_project(f)

    def load_project(self, f: str) -> None:
        try:
            self.p = Project.from_json(Path(f).read_text("utf-8"))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Open project", f"Could not read project:\n{e}")
            return
        self.p.path = f
        self.home.remember(f)
        self.refresh_all()
        self.nav.setCurrentRow(1)

    def save_project(self, as_new: bool = False) -> bool:
        if as_new or not self.p.path:
            f, _ = QFileDialog.getSaveFileName(self, "Save project", str(Path(self.p.output_dir) / (self.p.name + ".discproj")),
                                               "Projects (*.discproj)")
            if not f:
                return False
            if not f.endswith(".discproj"):
                f += ".discproj"
            self.p.path = f
            folder = str(Path(f).parent)
            if folder != self.p.output_dir and QMessageBox.question(
                    self, "Output folder", f"Also save exported images in\n{folder} ?") == QMessageBox.StandardButton.Yes:
                self.p.output_dir = folder
                self.export.refresh()
        Path(self.p.path).write_text(self.p.to_json(), "utf-8")
        self.home.remember(self.p.path)
        self.statusBar().showMessage(f"Saved {self.p.path}", 4000)
        self.export.refresh()
        return True

    def composite_to(self, size: int, name: str = "composite") -> str:
        CACHE.mkdir(parents=True, exist_ok=True)
        path = CACHE / f"{name}-{size}.png"
        compose.compose(self.p, size).save(str(path))
        return str(path)

    def closeEvent(self, e):  # noqa: N802
        self.export.runner.stop()
        self.burn.runner.stop()
        det = getattr(self.burn, "_detect", None)
        if det is not None and not det.wait(1500):      # a slow drive read: don't hang on exit
            det.terminate()
            det.wait(500)
        super().closeEvent(e)


# ---------------------------------------------------------------------------
class HomePage(QWidget):
    def __init__(self, win: Studio):
        super().__init__()
        self.setObjectName("page")
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.addWidget(h1("Draw on a disc", "Turn an image into data that shows up as a visible picture on a blank CD, DVD or Blu-ray-R. "
                         "Use sacrificial test discs while experimenting."))
        row = QHBoxLayout()
        for kind, blurb in (("cd", "Audio WAV+CUE or Mode 1 ISO"), ("dvd", "Fast dispersion ISO"), ("bd", "25 GB BD-R / BD-RE")):
            b = QPushButton(f"New {KIND_NAMES[kind]} project\n{blurb}")
            b.setMinimumHeight(74)
            b.clicked.connect(lambda _=False, k=kind: self.new_project(k))
            row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(QLabel("Recent projects"))
        self.recent = QListWidget()
        self.recent.setObjectName("layers")
        self.recent.itemActivated.connect(lambda it: win.load_project(it.data(Qt.ItemDataRole.UserRole)))
        lay.addWidget(self.recent, 1)
        o = QPushButton("Open project…")
        o.clicked.connect(win.open_project)
        lay.addWidget(o, 0, Qt.AlignmentFlag.AlignLeft)
        self.cfg = CONFIG_DIR / "recent.json"
        self.refresh()

    def _recents(self) -> list[str]:
        try:
            return [x for x in json.loads(self.cfg.read_text()) if Path(x).exists()]
        except Exception:  # noqa: BLE001
            return []

    def remember(self, f: str) -> None:
        r = [f] + [x for x in self._recents() if x != f]
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text(json.dumps(r[:12]))
        self.refresh()

    def refresh(self) -> None:
        self.recent.clear()
        for f in self._recents():
            it = QListWidgetItem(f"{Path(f).stem}    —    {f}")
            it.setData(Qt.ItemDataRole.UserRole, f)
            self.recent.addItem(it)

    def new_project(self, kind: str | None = None) -> None:
        if not isinstance(kind, str):
            kind = "cd"
        self.win.p = Project(name=f"New {KIND_NAMES[kind]} disc")
        self.win.apply_kind(kind)
        self.win.refresh_all()
        self.win.nav.setCurrentRow(1)


# ---------------------------------------------------------------------------
class LayerItem(QGraphicsPixmapItem):
    def __init__(self, layer: Layer, page: "DesignPage"):
        super().__init__()
        self.layer, self.page = layer, page
        img = compose.load_image(layer.path)
        self.setPixmap(QPixmap.fromImage(img))
        self.setOffset(-img.width() / 2, -img.height() / 2)
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.sync_from_layer()

    def sync_from_layer(self) -> None:
        L = self.layer
        self.setPos(L.x, L.y)
        self.setScale(L.scale)
        self.setRotation(L.rotation)
        self.setOpacity(L.opacity)
        self.setVisible(L.visible)

    def itemChange(self, change, value):  # noqa: N802
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self.page.syncing:
            self.layer.x, self.layer.y = self.pos().x(), self.pos().y()
            self.page.item_moved(self.layer)
        return super().itemChange(change, value)


def dropped_files(event) -> list[str]:
    return [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]


class DiscView(QGraphicsView):
    wheelScaled = pyqtSignal(float)
    filesDropped = pyqtSignal(list)

    def minimumSizeHint(self):  # noqa: N802
        return QSize(120, 120)

    def sizeHint(self):  # noqa: N802
        return QSize(560, 560)

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):  # noqa: N802
        files = dropped_files(e)
        if files:
            e.acceptProposedAction()
            self.filesDropped.emit(files)

    def __init__(self, scene):
        super().__init__(scene)
        self.setAcceptDrops(True)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self.fitInView(QRectF(-64, -64, 128, 128), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, e):  # noqa: N802
        self.wheelScaled.emit(1.06 if e.angleDelta().y() > 0 else 1 / 1.06)


class DesignPage(QWidget):
    def __init__(self, win: Studio):
        super().__init__()
        self.setObjectName("page")
        self.win = win
        self.syncing = False
        self.items: dict[int, LayerItem] = {}
        self.scene = QGraphicsScene(-64, -64, 128, 128)
        self.scene.selectionChanged.connect(self.scene_selected)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)

        # left: layers
        left = QVBoxLayout()
        left.addWidget(h1("Design"))
        box = QGroupBox("Layers")
        bl = QVBoxLayout(box)
        self.list = QListWidget()
        self.list.setObjectName("layers")
        self.list.currentRowChanged.connect(self.list_selected)
        bl.addWidget(self.list)
        r = QHBoxLayout()
        for txt, fn in (("Add…", self.add_images), ("Remove", self.remove_layer), ("▲", lambda: self.move_layer(-1)),
                        ("▼", lambda: self.move_layer(1))):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            r.addWidget(b)
        bl.addLayout(r)
        self.vis = QCheckBox("Visible")
        self.vis.toggled.connect(lambda v: self.set_prop("visible", v))
        bl.addWidget(self.vis)
        left.addWidget(box, 1)
        wrap = QWidget()
        wrap.setLayout(left)
        wrap.setMinimumWidth(170)
        wrap.setMaximumWidth(300)
        lay.addWidget(wrap)

        # centre: canvas
        centre = QVBoxLayout()
        self.view = DiscView(self.scene)
        self.view.wheelScaled.connect(self.wheel)
        self.view.filesDropped.connect(self.add_paths)
        centre.addWidget(self.view, 1)
        tip = QLabel("Drop images here or use Add… · drag a layer to move it · mouse wheel scales the selected layer · blue rings = recording area")
        tip.setObjectName("sub")
        tip.setWordWrap(True)
        centre.addWidget(tip)
        lay.addLayout(centre, 1)

        # right: properties + tone (compact two-column grids so the column stays short)
        right = QVBoxLayout()
        pb = QGroupBox("Selected layer")
        pg_ = QGridLayout(pb)
        self.px = spin(-80, 80, 0, 2, 0.5, " mm")
        self.py = spin(-80, 80, 0, 2, 0.5, " mm")
        self.pw = spin(1, 400, 100, 1, 1, " mm")
        self.pr = spin(-360, 360, 0, 1, 1, "°")
        self.po = spin(0, 100, 100, 0, 5, " %")
        for w_, pre in ((self.px, "X  "), (self.py, "Y  "), (self.pw, "W  "), (self.pr, "∠  "), (self.po, "α  ")):
            w_.setPrefix(pre)
            w_.setMinimumWidth(80)
        self.px.valueChanged.connect(lambda v: self.set_prop("x", v))
        self.py.valueChanged.connect(lambda v: self.set_prop("y", v))
        self.pw.valueChanged.connect(self.set_width)
        self.pr.valueChanged.connect(lambda v: self.set_prop("rotation", v))
        self.po.valueChanged.connect(lambda v: self.set_prop("opacity", v / 100))
        fit = QWidget()
        fl = QHBoxLayout(fit)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(6)
        b_fit = QPushButton("Fit")
        b_fit.setToolTip("Whole image inside the disc (longer side = disc diameter)")
        b_fit.clicked.connect(lambda: self.fit_layer(False))
        b_fill = QPushButton("Fill")
        b_fill.setToolTip("Cover the whole disc (shorter side = disc diameter); the long side is cropped")
        b_fill.clicked.connect(lambda: self.fit_layer(True))
        fl.addWidget(b_fit)
        fl.addWidget(b_fill)
        pg_.addWidget(self.px, 0, 0)
        pg_.addWidget(self.py, 0, 1)
        pg_.addWidget(self.pw, 1, 0)
        pg_.addWidget(self.pr, 1, 1)
        pg_.addWidget(self.po, 2, 0)
        pg_.addWidget(fit, 2, 1)
        right.addWidget(pb)

        tb = QGroupBox("Tone")
        tg = QGridLayout(tb)
        self.t_dither = QSlider(Qt.Orientation.Horizontal)
        self.t_dither.setRange(0, 100)
        self.t_dither_l = QLabel("75%")
        self.t_bright = QSpinBox()
        self.t_bright.setRange(-64, 64)
        self.t_bright.setPrefix("Brightness  ")
        self.t_gamma = QCheckBox("sRGB linearisation")
        self.t_levels = QComboBox()
        self.t_levels.addItems(["2 levels (B/W)", "4 levels"])
        self.t_levels_row_label = QLabel("Greys")
        self.bg = QComboBox()
        self.bg.addItems(["transparent", "white", "black"])
        self.bg.setToolTip("Background behind the layers")
        self.t_dither.valueChanged.connect(self.tone_changed)
        self.t_bright.valueChanged.connect(self.tone_changed)
        self.t_gamma.toggled.connect(self.tone_changed)
        self.t_levels.currentIndexChanged.connect(self.tone_changed)
        self.bg.currentTextChanged.connect(self.bg_changed)
        tg.addWidget(QLabel("Dither"), 0, 0)
        tg.addWidget(self.t_dither, 0, 1)
        tg.addWidget(self.t_dither_l, 0, 2)
        tg.addWidget(self.t_bright, 1, 0, 1, 3)
        tg.addWidget(self.t_gamma, 2, 0, 1, 3)
        tg.addWidget(self.t_levels_row_label, 3, 0)
        tg.addWidget(self.t_levels, 3, 1, 1, 2)
        tg.addWidget(QLabel("Background"), 4, 0)
        tg.addWidget(self.bg, 4, 1, 1, 2)
        self.tone_img = ScaledImage()
        tg.addWidget(self.tone_img, 5, 0, 1, 3)
        tg.setRowStretch(5, 1)
        right.addWidget(tb, 1)
        nxt = QPushButton("Next: Preview ▶")
        nxt.setObjectName("primary")
        nxt.clicked.connect(lambda: win.nav.setCurrentRow(2))
        right.addWidget(nxt)
        rw = QWidget()
        rw.setLayout(right)
        rw.setMinimumWidth(190)
        rw.setMaximumWidth(300)
        lay.addWidget(rw)

        self.tone_timer = QTimer(self, singleShot=True, interval=250)
        self.tone_timer.timeout.connect(self.update_tone_preview)
        self.disc_items: list = []

    # --- scene -----------------------------------------------------------------
    def build_scene(self) -> None:
        for it in self.scene.items():
            self.scene.removeItem(it)
        self.items.clear()
        p = self.win.p
        pen = QPen(QColor(theme.P.outline), 0.3)
        disc = QGraphicsEllipseItem(-60, -60, 120, 120)
        disc.setBrush(QBrush(QColor(theme.P.on_surface_variant)))
        disc.setPen(pen)
        disc.setZValue(-100)
        self.scene.addItem(disc)
        hole = QGraphicsEllipseItem(-7.5, -7.5, 15, 15)
        hole.setBrush(QBrush(QColor(theme.P.surface_lowest)))
        hole.setPen(pen)
        hole.setZValue(100)
        self.scene.addItem(hole)
        for r, col in ((p.geo.r0, theme.P.primary), (p.geo.r1, theme.P.primary)):
            ring = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
            ring.setPen(QPen(QColor(col), 0.45, Qt.PenStyle.DashLine))
            ring.setZValue(101)
            self.scene.addItem(ring)
        band = data_region(p)
        if band:
            ring = QGraphicsPathItem()
            from PyQt6.QtGui import QPainterPath as _P
            outer, inner = _P(), _P()
            outer.addEllipse(-band[1], -band[1], 2 * band[1], 2 * band[1])
            inner.addEllipse(-band[0], -band[0], 2 * band[0], 2 * band[0])
            ring.setPath(outer.subtracted(inner))
            ring.setBrush(QBrush(theme.qcolor(theme.P.tertiary, 120)))
            ring.setPen(QPen(Qt.PenStyle.NoPen))
            ring.setZValue(102)
            ring.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.scene.addItem(ring)
        # clip: layers outside the disc stay visible but dimmed by a mask ring
        for i, layer in enumerate(p.layers):
            it = LayerItem(layer, self)
            it.setZValue(len(p.layers) - i)
            self.scene.addItem(it)
            self.items[id(layer)] = it

    def build_scene_if_ready(self) -> None:
        if not self.syncing:
            self.build_scene()
            L = self.current()
            if L and id(L) in self.items:
                self.items[id(L)].setSelected(True)

    def refresh(self) -> None:
        self.syncing = True
        p = self.win.p
        self.build_scene()
        self.list.clear()
        for L in p.layers:
            self.list.addItem(L.name or Path(L.path).name)
        t = p.tone
        self.t_dither.setValue(t.dither)
        self.t_dither_l.setText(f"{t.dither}%")
        self.t_bright.setValue(t.brightness)
        self.t_gamma.setChecked(t.gamma)
        self.t_levels.setCurrentIndex(1 if t.levels == 4 else 0)
        cd = p.kind == "cd"
        self.t_levels.setVisible(cd)
        self.t_levels_row_label.setVisible(cd)
        self.bg.setCurrentText(p.background)
        self.syncing = False
        if p.layers:
            self.list.setCurrentRow(0)
        else:
            self.load_props(None)
        self.tone_timer.start()

    # --- layer ops -------------------------------------------------------------
    def current(self) -> Layer | None:
        r = self.list.currentRow()
        return self.win.p.layers[r] if 0 <= r < len(self.win.p.layers) else None

    def add_images(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add images", str(Path.home()),
                                                "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif *.webp)")
        self.add_paths(files)

    def add_paths(self, files: list[str]) -> None:
        exts = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp"}
        added = False
        for f in files:
            if Path(f).suffix.lower() not in exts:
                continue
            img = compose.load_image(f)
            if img.isNull():
                QMessageBox.warning(self, "Add image", f"Cannot read {f}")
                continue
            r = self.win.p.geo.r1
            L = Layer(path=f, name=Path(f).name)
            L.scale = (2 * r) / max(img.width(), img.height())
            self.win.p.layers.insert(0, L)
            added = True
        if added:
            self.refresh()
            self.list.setCurrentRow(0)

    def remove_layer(self) -> None:
        r = self.list.currentRow()
        if 0 <= r < len(self.win.p.layers):
            del self.win.p.layers[r]
            self.refresh()

    def move_layer(self, d: int) -> None:
        r, ls = self.list.currentRow(), self.win.p.layers
        n = r + d
        if 0 <= r < len(ls) and 0 <= n < len(ls):
            ls[r], ls[n] = ls[n], ls[r]
            self.refresh()
            self.list.setCurrentRow(n)

    def fit_layer(self, fill: bool = False) -> None:
        L = self.current()
        if L:
            img = compose.load_image(L.path)
            side = min(img.width(), img.height()) if fill else max(img.width(), img.height())
            L.scale = (2 * self.win.p.geo.r1) / side
            L.x = L.y = 0
            self.after_layer_edit(L)

    def list_selected(self, row: int) -> None:
        if self.syncing:
            return
        L = self.current()
        self.load_props(L)
        self.syncing = True
        self.scene.clearSelection()
        if L and id(L) in self.items:
            self.items[id(L)].setSelected(True)
        self.syncing = False

    def scene_selected(self) -> None:
        if self.syncing:
            return
        try:
            items = self.scene.selectedItems()
        except RuntimeError:             # scene already destroyed while the window is closing
            return
        for it in items:
            if isinstance(it, LayerItem) and it.layer in self.win.p.layers:
                self.list.setCurrentRow(self.win.p.layers.index(it.layer))
                return

    def load_props(self, L: Layer | None) -> None:
        self.syncing = True
        for w in (self.px, self.py, self.pw, self.pr, self.po, self.vis):
            w.setEnabled(L is not None)
        if L:
            img = compose.load_image(L.path)
            self.px.setValue(L.x)
            self.py.setValue(L.y)
            self.pw.setValue(L.scale * img.width())
            self.pr.setValue(L.rotation)
            self.po.setValue(L.opacity * 100)
            self.vis.setChecked(L.visible)
        self.syncing = False

    def set_prop(self, name: str, v) -> None:
        L = self.current()
        if self.syncing or not L:
            return
        setattr(L, name, v)
        self.after_layer_edit(L)

    def set_width(self, mm: float) -> None:
        L = self.current()
        if self.syncing or not L:
            return
        L.scale = mm / compose.load_image(L.path).width()
        self.after_layer_edit(L)

    def after_layer_edit(self, L: Layer) -> None:
        it = self.items.get(id(L))
        if it:
            self.syncing = True
            it.sync_from_layer()
            self.syncing = False
        self.load_props(L)
        self.tone_timer.start()

    def item_moved(self, L: Layer) -> None:
        self.syncing = True
        self.px.setValue(L.x)
        self.py.setValue(L.y)
        self.syncing = False
        self.tone_timer.start()

    def wheel(self, f: float) -> None:
        L = self.current()
        if L:
            L.scale *= f
            self.after_layer_edit(L)

    # --- tone ------------------------------------------------------------------
    def tone_changed(self) -> None:
        if self.syncing:
            return
        t = self.win.p.tone
        t.dither = self.t_dither.value()
        t.brightness = self.t_bright.value()
        t.gamma = self.t_gamma.isChecked()
        t.levels = 4 if self.t_levels.currentIndex() == 1 else 2
        self.t_dither_l.setText(f"{t.dither}%")
        self.tone_timer.start()

    def bg_changed(self, text: str) -> None:
        if not self.syncing:
            self.win.p.background = text
            self.tone_timer.start()

    def update_tone_preview(self) -> None:
        if not self.win.p.layers:
            self.tone_img.setPixmap(QPixmap())
            self.tone_img.setText("add an image")
            return
        img = compose.tone_preview(self.win.p, 320)
        self.tone_img.setPixmap(QPixmap.fromImage(img))


# ---------------------------------------------------------------------------
class PreviewPage(QWidget):
    def __init__(self, win: Studio):
        super().__init__()
        self.setObjectName("page")
        self.win = win
        self.runner = Runner(self.on_line, self.on_done)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        left = QVBoxLayout()
        left.addWidget(h1("Preview", "Check how the picture lands on the disc before writing anything."))
        self.img = ScaledImage("No preview yet")
        self.img.setObjectName("card")
        left.addWidget(self.img, 1)
        lay.addLayout(left, 1)

        right = QVBoxLayout()
        box = QGroupBox("Source")
        bf = QVBoxLayout(box)
        self.mode = QComboBox()
        self.mode.addItems(["Local tone preview (instant)", "Encoder projection (CLI)", "Read-back of exported image (CLI)"])
        bf.addWidget(self.mode)
        self.size = QComboBox()
        self.size.addItems(["800", "1200", "1600", "2400"])
        self.size.setCurrentIndex(1)
        sf = QHBoxLayout()
        sf.addWidget(QLabel("Size (px)"))
        sf.addWidget(self.size)
        bf.addLayout(sf)
        go = QPushButton("Render")
        go.setObjectName("primary")
        go.clicked.connect(self.render)
        bf.addWidget(go)
        sv = QPushButton("Save PNG…")
        sv.clicked.connect(self.save_png)
        bf.addWidget(sv)
        right.addWidget(box)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        right.addWidget(self.log, 1)
        nxt = QPushButton("Next: Export ▶")
        nxt.setObjectName("primary")
        nxt.clicked.connect(lambda: win.nav.setCurrentRow(3))
        right.addWidget(nxt)
        rw = QWidget()
        rw.setLayout(right)
        rw.setMinimumWidth(200)
        rw.setMaximumWidth(320)
        lay.addWidget(rw)
        self.pix: QPixmap | None = None
        self.out_png = ""

    def on_show(self) -> None:
        self.render()

    def refresh(self) -> None:
        pass

    def show_pix(self, pm: QPixmap) -> None:
        self.pix = pm
        self.img.setPixmap(pm)

    def render(self) -> None:
        p = self.win.p
        if not p.layers:
            self.img.setText("Add an image on the Design page first.")
            return
        mode = self.mode.currentIndex()
        size = int(self.size.currentText())
        if mode == 0:
            self.show_pix(QPixmap.fromImage(compose.tone_preview(p, min(size, 1200))))
            return
        if not cli_available():
            self.log.appendPlainText("CLI not installed.")
            return
        CACHE.mkdir(parents=True, exist_ok=True)
        self.out_png = str(CACHE / "preview.png")
        if mode == 1:
            comp = self.win.composite_to(2048, "preview")
            args = projection_args(p, comp, self.out_png, size)
            if args is None:
                self.log.appendPlainText("Blu-ray has no CLI projection; showing the local preview instead.")
                self.show_pix(QPixmap.fromImage(compose.tone_preview(p, min(size, 1200))))
                return
        else:
            src = burn_image(p)
            if not src.exists():
                self.log.appendPlainText(f"Export first: {src} does not exist.")
                return
            args = readback_args(p, str(src), self.out_png, size)
            if args is None:
                self.log.appendPlainText("Blu-ray has no CLI read-back preview.")
                return
        self.log.appendPlainText("$ disc-image-studio " + " ".join(shlex.quote(a) for a in args))
        Path(self.out_png).unlink(missing_ok=True)
        self.runner.start(str(CLI_BIN), args)

    def on_line(self, line: str) -> None:
        self.log.appendPlainText(line)

    def on_done(self, code: int) -> None:
        if code == 0 and Path(self.out_png).exists():
            self.show_pix(QPixmap(self.out_png))
        else:
            self.log.appendPlainText(f"CLI exited with {code}")

    def save_png(self) -> None:
        if not self.pix:
            return
        f, _ = QFileDialog.getSaveFileName(self, "Save preview", str(Path.home() / "disc-preview.png"), "PNG (*.png)")
        if f:
            self.pix.save(f)


# ---------------------------------------------------------------------------
class ExportPage(QWidget):
    def __init__(self, win: Studio):
        super().__init__()
        self.setObjectName("page")
        self.win = win
        self.runner = Runner(self.on_line, self.on_done)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        left = QVBoxLayout()
        left.addWidget(h1("Export", "Generate the image file. Burn it from the next page, or with any tool you prefer."))

        gb = QGroupBox("Disc")
        gf = QFormLayout(gb)
        self.name = QLineEdit()
        self.name.textEdited.connect(self.fields_changed)
        self.kind = QComboBox()
        for k in KINDS:
            self.kind.addItem(KIND_NAMES[k], k)
        self.kind.activated.connect(self.kind_changed)
        self.preset = QComboBox()
        self.preset.activated.connect(self.preset_changed)
        self.geom = QLabel()
        self.geom.setObjectName("sub")
        self.geom.setWordWrap(True)
        gf.addRow("Project name", self.name)
        self.proj_path = ElidedLabel()
        self.proj_path.setObjectName("sub")
        self.proj_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        pbtn = QHBoxLayout()
        for txt, fn in (("Save project…", lambda: self.win.save_project(True)), ("Save", self.win.save_project),
                        ("Open project…", self.win.open_project)):
            b = QPushButton(txt)
            b.clicked.connect(lambda _=False, f=fn: f())
            pbtn.addWidget(b)
        pbtn.addStretch(1)
        gf.addRow("Project file", pbtn)
        gf.addRow("", self.proj_path)
        gf.addRow("Disc type", self.kind)
        gf.addRow("Disc preset", self.preset)
        gf.addRow("", self.geom)
        egrid = QGridLayout()
        egrid.setHorizontalSpacing(10)
        egrid.setVerticalSpacing(8)
        egrid.addWidget(gb, 0, 0)

        ob = QGroupBox("Output")
        of = QFormLayout(ob)
        self.outdir = QLineEdit()
        self.outdir.textEdited.connect(self.fields_changed)
        bd = QPushButton("Browse…")
        bd.clicked.connect(self.browse_dir)
        dr = QHBoxLayout()
        dr.addWidget(self.outdir, 1)
        dr.addWidget(bd)
        of.addRow("Folder", dr)
        self.cd_mode = QComboBox()
        self.cd_mode.addItems(["Audio track (WAV + CUE)", "Data disc (Mode 1 ISO)"])
        self.cd_mode.activated.connect(self.fields_changed)
        self.interleave = QCheckBox("CD-DA delay interleave")
        self.interleave.setToolTip("Keep on for cdrecord WAV")
        self.interleave.toggled.connect(self.fields_changed)
        self.compat = QComboBox()
        self.compat.addItems(["Off", "1 – light", "2 – strong black", "3 – strong black (zonal)"])
        self.compat.activated.connect(self.fields_changed)
        self.invert = QCheckBox("Swap 3T/6T assignment")
        self.invert.toggled.connect(self.fields_changed)
        of.addRow("CD content", self.cd_mode)
        of.addRow("", self.interleave)
        of.addRow("DVD write compatibility", self.compat)
        of.addRow("", self.invert)
        self.out_label = ElidedLabel()
        self.out_label.setObjectName("sub")
        of.addRow("Output file", self.out_label)
        egrid.addWidget(ob, 1, 0, 1, 2)

        fb = QGroupBox("Files on the disc (optional)")
        ff = QFormLayout(fb)
        self.files = QLineEdit()
        self.files.setPlaceholderText("Folder whose contents are stored alongside the picture")
        self.files.textEdited.connect(self.fields_changed)
        bf = QPushButton("Choose…")
        bf.clicked.connect(self.browse_files)
        fr = QHBoxLayout()
        fr.addWidget(self.files, 1)
        fr.addWidget(bf)
        ff.addRow("Folder", fr)
        self.label = QLineEdit()
        self.label.textEdited.connect(self.fields_changed)
        ff.addRow("Volume label", self.label)
        self.outer = QComboBox()
        self.outer.addItems(["Inner ring", "Outer ring"])
        self.outer.activated.connect(self.fields_changed)
        ff.addRow("Position", self.outer)
        egrid.addWidget(fb, 0, 1)
        egrid.setRowStretch(2, 1)
        left.addLayout(egrid)
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        lay.addWidget(lw, 1)

        right = QVBoxLayout()
        gen = QPushButton("Generate image")
        gen.setObjectName("primary")
        gen.setMinimumHeight(42)
        gen.clicked.connect(self.generate)
        right.addWidget(gen)
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(self.runner.stop)
        right.addWidget(self.cancel)
        self.bar = WavyProgress()
        self.bar.setRange(0, 0)
        self.bar.hide()
        right.addWidget(self.bar)
        self.disc = DiscProgress()
        self.disc.setMinimumSize(80, 80)
        right.addWidget(self.disc, 1)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        right.addWidget(self.log, 1)
        nxt = QPushButton("Next: Burn ▶")
        nxt.setObjectName("primary")
        nxt.clicked.connect(lambda: win.nav.setCurrentRow(4))
        right.addWidget(nxt)
        rw = QWidget()
        rw.setLayout(right)
        rw.setMinimumWidth(240)
        rw.setMaximumWidth(420)
        lay.addWidget(rw)
        self._loading = False

    def refresh(self) -> None:
        p = self.win.p
        self._loading = True
        self.name.setText(p.name)
        self.name.setCursorPosition(0)
        self.proj_path.setText(p.path or "Not saved yet (File ▸ Save, or the buttons above)")
        self.kind.setCurrentIndex(KINDS.index(p.kind))
        self.preset.clear()
        for pr in self.win.presets[p.kind]:
            self.preset.addItem(preset_title(pr), pr["id"])
        i = self.preset.findData(p.preset_id)
        self.preset.setCurrentIndex(max(0, i))
        self.outdir.setText(p.output_dir)
        self.outdir.setCursorPosition(0)
        self.cd_mode.setCurrentIndex(0 if p.cd_audio else 1)
        self.cd_mode.setEnabled(p.kind == "cd")
        self.interleave.setChecked(p.cd_interleave)
        self.interleave.setEnabled(p.kind == "cd" and p.cd_audio)
        self.compat.setCurrentIndex(p.dvd_compat)
        self.compat.setEnabled(p.kind == "dvd")
        self.invert.setChecked(p.bd_invert)
        self.invert.setEnabled(p.kind == "bd")
        self.files.setText(p.data_dir)
        self.files.setCursorPosition(0)
        self.label.setText(p.volume_label)
        self.label.setCursorPosition(0)
        self.outer.setCurrentIndex(1 if p.files_outer else 0)
        files_ok = not (p.kind == "cd" and p.cd_audio)
        for w in (self.files, self.label, self.outer):
            w.setEnabled(files_ok)
        g = p.geo
        self.geom.setText(f"{g.r0:.3f}–{g.r1:.3f} mm · {g.sectors:,} sectors (usable {g.usable:,})")
        self.out_label.setText(str(output_path(p)))
        self._loading = False
        self.disc.set_project(p)

    def kind_changed(self) -> None:
        self.win.apply_kind(self.kind.currentData())
        self.win.refresh_all()

    def preset_changed(self) -> None:
        self.win.apply_kind(self.win.p.kind, self.preset.currentData())
        self.win.refresh_all()

    def fields_changed(self, *_a) -> None:
        if self._loading:
            return
        p = self.win.p
        p.name = self.name.text() or "Untitled"
        p.output_dir = self.outdir.text()
        p.cd_audio = self.cd_mode.currentIndex() == 0
        p.cd_interleave = self.interleave.isChecked()
        p.dvd_compat = self.compat.currentIndex()
        p.bd_invert = self.invert.isChecked()
        p.data_dir = self.files.text()
        p.volume_label = self.label.text() or "DISC_IMAGE"
        p.files_outer = self.outer.currentIndex() == 1
        self.win.proj_label.setText(f"{p.name}\n{KIND_NAMES[p.kind]} · {p.preset_id}")
        self._loading = True
        self.cd_mode.setEnabled(p.kind == "cd")
        self.interleave.setEnabled(p.kind == "cd" and p.cd_audio)
        files_ok = not (p.kind == "cd" and p.cd_audio)
        for w in (self.files, self.label, self.outer):
            w.setEnabled(files_ok)
        self.out_label.setText(str(output_path(p)))
        self._loading = False
        self.disc.set_project(p)
        self.win.design.build_scene_if_ready()

    def browse_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Output folder", self.outdir.text())
        if d:
            self.outdir.setText(d)
            self.outdir.setCursorPosition(0)
            self.fields_changed()

    def browse_files(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Folder to store on the disc", self.files.text() or str(Path.home()))
        if d:
            self.files.setText(d)
            self.files.setCursorPosition(0)
            self.fields_changed()

    def generate(self) -> None:
        p = self.win.p
        if self.runner.running:
            return
        if not cli_available():
            QMessageBox.warning(self, "CLI missing", f"Run install.sh first. Expected {CLI_BIN}")
            return
        if not p.layers:
            QMessageBox.information(self, "Nothing to draw", "Add an image on the Design page first.")
            return
        out = output_path(p)
        Path(p.output_dir).mkdir(parents=True, exist_ok=True)
        if out.exists():
            if QMessageBox.question(self, "Overwrite?", f"{out} exists. Replace it?") != QMessageBox.StandardButton.Yes:
                return
            for ex in (out, out.with_suffix(".cue"), Path(str(out) + ".json")):
                ex.unlink(missing_ok=True)
        self.log.clear()
        self.log.appendPlainText("Compositing layers at 8192 px…")
        QApplication.processEvents()
        comp = self.win.composite_to(8192, "export")
        args = generate_args(p, comp, str(out))
        self.log.appendPlainText("$ disc-image-studio " + " ".join(shlex.quote(a) for a in args))
        self.bar.setRange(0, 0)
        self.bar.show()
        self.disc.set_project(p)
        self.runner.start(str(CLI_BIN), args)

    def on_line(self, line: str) -> None:
        m = re.search(r"block\s+(\d+)/(\d+)", line)
        if m and int(m.group(2)):
            self.bar.setRange(0, 1000)
            f = int(m.group(1)) / int(m.group(2))
            self.bar.setValue(int(1000 * f))
            self.disc.set_fraction(f)
            return
        self.log.appendPlainText(line)

    def on_done(self, code: int) -> None:
        self.bar.hide()
        out = output_path(self.win.p)
        if code == 0 and out.exists():
            self.disc.set_fraction(1.0)
            self.log.appendPlainText(f"\nDone: {out} ({human_size(out.stat().st_size)})")
            self.win.statusBar().showMessage(f"Exported {out.name}", 6000)
            self.win.burn.refresh()
        else:
            self.log.appendPlainText(f"\nFailed (exit {code}).")


# ---------------------------------------------------------------------------
class DetectThread(QThread):
    """Reads the disc in the background so a slow drive never freezes the window."""
    done = pyqtSignal(dict)

    def __init__(self, dev: str):
        super().__init__()
        self.dev = dev

    def run(self) -> None:
        try:
            d = detect_disc(self.dev)
        except Exception as e:  # noqa: BLE001
            d = {"error": f"Could not read the disc: {e}"}
        self.done.emit(d)


class DiscProgress(QWidget):
    """Disc picture that fills in from the inner edge outward as work progresses."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(80, 80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pix: QPixmap | None = None
        self.frac = 0.0
        self.r0 = self.r1 = 0.0
        self.band: tuple[float, float] | None = None
        self.rpm = 0.0
        self.angle = 0.0
        self.SLOW = 1.0                        # 1 = real speed; the Burn page can switch to slow motion
        self._clock = QElapsedTimer()
        self._spin = QTimer(self)
        self._spin.setInterval(8)              # as fast as the screen refreshes
        self._spin.timeout.connect(self._advance)

    def set_spin(self, rpm: float) -> None:
        self.rpm = max(0.0, rpm)
        if self.rpm > 0:
            if not self._spin.isActive():
                self._clock.start()
                self._spin.start()
        else:
            self._spin.stop()
        self.update()

    def _advance(self) -> None:
        dt = self._clock.restart() / 1000.0                # real elapsed seconds since the last frame
        self.angle = (self.angle + self.rpm / 60.0 * 360.0 / self.SLOW * dt) % 360.0
        self.update()

    def set_project(self, p: Project) -> None:
        self.r0, self.r1 = p.geo.r0, p.geo.r1
        self.band = data_region(p)
        self.pix = QPixmap.fromImage(compose.tone_preview(p, 600)) if p.layers else None
        self.frac = 0.0
        self.update()

    def set_fraction(self, f: float) -> None:
        self.frac = max(0.0, min(1.0, f))
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        from PyQt6.QtGui import QPainterPath
        qp = QPainter(self)
        qp.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        room = 24 if self.rpm > 0 else 0                     # keep the RPM caption clear of the disc
        side = min(self.width(), self.height() - room) - 8
        rect = QRectF((self.width() - side) / 2, (self.height() - room - side) / 2, side, side)
        c = rect.center()
        qp.setBrush(QColor(theme.P.surface_container))
        qp.setPen(QPen(QColor(theme.P.outline_variant), 1))
        qp.drawEllipse(c, side / 2, side / 2)
        if not self.pix or self.r1 <= 0:
            qp.setPen(QColor(theme.P.on_surface_variant))
            qp.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Add an image on Design\nto see progress here")
            return
        qp.save()
        qp.translate(c)
        qp.rotate(self.angle)
        qp.translate(-c)
        qp.setOpacity(0.22)
        qp.drawPixmap(rect, self.pix, QRectF(self.pix.rect()))
        qp.restore()
        # written area grows with the spiral: area fraction maps to radius
        rf = (self.r0 ** 2 + (self.r1 ** 2 - self.r0 ** 2) * self.frac) ** 0.5
        ppm = side / (2 * self.r1)
        clip = QPainterPath()
        clip.addEllipse(c, rf * ppm, rf * ppm)
        hole = QPainterPath()
        hole.addEllipse(c, self.r0 * ppm, self.r0 * ppm)
        qp.setClipPath(clip.subtracted(hole))
        qp.setOpacity(1.0)
        qp.save()
        qp.translate(c)
        qp.rotate(self.angle)
        qp.translate(-c)
        qp.drawPixmap(rect, self.pix, QRectF(self.pix.rect()))
        qp.restore()
        qp.setClipping(False)
        if self.band:
            b0, b1 = self.band
            ring = QPainterPath()
            ring.addEllipse(c, b1 * ppm, b1 * ppm)
            cut = QPainterPath()
            cut.addEllipse(c, b0 * ppm, b0 * ppm)
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(theme.qcolor(theme.P.tertiary, 130))
            qp.drawPath(ring.subtracted(cut))
        qp.setPen(QPen(QColor(theme.P.primary), 3))
        qp.setBrush(Qt.BrushStyle.NoBrush)
        qp.drawEllipse(c, rf * ppm, rf * ppm)
        if self.rpm > 0:
            qp.setPen(QColor(theme.P.on_surface))
            qp.drawText(QRectF(0, self.height() - 22, self.width(), 20), Qt.AlignmentFlag.AlignCenter,
                        f"≈ {self.rpm:,.0f} RPM" + ("" if self.SLOW == 1 else f"  ·  slow motion 1/{self.SLOW:.0f}"))


class BurnPage(QWidget):
    def __init__(self, win: Studio):
        super().__init__()
        self.setObjectName("page")
        self.win = win
        self.runner = Runner(self.on_line, self.on_done)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.addWidget(h1("Burn", "Experimental. Use blank, sacrificial discs. A write that fails part way usually ruins the disc."))
        gb = QGroupBox("Write")
        gf = QFormLayout(gb)
        self.image = ElidedLabel(strong=True)
        ib = QHBoxLayout()
        ib.addWidget(self.image, 1)
        lb = QPushButton("Load image…")
        lb.clicked.connect(self.load_image)
        ub = QPushButton("Use exported")
        ub.clicked.connect(self.use_exported)
        ib.addWidget(lb)
        ib.addWidget(ub)
        gf.addRow("Image", ib)
        self.disc_info = QLabel("Press Check disc.")
        self.disc_info.setWordWrap(True)
        self.use_preset = QPushButton("Use matching preset")
        self.use_preset.hide()
        self.use_preset.clicked.connect(self.apply_detected)
        chk = QPushButton("Check disc")
        chk.clicked.connect(self.check_disc)
        ir = QHBoxLayout()
        ir.addWidget(self.disc_info, 1)
        ir.addWidget(self.use_preset)
        ir.addWidget(chk)
        mb = QPushButton("Mount disc")
        mb.setToolTip("Mounts the disc: desktop mount first, then ~/disc (needs setup-disc-mount.sh)")
        mb.clicked.connect(self.mount_disc)
        ub2 = QPushButton("Unmount")
        ub2.clicked.connect(self.unmount_disc)
        ir.addWidget(mb)
        ir.addWidget(ub2)
        gf.addRow("Disc in drive", ir)
        self.detected: dict = {}
        self.drive = QComboBox()
        rb = QPushButton("Rescan")
        rb.clicked.connect(self.scan)
        dr = QHBoxLayout()
        dr.addWidget(self.drive, 1)
        dr.addWidget(rb)
        gf.addRow("Drive", dr)
        self.speed = QComboBox()
        self.speed.addItems(["Automatic", "1", "2", "4", "6", "8", "16"])
        sr = QHBoxLayout()
        sr.addWidget(self.speed)
        self.slowmo = QCheckBox("Slow-motion spin")
        self.slowmo.setToolTip("Real speed can look jittery on a 60 Hz screen (it spins faster than the screen can show)")
        self.slowmo.toggled.connect(lambda on: setattr(self.disc, "SLOW", 40.0 if on else 1.0))
        sr.addWidget(self.slowmo)
        sr.addStretch(1)
        gf.addRow("Speed", sr)
        self.tools = QLabel()
        self.tools.setObjectName("sub")
        gf.addRow("Tools", self.tools)
        self.cmd = QLineEdit()
        self.cmd.setReadOnly(True)
        gf.addRow("Command", self.cmd)
        lay.addWidget(gb)
        row = QHBoxLayout()
        self.go = QPushButton("Burn disc")
        self.go.setObjectName("danger")
        self.go.setMinimumHeight(40)
        self.go.clicked.connect(self.burn)
        self.stop = QPushButton("Abort")
        self.stop.clicked.connect(self.runner.stop)
        row.addWidget(self.go)
        row.addWidget(self.stop)
        row.addStretch(1)
        lay.addLayout(row)
        self.bar = WavyProgress()
        self.bar.setRange(0, 1000)
        self.bar.setFormat("Idle")
        lay.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        mid = QHBoxLayout()
        mid.addWidget(self.log, 1)
        self.disc = DiscProgress()
        mid.addWidget(self.disc, 1)
        lay.addLayout(mid, 1)
        self.speed.currentIndexChanged.connect(self.update_cmd)
        self.drive.currentIndexChanged.connect(self.update_cmd)

    def _run_mount(self, mount: bool) -> None:
        import subprocess
        dev = self.drive.currentText()
        if not dev.startswith("/dev"):
            QMessageBox.information(self, "Mount", "No optical drive selected.")
            return
        mp = str(Path.home() / "disc")
        tries = ([["udisksctl", "mount", "-b", dev], ["mount", mp]] if mount
                 else [["udisksctl", "unmount", "-b", dev], ["umount", mp]])
        last = ""
        for cmd in tries:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            except Exception as e:  # noqa: BLE001
                last = str(e)
                continue
            out = (r.stdout + r.stderr).strip()
            if r.returncode == 0:
                self.win.statusBar().showMessage(out.splitlines()[0] if out else "Done", 6000)
                if mount:
                    import re as _re
                    m = _re.search(r"at (/\S+)", out)
                    subprocess.Popen(["xdg-open", m.group(1) if m else mp])
                return
            last = out
        hint = ""
        if mount:
            hint = ("\n\nIf this disc has a slow-to-read picture area the desktop gives up on it. One-time fix:\n"
                    "  sudo " + str(Path(__file__).resolve().parents[1] / "setup-disc-mount.sh"))
        QMessageBox.warning(self, "Mount" if mount else "Unmount", (last or "Failed") + hint)

    def mount_disc(self) -> None:
        self._run_mount(True)

    def unmount_disc(self) -> None:
        self._run_mount(False)

    def load_image(self) -> None:
        start = str(Path(self.win.p.image_path).parent) if self.win.p.image_path else self.win.p.output_dir
        f, _ = QFileDialog.getOpenFileName(self, "Load an existing disc image", start,
                                           "Disc images (*.iso *.wav *.raw);;All files (*)")
        if not f:
            return
        p = self.win.p
        p.image_path = f
        try:                                   # a sidecar from this tool tells us which disc it was made for
            side = json.loads(Path(f + ".json").read_text())
            total = side.get("totalSectors") or side.get("sectors")
            if total:
                match = [(k, pr) for k in ("dvd", "bd") for pr in self.win.presets[k]
                         if pr.get("totalSectors") == total
                         and abs(pr["innerRadiusMm"] - side.get("imageMapping", {}).get("innerRadiusMm", pr["innerRadiusMm"])) < 1e-6]
                if match:
                    self.win.apply_kind(match[0][0], match[0][1]["id"])
                    self.win.statusBar().showMessage(f"Preset set to {match[0][1]['id']} from the image's sidecar", 6000)
        except Exception:  # noqa: BLE001
            pass
        self.win.refresh_all()
        self.check_disc()

    def use_exported(self) -> None:
        self.win.p.image_path = ""
        self.win.refresh_all()
        self.check_disc()

    def on_show(self) -> None:
        self.scan()
        if self.drive.currentText().startswith("/dev") and not self.runner.running:
            QTimer.singleShot(200, self.check_disc)

    def check_disc(self) -> None:
        dev = self.drive.currentText()
        if self.runner.running or not dev.startswith("/dev") or getattr(self, "_detect", None) is not None:
            return
        self.disc_info.setText("Reading disc… (a slow drive can take up to 40 seconds)")
        self.use_preset.hide()
        self._detect = DetectThread(dev)
        self._detect.done.connect(self._detect_done)
        self._detect.start()

    def _detect_done(self, d: dict) -> None:
        self._detect = None
        self.detected = d
        self.use_preset.hide()
        if "error" in d:
            self.disc_info.setText(d["error"])
            return
        try:
            self._show_disc(d)
        except Exception as e:  # noqa: BLE001
            self.disc_info.setText(f"Disc read, but the summary failed: {e}")

    def _show_disc(self, d: dict) -> None:
        dev = self.drive.currentText()
        p = self.win.p
        bits = [f"<b>{d['media']}</b>", f"ID {d['media_id'] or '?'}", d["status"] or "?"]
        if d["free_bytes"]:
            bits.append(f"{human_size(d['free_bytes'])} free")
        if d["max_speed"]:
            bits.append(f"up to {d['max_speed']}")
        warn = ""
        if d["kind"] and d["kind"] != p.kind:
            warn = f"<br><span style='color:#ffb454'>The project is a {KIND_NAMES[p.kind]} but this is a {KIND_NAMES[d['kind']]} disc.</span>"
        elif d["status"] not in ("blank", ""):
            warn = ("<br><span style='color:#ffb454'>Not blank. "
                    + (("DVD+RW is overwritten directly; if the burn refuses, run: dvd+rw-format -force " + dev
                        if "+RW" in d["media"] else "Wipe first: dvd+rw-format -blank=full " + dev)
                       if d["rewritable"] else "Write-once disc, cannot be reused.")
                    + "</span>")
        img = burn_image(p)
        try:
            side = json.loads(Path(str(img) + ".json").read_text())
            if side.get("totalSectors") and p.kind != "cd" and side["totalSectors"] != p.geo.sectors:
                warn += (f"<br><span style='color:#ff6b6b'>This image was generated for a {side['totalSectors']:,}-sector disc, "
                         f"but the project preset has {p.geo.sectors:,}. Generate it again on Export.</span>")
        except Exception:  # noqa: BLE001
            pass
        cap = d.get("capacity_bytes", 0)
        if img.exists() and cap and p.kind == d.get("kind") and img.stat().st_size > cap:
            warn += (f"<br><span style='color:#ff6b6b'>The image ({img.stat().st_size // 2048:,} sectors) is larger than this disc "
                     f"({cap // 2048:,}). Generate it again on Export with this disc's preset.</span>")
        if d["preset"] and d["preset"] != p.preset_id:
            warn += "<br><span style='color:#8fb0ff'>A measured preset exists for this disc.</span>"
            self.use_preset.show()
        elif d["preset"]:
            warn += "<br><span style='color:#7bd88f'>Project preset matches this disc.</span>"
        elif d["media_id"]:
            warn += "<br><span style='color:#8d94a6'>No measured preset for this disc; the standard one is approximate.</span>"
        self.disc_info.setText("  ·  ".join(bits) + warn)

    def apply_detected(self) -> None:
        d = self.detected
        if d.get("preset") and d.get("kind"):
            self.win.apply_kind(d["kind"], d["preset"])
            self.win.refresh_all()
            self.check_disc()

    def scan(self) -> None:
        cur = self.drive.currentText()
        self.drive.blockSignals(True)
        self.drive.clear()
        for d in list_drives():
            self.drive.addItem(d)
        if cur:
            self.drive.setCurrentText(cur)
        self.drive.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        p = self.win.p
        out = burn_image(p)
        self.image.setText(f"{out}  ({human_size(out.stat().st_size)})" if out.exists() else f"{out}  (not exported yet)")
        t = burn_tools()
        names = {"cdrecord": "cdrecord", "growisofs": "growisofs", "xorriso": "xorriso"}
        self.tools.setText("  ".join(f"{n}: {'✓' if t[n] else '✗'}" for n in names)
                           + ("" if (t["cdrecord"] and t["growisofs"]) else
                              "    Install: sudo pacman -S cdrtools dvd+rw-tools"))
        if not list_drives():
            self.drive.addItem("(no optical drive found)")
        self.update_cmd()
        if not self.runner.running:
            self.disc.set_project(self.win.p)

    def update_cmd(self) -> None:
        p = self.win.p
        dev = self.drive.currentText()
        sp = self.speed.currentText()
        c = burn_command(p, burn_image(p), dev, None if sp == "Automatic" else int(sp)) if dev.startswith("/dev") else None
        self.cmd.setText(" ".join(shlex.quote(a) for a in c) if c else "—")
        self.go.setEnabled(bool(c) and burn_image(p).exists())

    def burn(self) -> None:
        p = self.win.p
        dev = self.drive.currentText()
        sp = self.speed.currentText()
        c = burn_command(p, burn_image(p), dev, None if sp == "Automatic" else int(sp))
        if not c:
            return
        if QMessageBox.warning(self, "Burn disc", f"Write to {dev}?\n\nThe disc must be blank. This cannot be undone.",
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                               QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.log.clear()
        self.disc.set_project(p)
        self.log.appendPlainText("$ " + " ".join(shlex.quote(a) for a in c))
        self.go.setEnabled(False)
        self.runner.start(c[0], c[1:])

    def on_line(self, line: str) -> None:
        m = re.search(r"\(\s*([\d.]+)%\)\s*@([\d.]+x)(?:,\s*remaining\s*([\d:]+))?", line)
        if m:
            pct = float(m.group(1))
            self.bar.setValue(int(pct * 10))
            self.disc.set_fraction(pct / 100)
            self.disc.set_spin(spin_rpm(self.win.p, float(m.group(2)[:-1]), pct / 100))
            self.bar.setFormat(f"{pct:.1f}%  @{m.group(2)}" + (f"  ·  {m.group(3)} left" if m.group(3) else ""))
            return                      # keep the log readable: progress lines go to the bar only
        self.log.appendPlainText(line)

    def on_done(self, code: int) -> None:
        self.log.appendPlainText("\nFinished." if code == 0 else f"\nFailed (exit {code}).")
        self.bar.setFormat("Done" if code == 0 else "Failed")
        self.disc.set_spin(0)
        if code == 0:
            self.bar.setValue(1000)
            self.disc.set_fraction(1.0)
        self.update_cmd()


def link_network_shares() -> None:
    """~/SMB-Shares -> the live kio-fuse smb mount (its folder name changes every login)."""
    import glob
    uid = os.getuid()
    found = sorted(glob.glob(f"/run/user/{uid}/kio-fuse-*/smb"))
    link = Path.home() / "SMB-Shares"
    try:
        if found:
            if link.is_symlink() or link.exists():
                if link.is_symlink():
                    link.unlink()
                else:
                    return
            link.symlink_to(found[0])
    except OSError:
        pass


def main() -> int:
    link_network_shares()
    os.environ.setdefault("QT_QPA_PLATFORMTHEME", "kde")   # native KDE file dialogs: browse smb:// shares
    app = QApplication(sys.argv)
    app.setApplicationName("Disc Image Studio")
    app.setDesktopFileName("disc-image-studio")          # matches the .desktop entry so the taskbar shows the icon
    app.setWindowIcon(QIcon(logo_pixmap()))
    app.setStyleSheet(theme.stylesheet())
    w = Studio()
    watch_palette(app, w)
    if len(sys.argv) > 1 and sys.argv[-1].endswith(".discproj"):
        w.load_project(sys.argv[-1])
    w.show()
    return app.exec()


def watch_palette(app: QApplication, win: "Studio") -> None:
    """Re-skins the app whenever the Material You scheme changes (new wallpaper, light/dark switch).

    KDE replaces kdeglobals with a new file on every change, which makes a plain file watcher lose it, so the
    file's identity (inode, size, mtime) is polled once a second instead. It costs next to nothing.
    """
    def signature():
        try:
            st = theme.KDEGLOBALS.stat()
            return (st.st_ino, st.st_size, st.st_mtime_ns)
        except OSError:
            return None

    state = {"sig": signature(), "pal": theme.P}
    timer = QTimer(app)
    timer.setInterval(1000)

    def check() -> None:
        sig = signature()
        if sig is None or sig == state["sig"]:
            return
        state["sig"] = sig
        new = theme.load_palette()
        if new == state["pal"]:                      # file touched but the colours are the same
            return
        state["pal"] = new
        theme.P = new
        app.setStyleSheet(theme.stylesheet())
        win.refresh_all()
        for wid in app.allWidgets():                 # custom-painted widgets read the palette in paintEvent
            wid.update()

    timer.timeout.connect(check)
    timer.start()
    app._palette_timer = timer                       # keep alive
