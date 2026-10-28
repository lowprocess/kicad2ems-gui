"""
The Filter page: design a microstrip filter with dfsynth (its own package: the filter extra), see its layout, dimensions and line-model
response, validate it on the solvers and tune it from them, and open the board it wrote as a kicad2ems config.

dfsynth runs as a separate process, as kicad2ems runs do: the page follows its output, and reads what it wrote when
it ends (<out>_design.json: the spec, the dimensions, the layout; <out>_model.s2p; each validation round's
S-parameters in <out>_em/, <out>_em_tune1/, ...). The page never imports dfsynth: its types and topologies, its
substrate presets and its options come from `dfsynth --describe --json`, so the command line is its only link.

    describe()                 dfsynth's description (types, presets, options), or None when it cannot run here
    filter_argv(vals)          dfsynth's command line for the page's settings
    load_design(base)          what a dfsynth run wrote under <base>: design, model and EM responses
    line_level(line)           'error', 'warn' or None: how the page's log shows a line of dfsynth's output
"""
import glob, html, json, os, re, shutil, sys
import numpy as np

DFSYNTH_PIP = "python -m pip install 'kicad2ems[filter]' (or 'dfsynth @ git+https://github.com/lowprocess/dfsynth')"


_DESCRIPTIONS = {}
DESCRIBE_FORMAT = 1                 # the --describe --json format this page reads


def describe(python=None):
    """dfsynth's description, from `dfsynth --describe --json` in this Python (or `python`): {'kinds': {type:
    [topologies]}, 'presets': {name: {h, er, tand, material}}, 'options': [{key, flag, kind, default, choices, help,
    group}]}. None when dfsynth cannot run there: not installed, too old to describe itself, or describing itself
    in another format (why_not says which). Asked once."""
    return _describe(python)[0]


def why_not(python=None):
    """Why describe() gave None, as the page says it ('' when it did not)."""
    return _describe(python)[1]


def _describe(python=None):
    import subprocess
    python = python or sys.executable
    if python not in _DESCRIPTIONS:
        d, why = None, ''
        try:
            p = subprocess.run([python, '-m', 'dfsynth', '--describe', '--json'], capture_output=True, text=True,
                               timeout=60)
            if p.returncode == 0:
                d = json.loads(p.stdout)
                if d.get('format') != DESCRIBE_FORMAT:
                    d, why = None, (f"dfsynth {d.get('version', '?')} describes itself in format {d.get('format')}, "
                                    f"this page reads {DESCRIBE_FORMAT}: update "
                                    f"{'kicad2ems-gui' if (d.get('format') or 0) > DESCRIBE_FORMAT else 'dfsynth'}")
            elif 'No module named dfsynth' in p.stderr:
                why = f"dfsynth is not installed, so filters cannot be designed here: {DFSYNTH_PIP}"
            elif '--describe' in p.stderr:                          # argparse: unrecognized arguments
                why = (f"this dfsynth is too old for the page (it has no --describe): update it, "
                       f"python -m pip install -U 'dfsynth @ git+https://github.com/lowprocess/dfsynth'")
            else:
                why = f"dfsynth --describe failed: {(p.stderr.strip().splitlines() or ['?'])[-1]}"
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            why = f"dfsynth --describe failed: {type(e).__name__}: {e}"
        _DESCRIPTIONS[python] = (d, why)
    return _DESCRIPTIONS[python]


def options(desc):
    """{key: option} of a description, in dfsynth's order."""
    return {o['key']: o for o in (desc or {}).get('options', [])}


def filter_argv(vals, validate=True, desc=None):
    """dfsynth's command line (after the interpreter) for the page's values; None / '' leave dfsynth's default.
    validate False: the design only (no --validate, --em-tune, --k2e-args). desc: dfsynth's description
    (default: describe()); a value of no option it has is left out."""
    argv = ['-u', '-m', 'dfsynth']
    for key, o in options(desc or describe()).items():
        opt, kind = o['flag'], o['kind']
        v = vals.get(key)
        if not validate and key in ('validate', 'em_tune', 'k2e_args'):
            continue
        if kind == 'flag':
            if v:
                argv.append(opt)
        elif v not in (None, ''):
            argv += [opt, str(int(v) if kind == 'int' else v)]
    return argv


