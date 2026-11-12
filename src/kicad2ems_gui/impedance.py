"""
Tools > Impedance calculator: a line's impedance in a stack-up, without a board (kicad2ems's lines.calc: the 2D field
solver). The stack typed, or the open board's around one of its copper layers; the line's width and copper, a pair's
gap, coplanar ground; Z0, Zdiff, εeff and the delay as they are typed, the field drawn (the viewer's Section view),
and Fit: the width or gap of a target impedance.

    dlg = ImpedanceCalculator(parent, board='board.kicad_pcb')      # board: optional, its layers offered as stacks
    dlg.line()                                                      # the lines.calc.Line of what is typed
    dlg.result                                                      # calculate()'s dict of it, once solved
"""
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QComboBox, QCheckBox, QLabel,
                               QDoubleSpinBox, QPushButton, QApplication, QWidget, QSplitter)
from kicad2ems.api.frontend import impedance as K
from .sectionview import SectionView

OVER = [('air', 'air'), ('mask', 'solder mask'), ('plane', 'a dielectric, then a plane (stripline)'),
        ('open', 'a dielectric, open above (embedded)')]
WHAT_ONE, WHAT_PAIR = [('z0', 'Z0')], [('zdiff', 'Zdiff'), ('zcommon', 'Zcommon'), ('zodd', 'Zodd'), ('zeven', 'Zeven')]
VARY = [('w', 'the width'), ('gap', "the pair's gap"), ('ground_gap', "the ground's distance")]


class _Solve(QThread):
    done = Signal(int, object, object)                  # the request's number, the Line solved, its result or the error

    def __init__(self, token, line, fit, parent=None):
        super().__init__(parent)
        self.token, self.line, self.fit = token, line, fit

    def run(self):
        try:
            line = K.fit(self.line, *self.fit) if self.fit else self.line
            self.done.emit(self.token, line, K.calculate(line))
        except Exception as e:                          # noqa: BLE001 (a stack it cannot solve, a target out of reach)
            self.done.emit(self.token, self.line, e)


def _num(value, lo, hi, step, decimals=4, suffix=' mm'):
    b = QDoubleSpinBox()
    b.setDecimals(decimals)
    b.setRange(lo, hi)
    b.setSingleStep(step)
    b.setValue(value)
    b.setSuffix(suffix)
    b.setKeyboardTracking(False)                        # a value typed counts when it is finished
    return b


