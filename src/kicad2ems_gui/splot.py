"""
The Results page's plots (pyqtgraph): S-parameters and antenna results as a grid of subplots you add (Add plot)
and close (x on each), laid out in as many columns as the width allows.

    Cartesian  over frequency: |S| dB or linear, phase, group delay, VSWR; with antenna results also gain /
               directivity / realized gain and the radiation efficiency
    Smith      the reflections (S11, S22, ...) with an impedance readout
    Polar      S in polar form (|S| and angle), or the far-field cuts (xz, yz, xy) at a recorded frequency

The traces (one tree: openEMS, mom25d, the line model, a compare file, added folders) are shared by every plot.
The mouse reads every plot at a frequency; a click drops a marker on all of them (drag a marker line to move
it, Delete in the table to remove it). Export CSV and Save image take what is shown.
"""
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QComboBox, QPushButton, QLabel,
                               QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, QSplitter, QFileDialog,
                               QMessageBox, QHeaderView, QAbstractItemView, QToolButton, QMenu, QFrame, QScrollArea,
                               QSizePolicy)
import pyqtgraph as pg
from .panels import FlowLayout
from .traces import (KINDS, SMITH, transform, value_at, fmt_value, nearest, smith_grid, polar_grid, pattern_xy,
                     export_csv, default_visible)

# a colour per trace (tab10, then darker ones), a line style per source; both changeable from the trace list
COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
          '#393b79', '#e6550d', '#31a354', '#843c39', '#7b4173', '#3182bd', '#8c6d31', '#637939', '#ad494a', '#636363']
STYLES = dict(solid=Qt.SolidLine, dash=Qt.DashLine, dot=Qt.DotLine, dashdot=Qt.DashDotLine,
              dashdotdot=Qt.DashDotDotLine)
STYLE_NAMES = dict(solid='solid', dash='dashed', dot='dotted', dashdot='dash-dot', dashdotdot='dash-dot-dot')
WIDTHS = (1, 2, 3, 4)
LOOKS_KEY = 'results/trace_looks'                                  # QSettings: the user's colours and styles
CARTESIAN, SMITH_PLOT, POLAR = 'Cartesian', 'Smith', 'Polar'
TYPES = (CARTESIAN, SMITH_PLOT, POLAR)
ANT_KINDS = ('Gain (dBi)', 'Efficiency (%)')                       # Cartesian, with antenna results
S_POLAR, FAR_CUTS = 'S (polar)', 'Far-field cuts'
PATTERN_QTY = ('Gain (dBi)', 'Realized gain (dBi)', 'Directivity (dBi)')
RANGE_DB = 30.0
MIN_COL_WIDTH = 430                                                 # a column of plots needs this many pixels
MIN_PLOT_HEIGHT = 240


def default_layout(antenna=False):
    """The subplots a page starts with: |S| and the Smith chart; for an antenna also its gain and pattern."""
    if antenna:
        return [f"{CARTESIAN}:{KINDS[0]}", f"{CARTESIAN}:{ANT_KINDS[0]}", f"{POLAR}:{FAR_CUTS}", SMITH_PLOT]
    return [f"{CARTESIAN}:{KINDS[0]}", SMITH_PLOT]