def _em_rounds(base):
    """[(round label, {solver: s2p path})] of a dfsynth validation under <base>: <base>_em, <base>_em_tune1, ..."""
    name = os.path.basename(base)
    out = []
    for d in sorted(glob.glob(base + '_em') + glob.glob(base + '_em_tune*'),
                    key=lambda d: int(d.rsplit('tune', 1)[1]) if '_em_tune' in d else 0):
        files = {}
        for p in sorted(glob.glob(os.path.join(d, name + '_*.s2p'))):
            solver = os.path.basename(p)[len(name) + 1:-4]
            if solver != 'qucs':                                    # kicad2ems's line model: not dfsynth's
                files[solver] = p
        if files:
            out.append(('round 0' if d.endswith('_em') else 'round ' + d.rsplit('tune', 1)[1], files))
    return out


def load_design(base):
    """What dfsynth wrote under <base>, or None: {'design': the design JSON, 'model': (f, S) of the line model,
    'em': [(round, {solver: (f, S)})], 'pcb', 'toml'}."""
    from kicad2ems.api.frontend import read_touchstone
    path = base + '_design.json'
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        design = json.load(fh)
    model = read_touchstone(base + '_model.s2p') if os.path.exists(base + '_model.s2p') else None
    # only this run's rounds (the design JSON lists them): a folder of an earlier run with more rounds is not one
    rounds = _em_rounds(base)[:len(design.get('em') or [])]
    em = [(lab, {k: read_touchstone(p) for k, p in files.items()}) for lab, files in rounds]
    return {'design': design, 'model': model, 'em': em, 'pcb': base + '.kicad_pcb', 'toml': base + '.toml'}


# what in dfsynth's output is a problem: its errors (and Python's), and the warnings it gives
ERRORS = re.compile(r'^(dfsynth:|Traceback|\w*(Error|Exception)\b)|\berror:')
WARNINGS = re.compile(r'note:|warning|stopping the tuning|too large to tune|no band edge|not installed|'
                      r'no improvement|below the|cannot|not found', re.I)


K2E_WARNINGS = re.compile(r'warning|stopped at --max-steps|still be ringing', re.I)
PROGRESS = re.compile(r'^ {4}\S+: (step \d+|\d+% )')             # dfsynth's lines of a solver's progress


def line_level(line, after=None):
    """'error', 'warn' or None for a line of dfsynth's output; `after` the previous line's level (an error's
    indented lines, a traceback's, are the error too)."""
    if ERRORS.search(line.strip()):
        return 'error'
    if after == 'error' and line[:1].isspace() and line.strip():
        return 'error'
    if line.startswith(' ' * 4):                                # kicad2ems's own output, followed: its warnings
        return 'warn' if K2E_WARNINGS.search(line) else None   # (its notes are routine here)
    return 'warn' if WARNINGS.search(line) else None


def _db(x):
    return 20 * np.log10(np.maximum(np.abs(x), 1e-12))


# ------------------------------------------------------------------------------------------- the page (Qt)
from PySide6.QtCore import Qt, QProcess
from PySide6.QtGui import QPainterPath, QPen, QBrush, QColor, QFontDatabase, QTextCursor, QTextCharFormat, QIcon
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QComboBox, QCheckBox,
                               QPushButton, QPlainTextEdit, QSplitter, QTabWidget, QTableWidget,
                               QTableWidgetItem, QScrollArea, QFileDialog, QSpinBox, QHeaderView,
                               QGraphicsPathItem, QGraphicsEllipseItem, QStyle, QProgressBar)
import pyqtgraph as pg
from .panels import Section

COPPER = QColor(214, 140, 64)
VIA = QColor(90, 90, 90)
LEVELS = {'error': ('#d00000', '✖ '), 'warn': ('#d00000', '⚠ ')}       # red, both: the log's problems
COLORS = ['#1f77b4', '#d62728', '#2ca02c', '#9467bd', '#8c564b', '#e377c2']


def validation_solvers():
    """The Filter page's solver choices: each full-wave solver installed (kicad2ems's registry), then each with
    the line model."""
    from kicad2ems.api.frontend import registry
    full = [n for n, sv in registry().items() if sv.consumes == 'board']
    return full + [f"{n},lines" for n in full]