class ImpedanceCalculator(QDialog):
    """The calculator's window. Every change solves again (a tenth of a second); Fit changes the width, the gap or
    the ground's distance until the impedance chosen is the target."""

    def __init__(self, parent=None, board=None):
        super().__init__(parent)
        self.setWindowTitle('Impedance calculator')
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1040, 620)
        self.result, self.error, self.solved = None, '', None
        self._token, self._jobs, self._setting, self.board = 0, [], False, None
        split = QSplitter(Qt.Horizontal)
        outer = QVBoxLayout(self)
        outer.addWidget(split)
        left = QWidget()
        col = QVBoxLayout(left)
        col.setContentsMargins(0, 0, 0, 0)

        # ---- the stack ----
        box = QGroupBox('Stack')
        form = QFormLayout(box)
        self.stack = QComboBox()
        self.stack.setToolTip("The dielectrics as typed below, or the open board's own around one of its copper "
                              "layers (the copper layers next to it taken as planes)")
        form.addRow('From', self.stack)
        self.stack_note = QLabel()
        self.stack_note.setWordWrap(True)
        self.stack_note.setStyleSheet('color: gray')
        form.addRow(self.stack_note)
        self.h, self.er, self.tand = _num(0.2, 0.005, 20, 0.01), _num(4.3, 1, 100, 0.1, 3, ''), _num(0.02, 0, 1, 0.001, 4, '')
        row = QHBoxLayout()
        for label, w in (('', self.h), ('εr', self.er), ('tan δ', self.tand)):
            if label:
                row.addWidget(QLabel(label))
            row.addWidget(w)
        self.below_row = self._row(row)
        form.addRow('Under the copper', self.below_row)
        self.over = QComboBox()
        for key, label in OVER:
            self.over.addItem(label, key)
        form.addRow('Over the copper', self.over)
        self.h2, self.er2 = _num(0.2, 0.005, 20, 0.01), _num(4.3, 1, 100, 0.1, 3, '')
        row = QHBoxLayout()
        row.addWidget(self.h2)
        row.addWidget(QLabel('εr'))
        row.addWidget(self.er2)
        self.over_row = self._row(row)
        self.over_label = QLabel('its thickness')
        form.addRow(self.over_label, self.over_row)
        self.stack_form = form
        col.addWidget(box)

        # ---- the line ----
        box = QGroupBox('Line')
        form = QFormLayout(box)
        self.w, self.t = _num(0.35, 0.01, 50, 0.01), _num(0.035, 0, 1, 0.005)
        form.addRow('Width', self.w)
        form.addRow('Copper', self.t)
        self.pair = QCheckBox('A pair, its gap')
        self.gap = _num(0.15, 0.01, 20, 0.01)
        form.addRow(self.pair, self.gap)
        self.ground = QCheckBox('Ground beside it, away')
        self.ground.setToolTip('Coplanar ground on the same layer, this far from the copper (a grounded coplanar line)')
        self.ground_gap = _num(0.2, 0.01, 20, 0.01)
        form.addRow(self.ground, self.ground_gap)
        col.addWidget(box)

        # ---- the target ----
        box = QGroupBox('Find the size of an impedance')
        row = QHBoxLayout(box)
        self.target = _num(50, 1, 500, 1, 2, ' Ω')
        self.what, self.vary = QComboBox(), QComboBox()
        self.fit_btn = QPushButton('Fit')
        self.fit_btn.setToolTip('Change the size chosen until the impedance is the target (to 0.1 %)')
        self.fit_btn.clicked.connect(lambda: self.calculate(fit=True))
        for w in (self.what, QLabel('of'), self.target, QLabel('by'), self.vary, self.fit_btn):
            row.addWidget(w)
        col.addWidget(box)

        self.out = QLabel()
        self.out.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.out.setWordWrap(True)
        self.out.setTextFormat(Qt.RichText)
        col.addWidget(self.out)
        col.addStretch(1)
        row = QHBoxLayout()
        self.copy_btn = QPushButton('Copy')
        self.copy_btn.setToolTip('The line and its numbers, as text')
        self.copy_btn.clicked.connect(self.copy)
        row.addStretch(1)
        row.addWidget(self.copy_btn)
        col.addLayout(row)
        split.addWidget(left)
        self.view = SectionView(model_line=False)
        self.view.info.setText('')
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        split.setSizes([380, 660])

        self._later = QTimer(self)                      # a run of edits: one solve when it pauses
        self._later.setSingleShot(True)
        self._later.setInterval(150)
        self._later.timeout.connect(self.calculate)
        for b in (self.h, self.er, self.tand, self.h2, self.er2, self.w, self.t, self.gap, self.ground_gap):
            b.valueChanged.connect(self._changed)
        for c in (self.pair, self.ground):
            c.toggled.connect(self._changed)
        for c in (self.over, self.stack):
            c.currentIndexChanged.connect(self._changed)
        self.set_board(board)

    @staticmethod
    def _row(layout):
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    # ---- the stack's source ----
    def set_board(self, path):
        """The board whose layers the stack can be taken from (None, or one without a stack-up: typed only)."""
        self.board = path or None
        keep = self.stack.currentData()
        layers = []
        if path:
            try:
                layers = K.board_layers(path)
            except Exception:                           # noqa: BLE001 (not a board this reads: typed only)
                layers = []
        self._setting = True
        self.stack.clear()
        self.stack.addItem('typed here', None)
        for name in layers:
            self.stack.addItem(f"{name} of the open board", name)
        i = self.stack.findData(keep)
        self.stack.setCurrentIndex(max(i, 0))
        self._setting = False
        self._changed()                                 # another board's layer of that name is another stack

    # ---- the line typed ----
    def line(self):
        """The Line of what is typed (ValueError: what is wrong with it)."""
        kw = dict(t=self.t.value())
        if self.pair.isChecked():
            kw['gap'] = self.gap.value()
        if self.ground.isChecked():
            kw['ground_gap'] = self.ground_gap.value()
        layer = self.stack.currentData()
        if layer:
            return K.Line.on_board(self.board, layer, self.w.value(), **kw)
        below = [(self.h.value(), self.er.value(), self.tand.value())]
        over = self.over.currentData()
        if over == 'mask':
            kw.update(mask=self.h2.value(), er_mask=self.er2.value())
        elif over in ('plane', 'open'):
            kw.update(above=[(self.h2.value(), self.er2.value(), self.tand.value())], top_plane=over == 'plane')
        return K.Line(self.w.value(), below=below, **kw)

    def _sync(self):
        """What can be typed follows what is chosen: a board's layer hides the typed stack, air its thickness, a
        single line the pair's impedances."""
        self._setting = True
        typed = not self.stack.currentData()
        for w in (self.below_row, self.over, self.over_row, self.over_label):
            w.setVisible(typed)
        for w in (self.below_row, self.over):
            self.stack_form.labelForField(w).setVisible(typed)
        over = self.over.currentData()
        self.over_row.setVisible(typed and over != 'air')
        self.over_label.setVisible(typed and over != 'air')
        self.over_label.setText("the mask's thickness" if over == 'mask' else 'its thickness')
        if typed and over == 'mask' and self.h2.value() > 0.1:      # a mask is thin: not the stripline's 0.2 mm
            self.h2.setValue(0.02)
            self.er2.setValue(3.5)
        self.gap.setEnabled(self.pair.isChecked())
        self.ground_gap.setEnabled(self.ground.isChecked())
        for combo, items in ((self.what, WHAT_PAIR if self.pair.isChecked() else WHAT_ONE),
                             (self.vary, [v for v in VARY if v[0] == 'w' or (v[0] == 'gap' and self.pair.isChecked())
                                          or (v[0] == 'ground_gap' and self.ground.isChecked())])):
            keep = combo.currentData()
            combo.clear()
            for key, label in items:
                combo.addItem(label, key)
            combo.setCurrentIndex(max(combo.findData(keep), 0))
        self._setting = False

    def _changed(self, *_):
        if self._setting:
            return
        self._sync()
        self._later.start()

    # ---- solving ----
    def calculate(self, fit=False):
        """Solve what is typed (fit: first change the size chosen to the target's). The answer arrives in _done."""
        self._later.stop()
        try:
            line = self.line()
        except Exception as e:                          # noqa: BLE001 (a line that cannot be: say why)
            self._show_error(str(e))
            return
        self.stack_note.setText(K.describe(line) if self.stack.currentData() else '')
        self.stack_note.setVisible(bool(self.stack.currentData()))
        self._token += 1
        args = (self.target.value(), self.what.currentData(), self.vary.currentData()) if fit else None
        job = _Solve(self._token, line, args, self)
        job.done.connect(self._done)
        job.finished.connect(lambda j=job: self._jobs.remove(j))
        self._jobs.append(job)
        self.fit_btn.setEnabled(False)
        if fit:
            self.out.setText('fitting…')
        job.start()

    def busy(self):
        return bool(self._jobs) or self._later.isActive() or self.view.busy()

    def _show_error(self, text):
        self.result, self.error, self.solved = None, text, None
        self.out.setText(f"<span style='color:#b00020'>{text}</span>")
        self.view.show_section(None)
        self.view.info.setText('')

    def _done(self, token, line, r):
        if token != self._token:                        # something was typed meanwhile: its own solve follows
            return
        self.fit_btn.setEnabled(True)
        if isinstance(r, Exception):
            self._show_error(str(r))
            return
        self._setting = True                            # a fit's size back into its box
        for box, v in ((self.w, line.w), (self.gap, line.gap), (self.ground_gap, line.ground_gap)):
            if v is not None and abs(box.value() - v) > 1e-9:
                box.setValue(v)
        self._setting = False
        self.result, self.error, self.solved = r, '', line
        self.out.setText(self._html(line, r))
        self.view.show_section(K.element(line, r))

    @staticmethod
    def _html(line, r):
        big = "<span style='font-size:15pt'><b>{}</b></span>"
        if line.pair:
            head = big.format(f"Zdiff {r['zdiff']:.2f} Ω") + f" &nbsp; Zcommon {r['zcommon']:.2f} Ω"
            rows = [('odd / even mode', f"{r['zodd']:.2f} / {r['zeven']:.2f} Ω"),
                    ('εeff odd / even', f"{r['eeff_odd']:.3f} / {r['eeff_even']:.3f}"),
                    ('one strip alone', f"{r['z0']:.2f} Ω"), ('coupling', f"{100 * r['coupling']:.1f} %")]
        else:
            head = big.format(f"Z0 {r['z0']:.2f} Ω") + f" &nbsp; εeff {r['eeff']:.3f}"
            rows = []
        rows += [('delay', f"{r['delay_ps_mm']:.3f} ps/mm"), ('C, L', f"{r['c_pf_m']:.1f} pF/m, {r['l_nh_m']:.1f} nH/m")]
        if r['tand_eff']:
            rows.append(('tan δ, effective', f"{r['tand_eff']:.4f}"))
        if 'formula' in r:
            name, z, _ = r['formula']
            rows.append(('formula', f"{z:.2f} Ω ({name}; the solver {(r['z0'] - z) / z * 100:+.1f} %)"))
        body = ''.join(f"<tr><td style='color:gray; padding-right:12px'>{k}</td><td>{v}</td></tr>" for k, v in rows)
        return f"{head}<table>{body}</table><span style='color:gray'>{K.describe(line)}</span>"

    def text(self):
        """The line and its numbers as the command prints them ('' before a solve)."""
        return '\n'.join(K.report(self.solved, self.result)) if self.result else ''

    def copy(self):
        QApplication.clipboard().setText(self.text())
