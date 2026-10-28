"""
The GUI's field view: the dumps of a run (time-domain frames, frequency-domain fields), cut at any x / y / z
mesh line, played over time or phase, followed live while openEMS writes them, saved as PNG / GIF / MP4.
Reading and drawing for files live in ..fields (no Qt).
"""
import os
import numpy as np
from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QComboBox, QPushButton, QLabel, QCheckBox,
                               QSlider, QSpinBox, QFileDialog, QMessageBox, QProgressDialog, QApplication)
import pyqtgraph as pg
from .panels import FlowLayout
from kicad2ems.api.frontend import frames as F

COMPONENTS = [('|F|', 'mag'), ('x', 'x'), ('y', 'y'), ('z', 'z')]


def _slider():
    s = QSlider(Qt.Horizontal)
    s.setMinimum(0)
    s.setMaximum(0)
    return s


class FieldsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.out, self.srcs, self.src, self.pl, self.lim = win, None, [], None, None, None
        self.user_lim = False                                       # the colour bar was dragged: keep it
        lay = QVBoxLayout(self)

        row = FlowLayout()
        row.addWidget(QLabel('Dump'))
        self.dump = QComboBox()
        self.dump.setMinimumWidth(200)
        self.dump.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.dump.setMinimumContentsLength(28)
        self.dump.currentIndexChanged.connect(self._pick)
        row.addWidget(self.dump, 1)
        b = QPushButton('Refresh')
        b.clicked.connect(lambda: self.load(self.out))
        row.addWidget(b)
        b = QPushButton('Open results folder…')
        b.clicked.connect(self._open)
        row.addWidget(b)
        self.live = QCheckBox('Live (follow the newest frame)')
        self.live.setChecked(True)
        self.live.setToolTip('While a run is going, show each time-domain frame as openEMS writes it')
        row.addWidget(self.live)
        lay.addLayout(row)

        row = FlowLayout()
        row.addWidget(QLabel('Component'))
        self.comp = QComboBox()
        self.comp.addItems([c for c, _ in COMPONENTS])
        self.comp.currentIndexChanged.connect(self._new_range)
        row.addWidget(self.comp)
        row.addWidget(QLabel('Cut normal to'))
        self.axis = QComboBox()
        self.axis.addItems(['x', 'y', 'z'])
        self.axis.setToolTip('Plane dumps have one choice; volume dumps can be cut at any x, y or z mesh line')
        self.axis.currentIndexChanged.connect(self._axis_changed)
        row.addWidget(self.axis)
        self.slice = _slider()
        self.slice.setMinimumWidth(160)
        self.slice.valueChanged.connect(self._new_range)
        row.addWidget(self.slice, 1)
        self.slice_lab = QLabel('')
        self.slice_lab.setMinimumWidth(110)
        row.addWidget(self.slice_lab)
        self.log = QCheckBox('log scale')
        self.log.setChecked(True)
        self.log.toggled.connect(self._new_range)
        row.addWidget(self.log)
        self.auto = QCheckBox('auto range per frame')
        self.auto.setToolTip('Off: keep the colour range (drag the colour bar to set it)')
        self.auto.toggled.connect(self._new_range)
        row.addWidget(self.auto)
        lay.addLayout(row)

        self.view = pg.PlotWidget()
        self.view.setBackground('w')
        self.img = pg.ImageItem()
        self.view.addItem(self.img)
        self.lines = pg.PlotDataItem([], [], pen=pg.mkPen('#7fd1ff', width=1), connect='finite')
        self.view.addItem(self.lines)
        self.cbar = pg.ColorBarItem(values=(0, 1), colorMap=pg.colormap.getFromMatplotlib('inferno'), interactive=True)
        self.cbar.setImageItem(self.img, insert_in=self.view.getPlotItem())
        self.cbar.axis.enableAutoSIPrefix(False)
        self.cbar.sigLevelsChangeFinished.connect(self._levels_dragged)
        self.view.scene().sigMouseMoved.connect(self._hover)
        lay.addWidget(self.view, 1)

        row = FlowLayout()
        self.play_btn = QPushButton('▶ Play')
        self.play_btn.setCheckable(True)
        self.play_btn.toggled.connect(self._play)
        row.addWidget(self.play_btn)
        row.addWidget(QLabel('frame'))
        self.frame = _slider()
        self.frame.setMinimumWidth(160)
        self.frame.valueChanged.connect(self.draw)
        row.addWidget(self.frame, 2)
        self.phase_on = QCheckBox('instantaneous, phase')
        self.phase_on.setToolTip('Frequency domain: Re(F·e^jφ) at the phase below; off: the peak |F|')
        self.phase_on.toggled.connect(self._new_range)
        row.addWidget(self.phase_on)
        self.phase = _slider()
        self.phase.setMaximum(359)
        self.phase.setMinimumWidth(120)
        self.phase.valueChanged.connect(self.draw)
        row.addWidget(self.phase, 1)
        self.frame_lab = QLabel('')
        self.frame_lab.setMinimumWidth(240)
        row.addWidget(self.frame_lab)
        lay.addLayout(row)

        row = FlowLayout()
        self.readout = QLabel('')
        self.readout.setMinimumWidth(220)
        row.addWidget(self.readout, 1)
        row.addWidget(QLabel('fps'))
        self.fps = QSpinBox()
        self.fps.setRange(1, 60)
        self.fps.setValue(12)
        row.addWidget(self.fps)
        row.addWidget(QLabel('every n-th frame'))
        self.every = QSpinBox()
        self.every.setRange(1, 1000)
        self.every.setToolTip('Time domain: frames used for Play and saved animations')
        row.addWidget(self.every)
        for text, ext in (('Save PNG…', 'png'), ('Save GIF…', 'gif'), ('Save MP4…', 'mp4')):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, e=ext: self.save(e))
            row.addWidget(b)
        lay.addLayout(row)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._set_controls()

    # ---- sources ----
    def _open(self):
        d = QFileDialog.getExistingDirectory(self, 'A results folder (the run\'s output folder)', self.out or os.getcwd())
        if d:
            self.load(d)

    def load(self, out_dir):
        """List the dumps of a results folder (keeps the selection when it is still there)."""
        if not out_dir:
            return
        self.out = out_dir
        keep = self.src.label if self.src else None
        self.srcs = F.find_dumps(out_dir)
        self.dump.blockSignals(True)
        self.dump.clear()
        self.dump.addItems([s.label for s in self.srcs] or ['(no field dumps in this folder: add some in Setup)'])
        labels = [s.label for s in self.srcs]
        self.dump.setCurrentIndex(labels.index(keep) if keep in labels else 0)
        self.dump.blockSignals(False)
        self._pick()

    def _pick(self, *_):
        i = self.dump.currentIndex()
        self.src = self.srcs[i] if 0 <= i < len(self.srcs) else None
        self.lim = None
        self._set_controls()
        if self.src and len(self.src):
            shape = self.src.shape()
            self.axis.blockSignals(True)
            self.axis.setCurrentIndex(F.default_axis(shape))
            self.axis.blockSignals(False)
            self._axis_changed()
        else:
            self.img.clear()
            self.lines.setData([], [])
            self.frame_lab.setText('no frames yet' if self.src else '')

    def _set_controls(self):
        src = self.src
        n = len(src) if src else 0
        self.frame.blockSignals(True)
        self.frame.setMaximum(max(0, n - 1))
        self.frame.blockSignals(False)
        fd = bool(src) and src.domain == 'FD'
        self.phase_on.setEnabled(fd)
        self.phase.setEnabled(fd)
        self.every.setEnabled(not fd)
        if fd and n:
            self.every.setValue(1)
        elif src and n > 200 and self.every.value() == 1:
            self.every.setValue(max(1, n // 120))

    def _axis_changed(self, *_):
        if not (self.src and len(self.src)):
            return
        shape = self.src.shape()
        ax = self.axis.currentIndex()
        self.slice.blockSignals(True)
        self.slice.setMaximum(max(0, shape[ax] - 1))
        self.slice.setValue(shape[ax] // 2 if shape[ax] > 1 else 0)
        self.slice.setEnabled(shape[ax] > 1)
        self.slice.blockSignals(False)
        self._new_range()

    # ---- drawing ----
    def _component(self):
        return COMPONENTS[self.comp.currentIndex()][1]

    def _phase(self):
        return np.radians(self.phase.value()) if self.src.domain == 'FD' and self.phase_on.isChecked() else None

    def _new_range(self, *_):
        self.lim, self.user_lim = None, False
        self.draw()

    def _levels_dragged(self, *_):
        if self.pl is None:
            return
        lo, hi = self.cbar.levels()
        self.auto.blockSignals(True)
        self.auto.setChecked(False)
        self.auto.blockSignals(False)
        self.lim, self.user_lim = ((10 ** lo, 10 ** hi) if self._use_log() else (lo, hi)), True

    def _use_log(self):
        return self.log.isChecked() and self.pl is not None and not self.pl.signed

    def draw(self, *_):
        src = self.src
        if not (src and len(src)):
            return
        i = min(self.frame.value(), len(src) - 1)
        try:
            mesh, data = src.load(i)
        except Exception as e:                                      # a frame still being written
            self.frame_lab.setText(f"frame {i}: {e.__class__.__name__}")
            return
        ax = self.axis.currentIndex()
        pl = self.pl = F.plane(mesh, data, ax, self.slice.value(), self._component(), self._phase())
        pos = pl.pos if ax != 1 else -pl.pos
        self.slice_lab.setText(f"{'xyz'[ax]} = {pos:.3f} mm")
        if self.auto.isChecked():
            self.lim = F.levels([pl.img], pl.signed, self.log.isChecked())
        elif self.lim is None:
            self.lim = F.levels(self._sample(ax), pl.signed, self.log.isChecked())
        lo, hi = self.lim
        img, (u0, v0, du, dv) = pl.resample()
        use_log = self._use_log()
        if use_log:
            lo = max(lo, hi * 1e-12) if hi > 0 else 1e-30
            img, lo, hi = np.log10(np.maximum(img, lo)), np.log10(lo), np.log10(max(hi, lo * 10))
        cmap = pg.colormap.getFromMatplotlib('RdBu_r' if pl.signed else 'inferno')
        self.cbar.setColorMap(cmap)
        self.img.setImage(img, autoLevels=False)
        self.img.setRect(QRectF(u0 - du / 2, v0 - dv / 2, du * img.shape[0], dv * img.shape[1]))
        self.cbar.blockSignals(True)
        self.cbar.setLevels((lo, hi))
        self.cbar.blockSignals(False)
        what = f"|{src.field}|" if self._component() == 'mag' else f"{src.field}_{self._component()}"
        scaled = src.domain == 'FD' and src.scale(i)
        self.cbar.axis.setLabel(('log10 ' if use_log else '') + f"{what} ({src.unit}" +
                                (', 1 V incident' if scaled else '') + ')')
        segs = F.outlines(src.geometry, ax, pl.pos)
        if segs:
            xs = np.concatenate([np.append(u, np.nan) for u, _ in segs])
            ys = np.concatenate([np.append(v, np.nan) for _, v in segs])
            self.lines.setData(xs, ys)
            self.lines.setPen(pg.mkPen('#7fd1ff' if not pl.signed else '#222222', width=1 if ax == 2 else 3))
        else:
            self.lines.setData([], [])
        p = self.view.getPlotItem()
        p.invertY(ax == 2)
        p.setAspectLocked(ax == 2)
        p.setLabel('bottom', f"{pl.names[0]} (mm)")
        p.setLabel('left', f"{pl.names[1]} (mm)")
        self.frame_lab.setText(f"{i + 1}/{len(src)}: {src.frame_label(i, self._phase())}")

    def _sample(self, ax):
        """Images for one colour range over the series: time domain, up to 12 frames across it; frequency
        domain with a phase, half a period."""
        src, idx, comp = self.src, self.slice.value(), self._component()
        if src.domain == 'FD':
            mesh, data = src.load(self.frame.value())
            phases = np.linspace(0, np.pi, 6, endpoint=False) if self._phase() is not None else [None]
            return [F.plane(mesh, data, ax, idx, comp, p).img for p in phases]
        out = []
        for i in sorted(set(np.linspace(0, len(src) - 1, min(12, len(src))).astype(int))):
            try:
                out.append(F.plane(*src.load(i), ax, idx, comp).img)
            except Exception:                                       # a frame being written
                pass
        return out

    def _hover(self, pos):
        pl = self.pl
        if pl is None or not self.view.sceneBoundingRect().contains(pos):
            return
        q = self.view.getPlotItem().vb.mapSceneToView(pos)
        iu, iv = np.argmin(np.abs(pl.u - q.x())), np.argmin(np.abs(pl.v - q.y()))
        if pl.u[0] - 1 <= q.x() <= pl.u[-1] + 1 and pl.v[0] - 1 <= q.y() <= pl.v[-1] + 1:
            self.readout.setText(f"{pl.names[0]} = {pl.u[iu]:.3f}, {pl.names[1]} = {pl.v[iv]:.3f} mm: "
                                 f"{pl.img[iu, iv]:.4g} {self.src.unit}")

    # ---- playing and following a run ----
    def _play(self, on):
        self.play_btn.setText('■ Stop' if on else '▶ Play')
        if on:
            if self.src and self.src.domain == 'FD':
                self.phase_on.setChecked(True)
            self.timer.start(int(1000 / self.fps.value()))
        else:
            self.timer.stop()

    def _tick(self):
        src = self.src
        if not (src and len(src)):
            return
        self.timer.setInterval(int(1000 / self.fps.value()))
        if src.domain == 'FD':
            self.phase.setValue((self.phase.value() + 15) % 360)
        else:
            self.frame.setValue((self.frame.value() + self.every.value()) % len(src))

    def follow(self, out_dir):
        """Called while a run is going: new dumps and frames; with Live, show the newest frame."""
        if out_dir != self.out or len(F.find_dumps(out_dir)) != len(self.srcs):
            self.load(out_dir)
        if not self.src:
            return
        n_old = len(self.src)
        self.src.refresh()
        if not n_old and len(self.src):
            self._pick()
        self._set_controls()
        if self.live.isChecked() and not self.play_btn.isChecked() and self.src.domain == 'TD':
            k = self.src.newest_complete()
            if k is not None and k != self.frame.value():
                if not self.user_lim:
                    self.lim = None                                 # the range grows with the run
                self.frame.setValue(k)

    # ---- saving ----
    def _frames(self):
        n = len(self.src)
        return list(range(0, n, self.every.value())) if self.src.domain == 'TD' else [self.frame.value()]

    def save(self, ext):
        src = self.src
        if not (src and len(src) and self.pl is not None):
            QMessageBox.information(self, 'Fields', 'No field frame to save')
            return
        base = os.path.join(self.out or os.getcwd(), f"{src.run}_{src.name}.{ext}")
        path, _ = QFileDialog.getSaveFileName(self, f"Save {ext.upper()}", base, f"{ext.upper()} (*.{ext})")
        if not path:
            return
        if not path.lower().endswith('.' + ext):
            path += '.' + ext
        ax, comp, use_log = self.axis.currentIndex(), self._component(), self._use_log()
        lim = None if self.auto.isChecked() else self.lim
        try:
            if ext == 'png':
                from PIL import Image
                lo, hi = self.lim
                i = self.frame.value()
                what = f"|{src.field}|" if comp == 'mag' else f"{src.field}_{comp}"
                Image.fromarray(F.render(self.pl, lo, hi, use_log,
                                         f"{what}, {self.slice_lab.text()}, {src.frame_label(i, self._phase())} "
                                         f"({src.run} driven)", src.geometry, f"{what} ({src.unit})")).save(path)
            else:
                frames = self._frames()
                n = len(frames) if src.domain == 'TD' else 24
                dlg = QProgressDialog(f"Writing {os.path.basename(path)}…", None, 0, n, self)
                dlg.setWindowModality(Qt.WindowModal)
                dlg.show()

                def progress(k, n_):
                    dlg.setValue(k)
                    QApplication.processEvents()
                F.save_animation(src, path, ax, self.slice.value(), comp, frames, fps=self.fps.value(),
                                 log=self.log.isChecked(), lim=lim, progress=progress)
                dlg.close()
        except Exception as e:
            QMessageBox.warning(self, 'Save', str(e))
            return
        self.readout.setText(f"saved {path}")