class FilterTab(QWidget):
    """dfsynth's settings on the left; the layout, the responses, the dimensions and the log on the right."""

    def __init__(self, win=None):
        super().__init__()
        self.win, self.proc, self.base, self.result = win, None, None, None
        self.problems, self._last = {'error': 0, 'warn': 0}, None
        self.desc = describe()
        self.opts = options(self.desc)
        lay = QHBoxLayout(self)
        self.split = QSplitter(Qt.Horizontal)
        lay.addWidget(self.split)
        self.split.addWidget(self._form())
        self.split.addWidget(self._views())
        self.split.setSizes([380, 900])
        self._type_changed()
        if self.desc is None:                                       # nothing to design with: say so, up front
            self.split.widget(0).setEnabled(False)
            self.say(why_not() or f"dfsynth cannot be run here: {DFSYNTH_PIP}", 'error')

    # ---- the settings ----
    def _line(self, hint='', tip=''):
        e = QLineEdit()
        e.setPlaceholderText(hint)
        e.setToolTip(tip)
        return e

    def _form(self):
        d = self.desc
        kinds = d['kinds'] if d else {'bandpass': ('coupled',)}
        presets = list(d['presets']) if d else ['RO4003C-0.508']
        self.w = {}
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)

        def section(title, rows, expanded=False):
            inner = QWidget()
            f = QFormLayout(inner)
            f.setContentsMargins(0, 0, 0, 0)
            for label, key, wid in rows:
                self.w[key] = wid
                f.addRow(label, wid)
            v.addWidget(Section(title, inner, expanded))

        typ = QComboBox()
        typ.addItems(list(kinds))
        typ.setCurrentText('bandpass')
        typ.currentTextChanged.connect(self._type_changed)
        topo = QComboBox()
        topo.currentTextChanged.connect(self._topology_changed)
        resp = QComboBox()
        resp.addItems(['chebyshev', 'butterworth'])
        order = QSpinBox()
        order.setRange(0, 15)
        order.setSpecialValueText('auto')                           # 0: from the attenuation, else 5
        order.setToolTip('filter order; auto: the lowest meeting the attenuation, else 5')
        section('Filter', [
            ('Type', 'type', typ), ('Topology', 'topology', topo),
            ('f0', 'f0', self._line('e.g. 5G', 'centre (band-pass / band-stop) or cut-off frequency: 2.4G, 500M')),
            ('Bandwidth', 'bw', self._line('e.g. 500M', 'band-pass / band-stop: the ripple band (Chebyshev); '
                                           'high-pass: the pass band above the cut-off')),
            ('Response', 'response', resp), ('Order', 'order', order),
            ('Attenuation', 'atten', self._line('e.g. 40@6G', 'stop-band spec DB@FREQ: picks the order')),
            ('Ripple (dB)', 'ripple', self._line('0.1')), ('Z0 (Ω)', 'z0', self._line('50'))], expanded=True)
        section('Topology details', [
            ('High Z (Ω)', 'zhigh', self._line('chosen', 'low-pass: the high-impedance lines')),
            ('Low Z (Ω)', 'zlow', self._line('chosen', 'stepped low-pass: the low-impedance sections')),
            ('Stub / rod Z (Ω)', 'zstub', self._line('chosen', 'stub low-pass: the stubs; interdigital: the rods')),
            ('Fan angle (°)', 'stub_angle', self._line('60', 'radial low-pass: the fans\' apex angle')),
            ('Hairpin gap (mm)', 'hairpin_gap', self._line('chosen', "hairpin: the gap between a resonator's own arms")),
            ('Feed (mm)', 'feed', self._line('chosen', '50 Ω feed line at each port'))])
        sub = QComboBox()
        sub.addItems(presets)
        sub.setCurrentText('RO4003C-0.813' if 'RO4003C-0.813' in presets else presets[0])
        sub.currentTextChanged.connect(self._substrate_changed)
        allow = QCheckBox('allow below the limits')
        allow.setToolTip('write designs with traces or gaps below the minimums (refused by default)')
        section('Substrate and fabrication', [
            ('Preset', 'substrate', sub), ('Height (mm)', 'h', self._line()), ('εr', 'er', self._line()),
            ('tan δ', 'tand', self._line()), ('Copper (mm)', 'copper', self._line('0.035')),
            ('Min trace (mm)', 'min_width', self._line('0.1', 'fabrication minimum trace width')),
            ('Min space (mm)', 'min_gap', self._line('0.1', 'fabrication minimum gap')),
            ('', 'allow_fab_violations', allow)], expanded=True)
        out = self._line('', "output base path: <out>.kicad_pcb, <out>.toml, <out>_design.json, ...")
        browse = QPushButton('…')
        browse.setFixedWidth(28)
        browse.clicked.connect(self._browse)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(out, 1)
        rl.addWidget(browse)
        self.w['out'] = out
        nocal = QCheckBox('no calibration')
        nocal.setToolTip('skip the line-model calibration: the textbook synthesis as it is')
        section('Output', [('Base path', '_out_row', row), ('', 'no_calibrate', nocal),
                           ('Refine limit (s)', 'refine_time',
                            self._line('10', "time limit of the calibration's final refinement (low-pass, band-stop, "
                                             "interdigital): past it the best so far is kept"))], expanded=True)
        self.w.pop('_out_row')
        solv = QComboBox()
        solv.setEditable(True)
        solv.addItems(validation_solvers())
        solv.setToolTip("kicad2ems solvers for the validation, comma-separated (the full-wave ones installed here, "
                        "alone or with the line model)")
        tune = QSpinBox()
        tune.setRange(0, 6)
        tune.setToolTip('rounds of correcting the design from the full-wave result (interdigital: space mapping)')
        section('Validation', [
            ('Solvers', 'validate', solv), ('Tune rounds', 'em_tune', tune),
            ('kicad2ems args', 'k2e_args', self._line('e.g. --fine 0.03', 'extra kicad2ems arguments'))],
            expanded=True)
        more = [(o['flag'], key, self._option_widget(o)) for key, o in self.opts.items() if key not in self.w]
        if more:                                                    # dfsynth's options the page has no place for
            section('More options', more)
        for key, w in self.w.items():
            o = self.opts.get(key)
            if o is None and d is not None:                         # this dfsynth has no such option
                w.setEnabled(False)
                w.setToolTip(f"this dfsynth ({d.get('version', '?')}) has no such option")
            elif o is not None and not w.toolTip():
                w.setToolTip(f"{o['flag']}: {o['help']}")
        foot = QWidget()                                            # the buttons, below the settings: always in view
        fv = QVBoxLayout(foot)
        fv.setContentsMargins(6, 4, 6, 6)
        btns = QHBoxLayout()
        self.design_btn = QPushButton('Design')
        self.design_btn.setToolTip('synthesise, calibrate on the line model and write the board')
        self.design_btn.clicked.connect(lambda: self.start(validate=False))
        self.validate_btn = QPushButton('Design + validate')
        self.validate_btn.setToolTip('the same, then solve the board with the solvers chosen (and tune it)')
        self.validate_btn.clicked.connect(lambda: self.start(validate=True))
        self.stop_btn = QPushButton('Stop')
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        for b in (self.design_btn, self.validate_btn, self.stop_btn):
            btns.addWidget(b)
        fv.addLayout(btns)
        self.busy = QProgressBar()                                  # while dfsynth runs: what it is doing
        self.busy.setRange(0, 0)
        self.busy.hide()
        fv.addWidget(self.busy)
        self.open_btn = QPushButton('Open the board in kicad2ems')
        self.open_btn.setToolTip("the config dfsynth wrote, in the main settings: preview it, run any solver")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self.open_in_kicad2ems)
        fv.addWidget(self.open_btn)
        v.addStretch(1)
        self._substrate_changed(sub.currentText())
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(box)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        lv.addWidget(sc, 1)
        lv.addWidget(foot)
        return left

    def _option_widget(self, o):
        """A widget for one of dfsynth's options, from its declaration: a tick box, a choice or a text field."""
        if o['kind'] == 'flag':
            return QCheckBox(o['help'])
        if o['choices']:
            w = QComboBox()
            w.addItems([''] + [str(c) for c in o['choices']])
            return w
        return self._line('' if o['default'] in (None, '', 0, 0.0) else str(o['default']), o['help'])

    def _type_changed(self, *_):
        kinds = self.desc['kinds'] if self.desc else {'bandpass': ('coupled',)}
        topo = self.w['topology']
        cur = topo.currentText()
        topo.blockSignals(True)
        topo.clear()
        topo.addItems(list(kinds.get(self.w['type'].currentText(), ())))
        if cur in kinds.get(self.w['type'].currentText(), ()):
            topo.setCurrentText(cur)
        topo.blockSignals(False)
        self._topology_changed()

    def _topology_changed(self, *_):
        """Only the details the type and topology use are enabled."""
        t, p = self.w['type'].currentText(), self.w['topology'].currentText()
        self.w['zhigh'].setEnabled(t == 'lowpass')
        self.w['zlow'].setEnabled(t == 'lowpass' and p == 'stepped')
        self.w['zstub'].setEnabled((t == 'lowpass' and p == 'stub') or p == 'interdigital')
        self.w['stub_angle'].setEnabled(t == 'lowpass' and p == 'radial')
        self.w['hairpin_gap'].setEnabled(t == 'bandpass' and p == 'hairpin')
        self.w['bw'].setPlaceholderText('2 x f0' if t == 'highpass' else ('' if t == 'lowpass' else 'e.g. 500M'))
        self.w['bw'].setEnabled(t != 'lowpass')

    def _substrate_changed(self, name):
        """The preset's values as the hints of its overrides."""
        if not self.desc:
            return
        pre = self.desc['presets'].get(name, {})
        h, er, td = pre.get('h'), pre.get('er'), pre.get('tand')
        for key, val in (('h', h), ('er', er), ('tand', td)):
            self.w[key].setPlaceholderText('' if val is None else f"{val:g} (preset)")

    def _browse(self):
        p, _ = QFileDialog.getSaveFileName(self, 'dfsynth output', self.w['out'].text() or os.getcwd(),
                                           'KiCad board (*.kicad_pcb)')
        if p:
            self.w['out'].setText(p[:-len('.kicad_pcb')] if p.endswith('.kicad_pcb') else p)

    def values(self):
        """The settings as dfsynth's values (empty fields: None, its defaults)."""
        out = {}
        for key, o in self.opts.items():
            w, kind = self.w.get(key), o['kind']
            if w is None:
                continue
            if isinstance(w, QCheckBox):
                out[key] = w.isChecked()
            elif isinstance(w, QSpinBox):
                out[key] = w.value() or None
            elif isinstance(w, QComboBox):
                out[key] = w.currentText().strip() or None
            else:
                t = w.text().strip()
                out[key] = (float(t) if kind == 'float' else int(t) if kind == 'int' else t) if t and w.isEnabled() else None
        return out

    def set_values(self, vals):
        for key, v in vals.items():
            w = self.w.get(key)
            if w is None:
                continue
            if isinstance(w, QCheckBox):
                w.setChecked(bool(v))
            elif isinstance(w, QSpinBox):
                w.setValue(int(v or 0))
            elif isinstance(w, QComboBox):
                if key == 'type':
                    w.setCurrentText(v)
                    self._type_changed()
                else:
                    w.setCurrentText('' if v is None else str(v))
            else:
                w.setText('' if v is None else f"{v:g}" if isinstance(v, float) else str(v))

    # ---- the views ----
    def _views(self):
        right = QSplitter(Qt.Vertical)
        top = QSplitter(Qt.Horizontal)
        self.layout_plot = pg.PlotWidget(title='Layout (mm)')
        self.layout_plot.setAspectLocked(True)
        self.layout_plot.invertY(True)                              # KiCad's y runs down
        self.layout_plot.showGrid(x=True, y=True, alpha=0.2)
        self.resp_plot = pg.PlotWidget(title='Response')
        self.resp_plot.setLabel('bottom', 'GHz')
        self.resp_plot.setLabel('left', 'dB')
        self.resp_plot.showGrid(x=True, y=True, alpha=0.3)
        self.resp_plot.addLegend(offset=(-10, 10))
        self.resp_plot.setYRange(-60, 2)
        top.addWidget(self.layout_plot)
        top.addWidget(self.resp_plot)
        right.addWidget(top)
        tabs = QTabWidget()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['element', 'Z (Ω)', 'width (mm)', 'length (mm)', 'gap (mm)'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        tabs.addTab(self.table, 'Dimensions')
        tabs.addTab(self.summary, 'Summary')
        tabs.addTab(self.log, 'Log')
        self.tabs = tabs
        right.addWidget(tabs)
        right.setSizes([520, 300])
        return right

    # ---- the log: everything dfsynth and the page say; problems in red, counted on the Log tab ----
    def say(self, text, level=None, first=True, count=True):
        """Text into the log; an 'error' or 'warn' in bold red, marked, counted on the tab (and an error brings
        the log forward). `first` False: the rest of a message already marked (and counted)."""
        for i, line in enumerate(str(text).splitlines() or ['']):
            if level is None:
                self.log.appendPlainText(line)
                continue
            col, mark = LEVELS[level]
            mark = mark if first and i == 0 else ' ' * len(mark)
            self.log.appendHtml(f'<span style="color:{col}; font-weight:bold; white-space:pre">'
                                f'{mark}{html.escape(line)}</span>')
        if level is not None and first and count:
            self.problems[level] += 1
        self.log.moveCursor(QTextCursor.End)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        self.log.setCurrentCharFormat(QTextCharFormat())                              # plain text stays plain
        self._mark_log()
        if level == 'error':
            self.tabs.setCurrentWidget(self.log)

    def _mark_log(self):
        e, w = self.problems['error'], self.problems['warn']
        i = self.tabs.indexOf(self.log)
        bar = self.tabs.tabBar()
        if not e + w:
            self.tabs.setTabText(i, 'Log')
            self.tabs.setTabIcon(i, QIcon())
            bar.setTabTextColor(i, QColor())
            return
        parts = ([f"{e} error{'s' * (e != 1)}"] if e else []) + ([f"{w} warning{'s' * (w != 1)}"] if w else [])
        self.tabs.setTabText(i, f"Log ({', '.join(parts)})")
        self.tabs.setTabIcon(i, self.style().standardIcon(QStyle.SP_MessageBoxCritical if e
                                                          else QStyle.SP_MessageBoxWarning))
        bar.setTabTextColor(i, QColor(LEVELS['error'][0]))

    def clear_log(self):
        self.log.clear()
        self.problems, self._last = {'error': 0, 'warn': 0}, None
        self._mark_log()

    def progress(self, text, ms=0):
        """Where a run is up to: the main window's status bar (and the log)."""
        if self.win is not None:
            self.win.statusBar().showMessage(text, ms)
        if self.proc is not None:
            self.busy.setToolTip(text.removeprefix('dfsynth: '))       # (a busy bar shows no text in most styles)

    def show_result(self, res):
        """A dfsynth run's design, layout and responses into the views."""
        self.result = res
        self.layout_plot.clear()
        self.resp_plot.clear()
        self.table.setRowCount(0)
        self.open_btn.setEnabled(bool(res) and os.path.exists(res['toml']))
        if not res:
            self.summary.clear()
            return
        d = res['design']
        geo = d.get('geometry') or {}
        path = QPainterPath()
        for poly in geo.get('polys', []):
            path.moveTo(*poly[0])
            for x, y in poly[1:]:
                path.lineTo(x, y)
            path.closeSubpath()
        it = QGraphicsPathItem(path)
        pen = QPen(COPPER.darker(130))
        pen.setCosmetic(True)
        it.setPen(pen)
        it.setBrush(QBrush(COPPER))
        self.layout_plot.addItem(it)
        drill = (geo.get('via_mm') or [0.3, 0.6])[0]
        for x, y in geo.get('vias', []):
            c = QGraphicsEllipseItem(x - drill / 2, y - drill / 2, drill, drill)
            c.setBrush(QBrush(VIA))
            c.setPen(QPen(Qt.NoPen))
            self.layout_plot.addItem(c)
        W, H = d.get('board_mm', [0, 0])
        self.layout_plot.plot([0, W, W, 0, 0], [0, 0, H, H, 0], pen=pg.mkPen('#888', width=1))
        for n, x, y, _ in geo.get('ports', []):
            t = pg.TextItem(f"P{n}", color='#c00', anchor=(0.5, 1.2))
            t.setPos(x, y)
            self.layout_plot.addItem(t)
            self.layout_plot.plot([x], [y], pen=None, symbol='o', symbolSize=6, symbolBrush='#c00')
        self.layout_plot.autoRange()
        # the responses: the line model, then each solver of the last validation round
        curves = []
        if res['model'] is not None:
            curves.append(('model', res['model'], '#000'))
        if res['em']:
            lab, files = res['em'][-1]
            for i, (solver, fs) in enumerate(files.items()):
                curves.append((f"{solver} ({lab})", fs, COLORS[i % len(COLORS)]))
        for name, (f, S), col in curves:
            self.resp_plot.plot(f / 1e9, _db(S[:, 1, 0]), pen=pg.mkPen(col, width=2), name=f"S21 {name}")
            self.resp_plot.plot(f / 1e9, _db(S[:, 0, 0]), pen=pg.mkPen(col, width=1, style=Qt.DashLine),
                                name=f"S11 {name}")
        for v in (d.get('targets_GHz') or {}).values():
            if v:
                self.resp_plot.addItem(pg.InfiniteLine(v, angle=90, pen=pg.mkPen('#2a2', style=Qt.DotLine)))
        self.resp_plot.setYRange(-60, 2)
        rows = d.get('elements', [])
        self.table.setRowCount(len(rows))
        for i, e in enumerate(rows):
            for j, k in enumerate(('name', 'z_ohm', 'width_mm', 'length_mm', 'gap_mm')):
                v = e.get(k)
                self.table.setItem(i, j, QTableWidgetItem('' if v in (None, '') else
                                                          f"{v:.3f}" if isinstance(v, float) else str(v)))
        self.summary.setPlainText(summary_text(d, notes=False))
        col, mark = LEVELS['warn']
        if d.get('notes'):
            self.summary.appendPlainText('')
        for n in d.get('notes') or []:                              # the design's warnings: red here as well
            self.summary.appendHtml(f'<span style="color:{col}; font-weight:bold; white-space:pre">'
                                    f'{mark}{html.escape(str(n))}</span>')
        self.summary.setCurrentCharFormat(QTextCharFormat())

    # ---- running dfsynth ----
    def start(self, validate):
        if self.proc is not None:
            return
        vals = self.values()
        if not vals.get('f0'):
            self.say('cannot design: set f0 first', 'error')
            return
        if not vals.get('out'):
            vals['out'] = os.path.join(os.getcwd(), 'filters', f"{vals['type']}_{vals['topology']}")
            self.w['out'].setText(vals['out'])
        if validate and not vals.get('validate'):
            self.say('cannot validate: choose the solvers for the validation', 'error')
            return
        self.base = os.path.abspath(vals['out'])
        os.makedirs(os.path.dirname(self.base), exist_ok=True)
        stale = [p for p in glob.glob(self.base + '_em*') if re.fullmatch(r'_em(_tune\d+)?', p[len(self.base):])]
        for p in [self.base + '_design.json'] + stale:               # no stale results on the page
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.isfile(p):
                os.remove(p)
        self.clear_log()
        self.tabs.setCurrentWidget(self.log)
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.setWorkingDirectory(os.path.dirname(self.base))
        self.proc.readyReadStandardOutput.connect(self._stdout)
        self.proc.finished.connect(self._finished)
        argv = filter_argv(vals, validate)
        self.say('$ dfsynth ' + ' '.join(argv[3:]))
        self.proc.start(sys.executable, argv)
        self.progress('dfsynth: designing…' if not validate else
                      'dfsynth: designing, then validating on ' + vals['validate'])
        for b in (self.design_btn, self.validate_btn):
            b.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.busy.show()

    def stop(self):
        """Asks a kicad2ems run dfsynth started to stop (the STOP file its solvers check), and ends dfsynth."""
        if self.proc is not None:
            if self.base:
                from .runner import stop_runs
                for d in glob.glob(self.base + '_em*'):
                    if os.path.isdir(d):
                        stop_runs(d)
            self.proc.kill()

    def _stdout(self):
        data = bytes(self.proc.readAllStandardOutput()).decode('utf-8', 'replace')
        for line in data.splitlines():
            prev, self._last = self._last, line_level(line, self._last)
            self.say(line, self._last, first=not (self._last == 'error' == prev))     # an error's lines: one
            s = line.strip()
            if s.startswith('kicad2ems (') or s.startswith('calibration ') or s.startswith('refine'):
                self.progress('dfsynth: ' + s.rstrip(':'))
                self._stage = s.rstrip(':')
            elif PROGRESS.match(line) or s == 'solving...':           # a solver's progress (validate.Follow)
                self.progress(f"dfsynth: {getattr(self, '_stage', 'validating')}: {s}")

    def _finished(self, code, _status):
        self._stdout()
        self.proc = None
        for b in (self.design_btn, self.validate_btn):
            b.setEnabled(self.desc is not None)
        self.stop_btn.setEnabled(False)
        self.busy.hide()
        res = load_design(self.base) if self.base else None
        self.show_result(res)
        if code == 2:
            self.say('dfsynth refused the design (fabrication limits, or the spec): see above', 'error', count=False)
        elif code:
            self.say(f"dfsynth ended with code {code}: see above", 'error', count=not self.problems['error'])
        else:
            done = f"done: {os.path.basename(self.base)}.kicad_pcb in {os.path.dirname(self.base)}"
            self.say(done)
            w = self.problems['warn']
            self.progress(done + (f" ({w} warning{'s' * (w != 1)}: see the log)" if w else ''), 0 if w else 10000)
            self.tabs.setCurrentWidget(self.log if w else self.summary)
            return
        self.progress('dfsynth failed: see the Filter Synthesis log')

    def open_in_kicad2ems(self):
        """The board's config in the main window's settings (which previews it)."""
        if self.result and self.win is not None and os.path.exists(self.result['toml']):
            self.win._open(self.result['toml'])


def summary_text(d, notes=True):
    """The design JSON as text: the spec, the calibration, the line model's and each validation round's figures."""
    sp, sub = d.get('spec', {}), d.get('substrate', {})
    lines = [f"{sp.get('kind')} / {sp.get('topology')}: {sp.get('response')}, order {sp.get('order')}, "
             f"f0 {sp.get('f0', 0) / 1e9:.4g} GHz" + (f", bandwidth {sp['bw'] / 1e6:.4g} MHz" if sp.get('bw') else ''),
             f"substrate {sub.get('name')}: h {sub.get('h')} mm, εr {sub.get('er')}, tan δ {sub.get('tand')}, "
             f"limits {sub.get('min_width')} / {sub.get('min_gap')} mm",
             f"kf {d.get('kf', 1):.4f}, kb {d.get('kb', 1):.4f} (the board as written: calibrated, then tuned);  board "
             + ' x '.join(f"{x:.2f}" for x in d.get('board_mm', [])) + ' mm', '']

    def fig(m):
        pct = lambda v: 'n/a' if v is None else f"{v:+.2f} %"
        s = f"centre {pct(m.get('centre_error_pct'))}  bw {pct(m.get('bandwidth_error_pct'))}"
        if m.get('passband_IL_dB') is not None:
            s += f"  IL {m['passband_IL_dB']:.2f} dB"
        if m.get('passband_RL_worst_dB') is not None:
            s += f"  RL {m['passband_RL_worst_dB']:.1f} dB"
        if m.get('own_passband_RL_worst_dB') is not None:
            s += f" (own band {m['own_passband_RL_worst_dB']:.1f})"
        return s
    if d.get('model'):
        lines.append(f"line model:  {fig(d['model'])}")
    for i, r in enumerate(d.get('em', [])):
        lines.append(f"\nvalidation round {i} (kf {r.get('kf', 1):.4f}, kb {r.get('kb', 1):.4f}):")
        for name, m in (r.get('metrics') or {}).items():
            lines.append(f"  {name:18s} {fig(m)}")
    if notes and d.get('notes'):
        lines += [''] + [f"note: {n}" for n in d['notes']]
    return '\n'.join(lines)
