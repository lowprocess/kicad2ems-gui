"""
The Results page's Beam steering bar, for an antenna result with each port's far field kept (mom25d's
<name>_mom25d_array.npz, phased.py): the drive (PORT[=amplitude][@phase] per port, the run's to start with) and
phase steps on top of it, with an amplitude taper (Taylor, Chebyshev, cosine) for lower sidelobes, recombined
at once, without solving again. Without a grid the step goes from each
driven port to the next (a line of elements); with one (COLSxROWS, or PORT:COL,ROW per port: a 2D array such as
a 4 x 4 patch array with a feed line per patch) there are two, X per column and Y per row, and a phase map shows
each element's phase and active reflection. Aim (results that kept the ports' places) points the beam at an angle
instead, each port's phase from its place at the pattern frequency (phased.aim), on top of the drive and the steps.
The plots (gain over frequency, the far-field cuts) and the 3D view's pattern follow; Animate sweeps X, Y, or both
round a circle (a conical scan), or with Aim the angle: theta back and forth, or phi round.

    bar = SteeringBar()              # compact=True: stacked, for the 3D view's side panel
    bar.set_data(res, data)          # the antenna result (JSON dict) and phased.load's data, or None: hidden
    bar.steered.connect(lambda res, sphere: ...)
    other.mirror(bar)                # another bar showing the same drive, grid and steps (Results page's, 3D view's)
"""
import math
import numpy as np
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)
from kicad2ems.api.frontend import phased

STEP_MAX = 180          # deg: the phase steps' range, either way
ANIM_MS = 60            # a frame of Animate
ANIM_DEG = 3            # a step's change per frame (Circle: the scan angle's)
CIRCLE_R = 90           # deg: Circle's radius when both steps are about zero
ANIM_MODES = ('X', 'Y', 'Circle')
AIM_MODES = ('θ', 'φ')  # Animate with Aim: theta back and forth over 0..AIM_THETA_MAX, or phi round at the theta set
AIM_THETA_MAX = 60


class PhaseMap(QWidget):
    """The 2D array's elements as a grid (column right, row down: row 0 the top row), each coloured by its
    phase (the hue; grey: not driven) with its port, phase and active reflection."""
    CELL = 62           # px: a cell's width at most
    ASPECT = 0.86       # a cell's height / width
    MIN_TEXT = 34       # px: narrower cells show the colour alone

    def __init__(self):
        super().__init__()
        self.cells = []                                 # (col, row, name, phase deg or None, dB, amplitude)
        self.tapered = False                            # some amplitude below the largest: a line for it
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setToolTip("each element of the array: its port, phase (the colour), amplitude (×, when tapered; "
                        "fainter for weaker) and active reflection (with its neighbours driven too)")

    def set(self, names, grid, a, active):
        self.cells = []
        for n, v, act in zip(names, a, active):
            if n in (grid or {}):
                c, r = grid[n]
                ph = math.degrees(math.atan2(v.imag, v.real)) if abs(v) > 0 else None
                db = 20 * math.log10(max(abs(act), 1e-15)) if np.isfinite(act) else None
                self.cells.append((c, r, n, ph, db, abs(v)))
        top = max((cell[5] for cell in self.cells), default=0) or 1.0
        self.cells = [(*cell[:5], cell[5] / top) for cell in self.cells]     # amplitude relative to the largest
        self.tapered = any(ph is not None and amp < 0.999 for _, _, _, ph, _, amp in self.cells)
        self._fit()
        self.update()

    def _fit(self, width=None):
        width = width or (self.width() if self.isVisible() and self.width() > 1 else self.sizeHint().width())
        self.setFixedHeight(self.heightForWidth(width))

    def _dims(self):
        cols = 1 + max(c for c, *_ in self.cells)
        rows = 1 + max(r for _, r, *_ in self.cells)                 # cells at (column, row) x the cell size
        w = min(self.CELL, max(8.0, (self.width() - 2) / cols))
        return cols, rows, w, w * self._aspect()

    def _aspect(self):
        return self.ASPECT * (4.5 / 3.5 if self.tapered else 1.0)          # four lines of text, not three

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        if not self.cells:
            return 0
        cols = 1 + max(c for c, *_ in self.cells)
        rows = 1 + max(r for _, r, *_ in self.cells)
        return int(math.ceil(rows * min(self.CELL, max(8.0, (width - 2) / cols)) * self._aspect())) + 2

    def sizeHint(self):
        if not self.cells:
            return QSize(0, 0)
        cols = 1 + max(c for c, *_ in self.cells)
        return QSize(int(cols * self.CELL) + 2, self.heightForWidth(int(cols * self.CELL) + 2))

    def resizeEvent(self, ev):
        self._fit(ev.size().width())
        super().resizeEvent(ev)

    def paintEvent(self, _):
        if not self.cells:
            return
        _, _, w, h = self._dims()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = p.font()
        f.setPointSizeF(max(6.0, min(f.pointSizeF(), h / (6.5 if self.tapered else 5))))
        p.setFont(f)
        for c, r, name, ph, db, amp in self.cells:
            rect = QRectF(1 + c * w, 1 + r * h, w - 2, h - 2)
            fill = (QColor(150, 150, 150, 90) if ph is None else
                    QColor.fromHsvF((ph % 360) / 360, 0.15 + 0.45 * amp, 0.95))      # weaker: paler
            p.setBrush(fill)
            p.setPen(QPen(self.palette().mid().color(), 1))
            p.drawRoundedRect(rect, 3, 3)
            if w >= self.MIN_TEXT:
                p.setPen(Qt.black if ph is not None else self.palette().text().color())
                deg = None if ph is None else int(round(ph)) or 0          # no "-0"
                lines = [name, '-' if ph is None else f"{180 if deg == -180 else deg}°"]
                if self.tapered and ph is not None:
                    lines.append(f"×{amp:.2f}")
                if db is not None:
                    lines.append(f"{db:.1f} dB" if db > -60 else "< −60 dB")
                p.drawText(rect, Qt.AlignCenter, '\n'.join(lines))
        p.end()