class Subplot(QFrame):
    """One plot of the grid: a header (its type, what it shows, close) and a pyqtgraph plot."""
    def __init__(self, host, kind, option=None):
        super().__init__()
        self.host, self.kind = host, kind
        self.wanted = option                                        # what was asked for: back once it exists
        self.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 4)
        lay.setSpacing(2)
        head = QHBoxLayout()
        head.addWidget(QLabel(f"<b>{kind}</b>"))
        self.option = QComboBox()
        self.option.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        head.addWidget(self.option)
        self.freq = QComboBox()                                     # the far-field cuts' frequency and quantity
        self.qty = QComboBox()
        self.qty.addItems(PATTERN_QTY)
        for w in (self.freq, self.qty):
            w.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            head.addWidget(w)
        head.addStretch(1)
        close = QToolButton()
        close.setText('✕')
        close.setAutoRaise(True)
        close.setToolTip('Remove this plot')
        close.clicked.connect(lambda: host.remove_subplot(self))
        head.addWidget(close)
        lay.addLayout(head)
        self.pw = pg.PlotWidget()
        self.pw.setMinimumHeight(MIN_PLOT_HEIGHT - 40)
        self.pw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.pw, 1)
        self.legend = self.pw.addLegend(offset=(-10, 10) if kind == CARTESIAN else (5, 5))
        if kind == CARTESIAN:
            self.pw.showGrid(x=True, y=True, alpha=0.3)
            self.pw.setLabel('bottom', 'frequency (GHz)')
        else:
            self.pw.setAspectLocked(True)
            self.pw.hideAxis('left')
            self.pw.hideAxis('bottom')
        self.cursor = pg.InfiniteLine(angle=90, pen=pg.mkPen('#888', width=1, style=Qt.DotLine))
        self.dot = pg.ScatterPlotItem(size=9, pen=pg.mkPen('k'), brush=pg.mkBrush(255, 255, 255, 180))
        self.fill_options()
        self.option.currentIndexChanged.connect(self._option_changed)
        self.freq.currentIndexChanged.connect(lambda *_: host.redraw())
        self.qty.currentIndexChanged.connect(lambda *_: host.redraw())
        self.pw.scene().sigMouseMoved.connect(lambda pos: host._moved(self, pos))
        self.pw.scene().sigMouseClicked.connect(lambda ev: host._clicked(self, ev))
        self._fit_head()

    def fill_options(self):
        """What this plot can show, for what the page has (antenna quantities only with antenna results)."""
        keep = self.option.currentText()
        self.option.blockSignals(True)
        self.option.clear()
        if self.kind == CARTESIAN:
            self.option.addItems(list(KINDS) + (list(ANT_KINDS) if self.host.antenna else []))
        elif self.kind == POLAR:
            self.option.addItems([S_POLAR] + ([FAR_CUTS] if self.host.sphere is not None else []))
        for pick in (self.wanted, keep):
            if pick and self.option.findText(pick) >= 0:
                self.option.setCurrentText(pick)
                break
        self.option.blockSignals(False)
        self.option.setVisible(self.kind != SMITH_PLOT)
        sph = self.host.sphere
        keep = self.freq.currentIndex()
        self.freq.blockSignals(True)
        self.freq.clear()
        if sph is not None:
            self.freq.addItems([f"{f / 1e9:.4g} GHz" for f in sph['freq']])
            f0 = (self.host.antenna or {}).get('f_pattern', sph['freq'][0])
            pick = keep if 0 <= keep < len(sph['freq']) else int(np.argmin(np.abs(sph['freq'] - f0)))
            self.freq.setCurrentIndex(pick)
        self.freq.blockSignals(False)
        self._fit_head()

    def _fit_head(self):
        far = self.mode == FAR_CUTS
        self.freq.setVisible(far)
        self.qty.setVisible(far)

    def _option_changed(self, *_):
        self.wanted = self.option.currentText()
        self._fit_head()
        self.host.redraw()
        self.host.layout_changed.emit()

    @property
    def mode(self):
        return self.option.currentText() if self.kind != SMITH_PLOT else SMITH_PLOT

    @property
    def on_frequency(self):
        """A plot over frequency (cursor line, marker lines)."""
        return self.kind == CARTESIAN

    @property
    def s_kind(self):
        """The S-parameter quantity of a Cartesian plot, else None."""
        return self.mode if self.kind == CARTESIAN and self.mode in KINDS else None

    @property
    def complex_plane(self):
        """A plot of complex S (Smith, polar S): markers and the cursor are points on its traces."""
        return self.kind == SMITH_PLOT or (self.kind == POLAR and self.mode == S_POLAR)

    def spec(self):
        """What the window remembers: the kind and what it was asked to show (a plot of the gain stays one while
        a folder without antenna results shows |S| in it)."""
        return self.kind if self.kind == SMITH_PLOT else f"{self.kind}:{self.wanted or self.mode}"


class SPlot(QWidget):
    layout_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.traces, self.markers, self.subplots = [], [], []
        self.z0, self.antenna, self.sphere = 50.0, None, None
        self._cols, self._moving = 0, False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = FlowLayout()                                          # wraps when the page is narrow
        add = QToolButton()
        add.setText('Add plot')
        add.setPopupMode(QToolButton.InstantPopup)
        add.setToolButtonStyle(Qt.ToolButtonTextOnly)
        menu = QMenu(add)
        for kind, tip in ((CARTESIAN, 'over frequency'), (SMITH_PLOT, 'the reflections'),
                          (POLAR, 'S in polar form, or the far-field cuts')):
            a = menu.addAction(f"{kind}: {tip}")
            a.triggered.connect(lambda _=False, k=kind: self.add_subplot(k))
        add.setMenu(menu)
        bar.addWidget(add)
        for text, slot, tip in (('Fit', self.fit, 'Zoom every plot to what it shows'),
                                ('Clear markers', self.clear_markers, 'Remove every marker (or select one and press Delete)'),
                                ('Export CSV…', self.export_csv, 'The shown traces as the first plot shows them'),
                                ('Save image…', self.save_image, 'Every plot as one PNG')):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch(1)
        hint = QLabel('click: marker · drag a marker to move it · wheel / drag: zoom, pan')
        hint.setStyleSheet('color: gray')
        bar.addWidget(hint)
        lay.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(150)
        self.tree.itemChanged.connect(lambda *_: self.redraw())
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.setToolTip('right-click a trace (or a source) for its colour, line style and width')
        self.looks = self._load_looks()                             # 'source|S21' -> {color, style, width}
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(4)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.grid_host)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.readout = QLabel(' ')
        self.readout.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.readout.setWordWrap(True)
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setMaximumHeight(150)
        self.table.keyPressEvent = self._table_key
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.scroll, 1)
        rl.addWidget(self.readout)
        rl.addWidget(self.table)
        self.split = QSplitter()
        self.split.setObjectName('results')
        self.split.addWidget(self.tree)
        self.split.addWidget(right)
        self.split.setStretchFactor(1, 4)
        self.split.setCollapsible(1, False)
        self.split.setSizes([220, 1000])
        lay.addWidget(self.split, 1)
        self.set_layout(default_layout())

    # ---- the subplots ----
    def add_subplot(self, kind, option=None, redraw=True):
        sp = Subplot(self, kind, option)
        self.subplots.append(sp)
        self._reflow(force=True)
        if redraw:
            self.redraw()
            self._fit_one(sp)
            self.layout_changed.emit()
        return sp

    def remove_subplot(self, sp):
        if sp not in self.subplots:
            return
        self.subplots.remove(sp)
        for m in self.markers:
            m['items'].pop(id(sp), None)
        self.grid.removeWidget(sp)
        sp.setParent(None)
        sp.deleteLater()
        self._reflow(force=True)
        self._update_table()
        self.layout_changed.emit()

    def layout_spec(self):
        """The subplots as strings (Cartesian:|S| (dB), Smith, Polar:Far-field cuts): what the window remembers."""
        return [sp.spec() for sp in self.subplots]

    def set_layout(self, spec):
        """Replace the subplots by these (layout_spec strings); unknown entries are skipped."""
        for sp in list(self.subplots):
            self.subplots.remove(sp)
            self.grid.removeWidget(sp)
            sp.setParent(None)
            sp.deleteLater()
        for m in self.markers:
            m['items'] = {}
        for s in spec or []:
            kind, _, opt = str(s).partition(':')
            if kind in TYPES:
                self.add_subplot(kind, opt or None, redraw=False)
        if not self.subplots:
            for s in default_layout(bool(self.antenna)):
                kind, _, opt = s.partition(':')
                self.add_subplot(kind, opt or None, redraw=False)
        self.redraw()
        self.fit()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._reflow()

    def _reflow(self, force=False):
        """As many columns as the width allows (at least MIN_COL_WIDTH each), the plots row by row."""
        n = len(self.subplots)
        width = max(self.scroll.viewport().width(), 1)
        cols = max(1, min(n, width // MIN_COL_WIDTH, 3)) if n else 1
        if cols == self._cols and not force:
            return
        self._cols = cols
        for sp in self.subplots:
            self.grid.removeWidget(sp)
        for k, sp in enumerate(self.subplots):
            self.grid.addWidget(sp, k // cols, k % cols)
        rows = (n + cols - 1) // cols
        for r in range(max(rows, self.grid.rowCount())):
            self.grid.setRowStretch(r, 1 if r < rows else 0)
        for c in range(max(cols, self.grid.columnCount())):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)
        self.grid_host.setMinimumHeight(rows * MIN_PLOT_HEIGHT)

    # ---- data ----
    def set_traces(self, traces, z0=50.0):
        """Show these traces (a new run): keeps the plots and the markers' frequencies."""
        self.traces, self.z0 = list(traces), z0
        self.tree.blockSignals(True)
        self.tree.clear()
        groups = {}
        for k, t in enumerate(self.traces):
            if t.source not in groups:
                g = QTreeWidgetItem([t.source])
                g.setFlags(g.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
                self.tree.addTopLevelItem(g)
                groups[t.source] = g
            it = QTreeWidgetItem([t.title])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked if default_visible(t) else Qt.Unchecked)
            it.setData(0, Qt.UserRole, k)
            it.setToolTip(0, t.path or '')
            if t.empty:
                it.setDisabled(True)
                it.setToolTip(0, 'not computed (port not excited)')
            groups[t.source].addChild(it)
        self.tree.expandAll()
        self._swatches()
        self.tree.blockSignals(False)
        self.redraw()
        self.fit()

    def set_antenna(self, res=None, sphere=None):
        """Antenna results (the run's <name>_antenna.json as a dict) and its far-field sphere, or None: the
        Cartesian plots offer gain and efficiency, the polar plots the far-field cuts."""
        self.antenna, self.sphere = res, sphere
        for sp in self.subplots:
            sp.fill_options()
        self.redraw()

    def update_antenna(self, res, sphere):
        """New antenna results of the same run (a steered drive): the antenna plots redrawn, the rest kept."""
        self.antenna, self.sphere = res, sphere
        for sp in self.subplots:
            if sp.mode in ANT_KINDS or sp.mode == FAR_CUTS:
                self._draw(sp)

    def visible(self):
        """The checked traces."""
        out = []
        for g in range(self.tree.topLevelItemCount()):
            grp = self.tree.topLevelItem(g)
            for c in range(grp.childCount()):
                it = grp.child(c)
                if it.checkState(0) == Qt.Checked and not it.isDisabled():
                    out.append(self.traces[it.data(0, Qt.UserRole)])
        return out

    def reflections(self):
        """The checked reflections (what a Smith chart shows)."""
        return [t for t in self.visible() if t.i == t.j]

    def _plane_traces(self, sp):
        """The traces a complex-plane plot shows: a Smith chart the reflections, a polar plot every checked one."""
        return self.reflections() if sp.kind == SMITH_PLOT else self.visible()

    @property
    def kind(self):
        """The quantity box of the first Cartesian plot (one is added if there is none)."""
        sp = next((s for s in self.subplots if s.kind == CARTESIAN), None) or self.add_subplot(CARTESIAN)
        return sp.option

    def s_kinds(self):
        """The S-parameter quantities the Cartesian plots show, in order, each once."""
        return list(dict.fromkeys(sp.s_kind for sp in self.subplots if sp.s_kind))

    # ---- how each trace looks: a colour each, a style per source, the user's choices over both ----
    @staticmethod
    def look_key(t):
        return f"{t.source}|{t.param}"

    def look(self, t):
        """(colour, style name, width) of a trace: its own colour (by its place in the list), its source's line
        style (the sources in order: solid, dashed, dotted, ...), then what the user chose."""
        k = next((n for n, x in enumerate(self.traces) if x is t), 0)
        sources = list(dict.fromkeys(x.source for x in self.traces))
        si = sources.index(t.source) if t.source in sources else 0
        auto = dict(color=COLORS[k % len(COLORS)], style=list(STYLES)[si % len(STYLES)], width=2)
        auto.update(self.looks.get(self.look_key(t), {}))
        return auto['color'], auto['style'] if auto['style'] in STYLES else 'solid', int(auto['width'])

    def _color(self, t):
        return self.look(t)[0]

    def _pen(self, t):
        c, st, w = self.look(t)
        return pg.mkPen(c, width=w, style=STYLES[st])

    def _load_looks(self):
        from PySide6.QtCore import QSettings
        import json
        try:
            v = QSettings('kicad2ems', 'gui').value(LOOKS_KEY)
            d = json.loads(v) if v else {}
            return d if isinstance(d, dict) else {}
        except (ValueError, TypeError):
            return {}

    def _save_looks(self):
        from PySide6.QtCore import QSettings
        import json
        QSettings('kicad2ems', 'gui').setValue(LOOKS_KEY, json.dumps(self.looks))

    def set_look(self, traces, **kw):
        """The user's colour / style / width for these traces (kw None: back to the automatic one)."""
        for t in traces:
            d = self.looks.setdefault(self.look_key(t), {})
            for k, v in kw.items():
                if v is None:
                    d.pop(k, None)
                else:
                    d[k] = v
            if not d:
                self.looks.pop(self.look_key(t), None)
        self._save_looks()
        self._swatches()
        self.redraw()

    def _swatches(self):
        """Each trace's line, as it is drawn, beside its name in the list."""
        from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QIcon
        for g in range(self.tree.topLevelItemCount()):
            grp = self.tree.topLevelItem(g)
            for c in range(grp.childCount()):
                it = grp.child(c)
                t = self.traces[it.data(0, Qt.UserRole)]
                col, st, w = self.look(t)
                pm = QPixmap(28, 12)
                pm.fill(Qt.transparent)
                p = QPainter(pm)
                p.setPen(QPen(QColor(col), w, STYLES[st]))
                p.drawLine(1, 6, 27, 6)
                p.end()
                it.setIcon(0, QIcon(pm))

    def _tree_menu(self, pos):
        """Right-click on a trace (or a source: all of its traces): colour, line style, width, automatic."""
        from PySide6.QtWidgets import QColorDialog
        from PySide6.QtGui import QColor
        it = self.tree.itemAt(pos)
        if it is None:
            return
        idx = [it.child(c).data(0, Qt.UserRole) for c in range(it.childCount())] if it.childCount() else \
            [it.data(0, Qt.UserRole)]
        ts = [self.traces[i] for i in idx if i is not None]
        if not ts:
            return
        menu = QMenu(self)
        if len(ts) == 1:
            menu.addAction('Colour…').triggered.connect(lambda: (
                lambda c: c.isValid() and self.set_look(ts, color=c.name()))(
                QColorDialog.getColor(QColor(self.look(ts[0])[0]), self, f"Colour of {ts[0].label}")))
        sm = menu.addMenu('Line style')
        for key, name in STYLE_NAMES.items():
            a = sm.addAction(name)
            a.setCheckable(True)
            a.setChecked(all(self.look(t)[1] == key for t in ts))
            a.triggered.connect(lambda _=False, k=key: self.set_look(ts, style=k))
        wm = menu.addMenu('Width')
        for w in WIDTHS:
            a = wm.addAction(f"{w} px")
            a.setCheckable(True)
            a.setChecked(all(self.look(t)[2] == w for t in ts))
            a.triggered.connect(lambda _=False, v=w: self.set_look(ts, width=v))
        menu.addSeparator()
        menu.addAction('Automatic colour and style').triggered.connect(
            lambda: self.set_look(ts, color=None, style=None, width=None))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ---- drawing ----
    def redraw(self):
        for sp in self.subplots:
            self._draw(sp)
        for m in self.markers:
            self._place_marker(m)
        self._update_table()

    def _draw(self, sp):
        pw = sp.pw
        pw.clear()
        pw.setTitle(None)
        if sp.legend is not None:
            sp.legend.clear()
        mode = sp.mode
        if sp.kind == CARTESIAN and mode in KINDS:
            pw.setLabel('left', mode)
            for t in self.visible():
                x, y = transform(mode, t)
                pw.plot(x, y, pen=self._pen(t), name=t.label)
        elif sp.kind == CARTESIAN:
            pw.setLabel('left', mode)
            rows = (self.antenna or {}).get('rows') or []
            fr = np.array([r['f'] for r in rows]) / 1e9
            if mode == ANT_KINDS[0]:
                for key, name, color in (('D_dbi', 'directivity', '#2ca02c'), ('G_dbi', 'gain', '#1f77b4'),
                                         ('Grealized_dbi', 'realized gain', '#d62728')):
                    y = np.array([np.nan if r.get(key) is None else r[key] for r in rows], float)
                    pw.plot(fr, y, pen=pg.mkPen(color, width=2), symbol='o', symbolSize=4, symbolBrush=color,
                            name=name)
            else:
                pw.plot(fr, [100 * r['eff'] for r in rows], pen=pg.mkPen('#9467bd', width=2), symbol='o',
                        symbolSize=4, symbolBrush='#9467bd', name='radiation efficiency')
        elif sp.complex_plane:
            grid = smith_grid() if sp.kind == SMITH_PLOT else polar_grid()
            for x, y in grid:
                pw.plot(x, y, pen=pg.mkPen('#cccccc', width=1))
            if sp.kind == SMITH_PLOT:
                for r in (0.2, 0.5, 1, 2, 5):                        # resistance labels on the real axis
                    lab = pg.TextItem(f"{r:g}", color='#999999', anchor=(1.1, 0))
                    lab.setPos((r - 1) / (r + 1), 0)
                    pw.addItem(lab)
            else:
                for r in (0.25, 0.5, 0.75, 1.0):
                    lab = pg.TextItem(f"{r:g}", color='#999999', anchor=(0, 1))
                    lab.setPos(r * 0.707, r * 0.707)
                    pw.addItem(lab)
            for t in self._plane_traces(sp):
                pw.plot(t.s.real, t.s.imag, pen=self._pen(t))
        else:                                                       # the far-field cuts
            self._draw_cuts(sp)
        if sp.on_frequency:
            pw.addItem(sp.cursor, ignoreBounds=True)
        if sp.on_frequency or sp.complex_plane:
            pw.addItem(sp.dot)
            sp.dot.setData([], [])

    def _draw_cuts(self, sp):
        from kicad2ems.api.frontend import sphere_cuts, sphere_gain
        pw, sph, res = sp.pw, self.sphere, self.antenna
        if sph is None or res is None or sp.freq.currentIndex() < 0:
            return
        i = sp.freq.currentIndex()
        f = float(sph['freq'][i])
        r = min(res['rows'], key=lambda row: abs(row['f'] - f))
        q = sp.qty.currentIndex()
        scale = (r['eff'], r['Prad'] / r['Pinc'] if r.get('Pinc') else np.nan, 1.0)[q]
        g = sphere_gain(sph, i, scale)
        peak = float(10 * np.log10(max(g.max(), 1e-12)))
        top = np.ceil(peak / 5) * 5
        lo = top - RANGE_DB
        rings = [k / 6 for k in range(1, 7)]
        for x, y in polar_grid(rings):
            pw.plot(x, y, pen=pg.mkPen('#cccccc', width=1))
        for k, rr in enumerate(rings):
            if k % 2 == 1:
                lab = pg.TextItem(f"{lo + rr * RANGE_DB:.0f}", color='#999999', anchor=(0.5, 1))
                lab.setPos(0, rr)
                pw.addItem(lab)
        for name, (ang, gg) in sphere_cuts(sph, g).items():
            x, y = pattern_xy(ang, gg, lo, RANGE_DB)
            color = {'xz': '#1f77b4', 'yz': '#d62728', 'xy': '#2ca02c'}[name[:2]]
            pw.plot(x, y, pen=pg.mkPen(color, width=2), name=name)
        pw.setTitle(f"{PATTERN_QTY[q]} at {f / 1e9:.4g} GHz, peak {peak:.2f} dBi", size='9pt')
        pw.setRange(xRange=(-1.05, 1.05), yRange=(-1.05, 1.05), padding=0.02)

    def fit(self):
        for sp in self.subplots:
            self._fit_one(sp)

    def _fit_one(self, sp):
        if sp.kind == CARTESIAN:
            sp.pw.enableAutoRange()
        else:
            sp.pw.setRange(xRange=(-1.05, 1.05), yRange=(-1.05, 1.05), padding=0.02)

    # ---- the cursor ----
    def _moved(self, sp, pos):
        if not sp.pw.sceneBoundingRect().contains(pos):
            return
        p = sp.pw.getPlotItem().vb.mapSceneToView(pos)
        if sp.on_frequency:
            self._show_at(p.x() * 1e9, src=sp)
        elif sp.complex_plane:
            trs = self._plane_traces(sp)
            if trs:
                t, k = nearest(trs, p.x(), p.y())
                self._show_at(float(t.f[k]), head=f"nearest: {t.label} &nbsp; ")

    def _show_at(self, f, head='', src=None):
        """Every plot at frequency f (Hz): the cursor lines, the dots, the readout."""
        trs = self.visible()
        kinds = self.s_kinds()
        kind = src.s_kind if src is not None and src.s_kind else (kinds[0] if kinds else KINDS[0])
        for sp in self.subplots:
            if sp.on_frequency:
                sp.cursor.setPos(f / 1e9)
                if sp.s_kind:
                    sp.dot.setData([f / 1e9] * len(trs), [value_at(sp.s_kind, t, f) for t in trs])
                else:
                    sp.dot.setData([], [])
            elif sp.complex_plane:
                g = [value_at(SMITH, t, f) for t in self._plane_traces(sp)]
                sp.dot.setData([v.real for v in g], [v.imag for v in g])
        parts = [f"<span style='color:{self._color(t)}'>{t.label}</span> {fmt_value(kind, value_at(kind, t, f))}"
                 for t in trs]
        if any(sp.kind == SMITH_PLOT for sp in self.subplots):
            parts += [f"<span style='color:{self._color(t)}'>{t.param} {t.source}</span> Z "
                      + fmt_value(SMITH, v, self.z0).split('Z ')[-1]
                      for t in self.reflections() for v in [value_at(SMITH, t, f)] if np.isfinite(v)]
        self.readout.setText(f"{head}<b>{f / 1e9:.4f} GHz</b> &nbsp; " + ' &nbsp; '.join(parts))

    # ---- markers ----
    def _snap(self, f):
        trs = self.visible()
        if not trs:
            return f
        grid = trs[0].f
        return float(grid[np.argmin(np.abs(grid - f))])             # on a computed frequency

    def _clicked(self, sp, ev):
        if ev.button() != Qt.LeftButton or ev.double():
            return
        if not sp.pw.sceneBoundingRect().contains(ev.scenePos()):
            return
        p = sp.pw.getPlotItem().vb.mapSceneToView(ev.scenePos())
        if sp.on_frequency and (self.visible() or self.antenna):
            self.add_marker(self._snap(p.x() * 1e9))
        elif sp.complex_plane and self._plane_traces(sp):
            t, k = nearest(self._plane_traces(sp), p.x(), p.y())
            self.add_marker(float(t.f[k]))

    def add_marker(self, f):
        m = dict(f=f, name=f"M{1 + max([int(x['name'][1:]) for x in self.markers] or [0])}", items={})
        self.markers.append(m)
        self._place_marker(m)
        self._update_table()
        return m

    def _place_marker(self, m):
        """The marker on every plot: a movable line over frequency, points on the complex-plane plots."""
        m['items'] = {}
        for sp in self.subplots:
            if sp.on_frequency:
                line = pg.InfiniteLine(pos=m['f'] / 1e9, angle=90, movable=True,
                                       pen=pg.mkPen('#444', width=1, style=Qt.DashLine), label=m['name'],
                                       labelOpts=dict(position=0.95, color='k', fill=(255, 255, 255, 200)))
                line.sigPositionChanged.connect(lambda ln, m=m: self._marker_moved(m, ln))
                sp.pw.addItem(line, ignoreBounds=True)
                m['items'][id(sp)] = (line,)
            elif sp.complex_plane:
                sc = pg.ScatterPlotItem(size=10, symbol='d', pen=pg.mkPen('k'), brush=pg.mkBrush('#ffd700'))
                txt = pg.TextItem(m['name'], color='k', anchor=(-0.2, 1))
                sp.pw.addItem(sc)
                sp.pw.addItem(txt)
                m['items'][id(sp)] = (sc, txt)
        self._move_plane_markers(m)

    def _move_plane_markers(self, m):
        for sp in self.subplots:
            it = m['items'].get(id(sp))
            if not it or not sp.complex_plane:
                continue
            sc, txt = it
            g = [v for v in (value_at(SMITH, t, m['f']) for t in self._plane_traces(sp)) if np.isfinite(v)]
            sc.setData([v.real for v in g], [v.imag for v in g])
            txt.setVisible(bool(g))
            if g:
                txt.setPos(g[0].real, g[0].imag)

    def _marker_moved(self, m, line):
        if self._moving:
            return
        self._moving = True
        try:
            m['f'] = line.value() * 1e9
            for sp in self.subplots:                                # the same marker on the other plots
                it = m['items'].get(id(sp))
                if it and sp.on_frequency and it[0] is not line:
                    it[0].setValue(m['f'] / 1e9)
            self._move_plane_markers(m)
            self._update_table()
        finally:
            self._moving = False

    def clear_markers(self):
        self.markers = []
        self.redraw()

    def _table_key(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
                if r < len(self.markers):
                    del self.markers[r]
            self.redraw()
        else:
            QTableWidget.keyPressEvent(self.table, ev)

    def _ant_value(self, key, f):
        rows = (self.antenna or {}).get('rows') or []
        fr = np.array([r['f'] for r in rows])
        y = np.array([np.nan if r.get(key) is None else r[key] for r in rows], float)
        if len(fr) < 1 or f < fr.min() or f > fr.max():
            return np.nan
        return float(np.interp(f, fr, y))

    def _columns(self):
        """The table's columns: (title, value at f) for every S quantity a Cartesian plot shows and every checked
        trace, the Smith chart's reflections, and the antenna's gain / efficiency when a plot shows them."""
        trs, cols = self.visible(), []
        for k in self.s_kinds():
            cols += [(t.label if len(self.s_kinds()) == 1 else f"{t.label} {k}",
                      lambda f, t=t, k=k: fmt_value(k, value_at(k, t, f), self.z0)) for t in trs]
        if any(sp.kind == SMITH_PLOT for sp in self.subplots):
            cols += [(f"{t.label} (Smith)", lambda f, t=t: fmt_value(SMITH, value_at(SMITH, t, f), self.z0))
                     for t in self.reflections()]
        modes = {sp.mode for sp in self.subplots if sp.kind == CARTESIAN}
        if self.antenna and ANT_KINDS[0] in modes:
            cols += [(name, lambda f, k=key: f"{self._ant_value(k, f):.2f} dBi")
                     for key, name in (('G_dbi', 'gain'), ('D_dbi', 'directivity'))]
        if self.antenna and ANT_KINDS[1] in modes:
            cols += [('efficiency', lambda f: f"{100 * self._ant_value('eff', f):.1f} %")]
        return cols

    def _update_table(self):
        cols = self._columns()
        self.table.setColumnCount(1 + len(cols))
        self.table.setHorizontalHeaderLabels(['f (GHz)'] + [c for c, _ in cols])
        self.table.setRowCount(len(self.markers))
        self.table.setVerticalHeaderLabels([m['name'] for m in self.markers])
        for r, m in enumerate(self.markers):
            self.table.setItem(r, 0, QTableWidgetItem(f"{m['f'] / 1e9:.4f}"))
            for c, (_, val) in enumerate(cols):
                self.table.setItem(r, 1 + c, QTableWidgetItem(val(m['f'])))
        self.table.setVisible(bool(self.markers))
        if self.markers:                                            # as tall as its rows, up to five of them
            rows = min(len(self.markers), 5)
            h = self.table.horizontalHeader().height() + rows * self.table.verticalHeader().defaultSectionSize()
            sb = self.table.horizontalScrollBar().sizeHint().height() if self.table.horizontalScrollBar().isVisible() else 0
            self.table.setFixedHeight(h + sb + 2 * self.table.frameWidth() + 2)

    # ---- export ----
    def export_csv(self, path=None):
        trs = self.visible()
        if not trs:
            QMessageBox.information(self, 'Export', 'No traces shown')
            return
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, 'Export the shown traces', 'sparams.csv', 'CSV (*.csv)')
        if path:
            kinds = self.s_kinds()
            refl = self.reflections() if any(sp.kind == SMITH_PLOT for sp in self.subplots) else []
            export_csv(path, trs, kinds[0] if kinds else KINDS[0], reflections=refl)

    def save_image(self, path=None):
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, 'Save the plots', 'results.png', 'PNG (*.png)')
        if path:
            self.grid_host.grab().save(path)