class SteeringBar(QGroupBox):
    steered = Signal(object, object)                                # (antenna result, sphere) of the drive

    def __init__(self, compact=False):
        super().__init__('Beam steering')
        self.setToolTip("Each port's far field was kept: any drive is their sum (exact, with the coupling between "
                        "the elements), recombined without solving again")
        self.res, self.data, self._dir, self._t, self._r = None, None, 1, 0.0, CIRCLE_R
        self._grid = None
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel('Drive'))
        self.drive = QLineEdit()
        self.drive.setToolTip("PORT[=amplitude][@phase in degrees] per driven port, comma-separated (incident "
                              "waves; the ports not named are terminated), e.g. P1@0, P2=0.5@90")
        self.drive.editingFinished.connect(self.update)
        row.addWidget(self.drive, 2)
        if compact:                                                 # a narrow side panel: a row each
            lay.addLayout(row)
            row = QHBoxLayout()
        row.addWidget(QLabel('Grid'))
        self.grid = QLineEdit()
        self.grid.setPlaceholderText('a line of ports')
        self.grid.setToolTip("the ports' places in a 2D array, for an X step per column and a Y step per row: "
                             "COLSxROWS (the ports in order fill the rows, top row first: 4x4 for P1..P16), or "
                             "PORT:COL,ROW per port separated by spaces (e.g. P1:0,0 P2:1,0 P3:0,1 P4:1,1; "
                             "fractional places for an offset lattice). Empty: one step from each driven port to "
                             "the next")
        self.grid.editingFinished.connect(self.update)
        row.addWidget(self.grid, 1)
        lay.addLayout(row)

        def step_row(label, tip):
            r = QHBoxLayout()
            lab = QLabel(label)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(-STEP_MAX, STEP_MAX)
            slider.setToolTip(tip)
            spin = QSpinBox()
            spin.setRange(-STEP_MAX, STEP_MAX)
            spin.setSuffix('°')
            spin.setToolTip(tip)
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            spin.valueChanged.connect(lambda *_: self.update())
            r.addWidget(lab)
            if compact:                                             # the slider on a row of its own
                r.addStretch(1)
                r.addWidget(spin)
                lay.addLayout(r)
                r = QHBoxLayout()
                r.addWidget(slider)
            else:
                r.addWidget(slider, 3)
                r.addWidget(spin)
            lay.addLayout(r)
            return lab, slider, spin, r

        self.label_x, self.slider, self.spin, _ = step_row(
            'Phase step', "added on top of the drive's phases: from each driven port to the next (in port order), "
                          "or with a grid per column: the beam tilts across the ports")
        self.label_y, self.slider_y, self.spin_y, _ = step_row(
            'Y step', "with a grid: added per row (row 0 the top one): the beam tilts across the rows")
        self.aim_row = QWidget()
        row = QHBoxLayout(self.aim_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.aim = QCheckBox('Aim at')
        self.aim.setToolTip("point the beam at θ, φ: each driven port's phase from its place, −k0 (x sin θ cos φ + "
                            "y sin θ sin φ) at the pattern frequency, on top of the drive and the steps (any layout "
                            "of feeds). A feed well off its element's centre still needs the drive's own phases")
        self.aim.toggled.connect(lambda *_: self._aim_changed())
        row.addWidget(self.aim)
        self.theta, self.phi = QDoubleSpinBox(), QDoubleSpinBox()
        for w, lab, lo, hi in ((self.theta, 'θ', 0, 90), (self.phi, 'φ', -180, 360)):
            w.setRange(lo, hi)
            w.setDecimals(0)
            w.setPrefix(f"{lab} ")
            w.setSuffix('°')
            w.valueChanged.connect(lambda *_: self.update())
            row.addWidget(w)
        self.phi.setWrapping(True)
        row.addStretch(1)
        lay.addWidget(self.aim_row)
        row = QHBoxLayout()
        row.addWidget(QLabel('Taper'))
        self.taper = QComboBox()
        self.taper.addItems([t.capitalize() for t in phased.TAPERS])
        self.taper.setToolTip("an amplitude taper multiplied into the drive, for lower sidelobes at the cost of a "
                              "wider beam and some gain: Taylor (nearly equal sidelobes at the level set), "
                              "Chebyshev (all sidelobes at the level), cosine. With a grid: per column times per "
                              "row; without: across the driven ports")
        self.taper.currentIndexChanged.connect(lambda *_: self._taper_changed())
        row.addWidget(self.taper)
        self.sll = QDoubleSpinBox()
        self.sll.setRange(13.5, 80)
        self.sll.setDecimals(0)
        self.sll.setValue(phased.TAPER_SLL)
        self.sll.setPrefix('−')
        self.sll.setSuffix(' dB')
        self.sll.setToolTip("Taylor's and Chebyshev's sidelobe level, below the main beam")
        self.sll.valueChanged.connect(lambda *_: self.update())
        row.addWidget(self.sll)
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.anim = QPushButton('Animate')
        self.anim.setCheckable(True)
        self.anim.setToolTip(f"sweep the phase step back and forth over ±{STEP_MAX}° (with a grid: X, Y, or both "
                             f"round a circle, a conical scan)")
        self.anim.toggled.connect(self._animate)
        row.addWidget(self.anim)
        self.anim_mode = QComboBox()
        self.anim_mode.addItems(ANIM_MODES)
        self.anim_mode.setToolTip("what Animate sweeps: the X step, the Y step, or both round a circle (the "
                                  f"steps' size at the start, {CIRCLE_R}° when about zero); with Aim, θ back and "
                                  f"forth over 0..{AIM_THETA_MAX}° or φ round")
        self.anim_mode.currentIndexChanged.connect(lambda *_: self._restart_circle())
        row.addWidget(self.anim_mode)
        self.reset = QPushButton('Reset')
        self.reset.setToolTip("the run's drive, grid, taper, phase steps and aim")
        self.reset.clicked.connect(self._reset)
        row.addWidget(self.reset)
        row.addStretch(1)
        lay.addLayout(row)
        self.map = PhaseMap()
        lay.addWidget(self.map)
        self.readout = QLabel()
        self.readout.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.readout.setWordWrap(True)
        lay.addWidget(self.readout)
        self.timer = QTimer(self)
        self.timer.setInterval(ANIM_MS)
        self.timer.timeout.connect(self._frame)
        self._show_2d(False)
        self._taper_changed(update=False)
        self.aim_row.hide()
        self.hide()

    # ---- state -----------------------------------------------------------------------------------------
    def set_data(self, res, data):
        """An antenna result and its per-port far fields (phased.load), or None: the bar hidden."""
        self.anim.setChecked(False)
        self.res, self.data = res, data
        self.setVisible(data is not None)
        if data is not None:
            self.aim_row.setVisible(set(self.places()) == set(data['ports']))
            self._reset(emit=False)

    def _show_2d(self, on):
        for w in (self.label_y, self.slider_y, self.spin_y, self.map):
            w.setVisible(on)
        self.label_x.setText('X step' if on else 'Phase step')
        self._anim_modes()

    def _anim_modes(self):
        """Animate's choices: the angle with Aim, X / Y / Circle with a grid, else the one step (no choice)."""
        modes = AIM_MODES if self.aiming() else ANIM_MODES if self._grid else ()
        have = tuple(self.anim_mode.itemText(i) for i in range(self.anim_mode.count()))
        if modes and have != modes:
            self.anim_mode.blockSignals(True)
            self.anim_mode.clear()
            self.anim_mode.addItems(modes)
            self.anim_mode.blockSignals(False)
        self.anim_mode.setVisible(bool(modes))

    def places(self):
        """{port: (x, y)} of the ports the run kept places for (model mm), empty for an older result."""
        pos = (self.data or {}).get('pos')
        if pos is None:
            return {}
        return {n: (float(x), float(y)) for n, (x, y) in zip(self.data['ports'], np.asarray(pos, float))
                if np.isfinite(x) and np.isfinite(y)}

    def aiming(self):
        return self.aim.isChecked() and self.aim_row.isVisible()

    def _aim_changed(self):
        for w in (self.theta, self.phi):
            w.setEnabled(self.aim.isChecked())
        self._anim_modes()
        self.update()

    def _set_aim(self, aim):
        """The aim controls from [theta, phi] or None (off), without an update."""
        for w in (self.aim, self.theta, self.phi):
            w.blockSignals(True)
        self.aim.setChecked(bool(aim))
        if aim:
            self.theta.setValue(aim[0])
            self.phi.setValue(aim[1])
        for w in (self.aim, self.theta, self.phi):
            w.blockSignals(False)
            w.setEnabled(w is self.aim or bool(aim))
        self._anim_modes()

    def _set_steps(self, x, y):
        """Both steps (and their sliders) without an update each."""
        for w, v in ((self.spin, x), (self.slider, x), (self.spin_y, y), (self.slider_y, y)):
            w.blockSignals(True)
            w.setValue(int(round(v)))
            w.blockSignals(False)

    def taper_spec(self):
        kind = phased.TAPERS[self.taper.currentIndex()]
        return f"{kind}:{self.sll.value():g}" if kind in ('taylor', 'chebyshev') else kind

    def _set_taper(self, spec):
        """The taper controls from a spec (phased.parse_taper's), without an update; a bad one: uniform."""
        try:
            kind, sll = phased.parse_taper(spec)
        except ValueError:
            kind, sll = 'uniform', phased.TAPER_SLL
        for w in (self.taper, self.sll):
            w.blockSignals(True)
        self.taper.setCurrentIndex(phased.TAPERS.index(kind))
        self.sll.setValue(sll)
        for w in (self.taper, self.sll):
            w.blockSignals(False)
        self.sll.setEnabled(kind in ('taylor', 'chebyshev'))

    def _taper_changed(self, update=True):
        self.sll.setEnabled(phased.TAPERS[self.taper.currentIndex()] in ('taylor', 'chebyshev'))
        if update:
            self.update()

    def _parse_grid(self):
        """The grid field's places (phased.parse_grid), shown or hidden with it; ValueError for a bad one."""
        g = phased.parse_grid(self.grid.text(), self.data['ports'])
        self._grid = g
        self._show_2d(bool(g))
        return g

    def _parse_grid_quiet(self):
        """_parse_grid, a bad grid left for update() to report."""
        try:
            self._parse_grid()
        except ValueError:
            pass

    def _reset(self, *_, emit=True):
        d, res = self.data, self.res or {}
        if res.get('drive_base'):                                   # the run's settings: untapered, unsteered
            drive, steps = res['drive_base'], (list(res.get('steer') or []) + [0, 0])[:2]
            self._set_taper(res.get('taper'))
        else:                                                       # the run's drive as it was driven
            drive, steps = res.get('drive') or phased.format_drive(d['drive'], d['ports']), [0, 0]
            self._set_taper(None)
        self.drive.setText(', '.join(drive))
        self.grid.setText(res.get('grid') or '')
        self._set_steps(*steps)
        self._set_aim(res.get('aim') if res.get('drive_base') else None)
        self.update(emit=emit)

    def mirror(self, other):
        """Show another bar's drive, grid and phase steps (its plots are already drawn: nothing emitted)."""
        if self.data is None:
            return
        self.drive.setText(other.drive.text())
        self.grid.setText(other.grid.text())
        self._set_taper(other.taper_spec())
        self._set_aim([other.theta.value(), other.phi.value()] if other.aim.isChecked() else None)
        self._parse_grid_quiet()
        self.anim_mode.blockSignals(True)
        self.anim_mode.setCurrentIndex(other.anim_mode.currentIndex())
        self.anim_mode.blockSignals(False)
        self._set_steps(other.spin.value(), other.spin_y.value())
        self.update(emit=False)

    def follow_animation(self, on):
        """Another bar started or stopped Animate: the button shows it, this bar's own timer stays off."""
        self.timer.stop()
        self.anim.blockSignals(True)
        self.anim.setChecked(on)
        self.anim.blockSignals(False)

    def weights(self):
        """The incident waves of the drive, the taper, the grid and the phase steps; ValueError for a drive or
        grid that does not parse."""
        names = self.data['ports']
        a = phased.parse_drive([x for x in self.drive.text().split(',')], names)
        if not np.any(np.abs(a) > 0):
            raise ValueError("drive: no port driven")
        g = self._parse_grid()
        a = phased.taper(a, names, g, self.taper_spec())
        a = phased.steer2d(a, names, g, self.spin.value(), self.spin_y.value() if g else 0)
        if self.aiming():
            a = phased.aim(a, names, self.places(), self.theta.value(), self.phi.value(), self.data['f_pattern'])
        return a

    def update(self, emit=True):
        if self.data is None:
            return None
        try:
            a = self.weights()
        except ValueError as e:
            self.readout.setText(f"<span style='color:#c62828'>{e}</span>")
            return None
        c = phased.combine(self.data, a)
        names = self.data['ports']
        res = dict(self.res or {}, rows=c['rows'], peak=c['peak'], drive=phased.format_drive(a, names))
        if self._grid:
            res['grid'] = phased.format_grid(self._grid, names)
        else:
            res.pop('grid', None)
        for k in ('drive_base', 'taper', 'steer', 'aim'):           # the run's: this drive is all in 'drive'
            res.pop(k, None)
        pk = c['peak']
        ip = int(np.argmin(np.abs(self.data['freq'] - pk['f'])))
        act = [(n, 20 * np.log10(max(abs(v), 1e-15))) for n, v in zip(names, c['active'][ip]) if np.isfinite(v)]
        r = c['rows'][ip]
        g = f"{pk['gain_dbi']:.2f} dBi" if pk['gain_dbi'] is not None else '-'
        head = (f"steps X {self.spin.value()}°, Y {self.spin_y.value()}°" if self._grid else
                ', '.join(res['drive']))
        if self.aiming():
            head += f", aimed at θ {self.theta.value():g}°, φ {self.phi.value():g}°"
        if self.taper.currentIndex():
            head += f", {self.taper.currentText()}" + (f" −{self.sll.value():g} dB" if self.sll.isEnabled() else '')
        if len(act) > 4:                                            # a large array: the range, the worst named
            worst = max(act, key=lambda t: t[1])
            act_s = f"{min(v for _, v in act):.1f} to {worst[1]:.1f} dB (worst {worst[0]})"
        else:
            act_s = ', '.join(f"{n} {v:.1f} dB" for n, v in act)
        self.readout.setText(f"{head}: beam at θ {pk['theta']:g}°, φ {pk['phi']:g}°, gain {g}, "
                             f"realized {r['Grealized_dbi'] or float('nan'):.2f} dBi at {pk['f'] / 1e9:.4g} GHz; "
                             f"active reflection {act_s}")
        if self._grid:
            self.map.set(names, self._grid, a, c['active'][ip])
        if emit:
            self.steered.emit(res, c['sphere'])
        return res, c['sphere']

    # ---- Animate ---------------------------------------------------------------------------------------
    def _restart_circle(self):
        x, y = self.spin.value(), self.spin_y.value()
        rr = math.hypot(x, y)
        self._r = min(rr, STEP_MAX) if rr >= ANIM_DEG else CIRCLE_R
        self._t = math.atan2(y, x) if rr >= ANIM_DEG else 0.0

    def _animate(self, on):
        if on:
            self._restart_circle()
            self.timer.start()
        else:
            self.timer.stop()

    def _frame(self):
        if self.aiming():                                          # the angle: theta to and fro, or phi round
            if self.anim_mode.currentText() == 'φ':
                self.phi.setValue((self.phi.value() + ANIM_DEG + 180) % 360 - 180)
                return
            v = self.theta.value() + self._dir * ANIM_DEG
            if not 0 <= v <= AIM_THETA_MAX:
                self._dir = -self._dir
                v = self.theta.value() + self._dir * ANIM_DEG
            self.theta.setValue(v)
            return
        mode = ANIM_MODES[self.anim_mode.currentIndex()] if self._grid else 'X'
        if mode == 'Circle':
            self._t += math.radians(ANIM_DEG)
            self._set_steps(self._r * math.cos(self._t), self._r * math.sin(self._t))
            self.update()
            return
        spin = self.spin_y if mode == 'Y' else self.spin
        v = spin.value() + self._dir * ANIM_DEG
        if abs(v) > STEP_MAX:
            self._dir = -self._dir
            v = spin.value() + self._dir * ANIM_DEG
        spin.setValue(v)
