"""
The Results page's plot of an analysis's curves (curves.py: a rail's impedance, a near field's spectrum), with other
runs of the same kind over it: the curves listed with a tick each, markers you click in and drag, their values in a
table, CSV and image export. The S-parameter plots are splot.SPlot; this is the same page for everything else.

    plot.set_sets(run, [other runs])        # CurveSets: the run solid, the others dashed in the same colours
"""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSplitter, QTreeWidget,
                               QTreeWidgetItem, QTableWidget, QTableWidgetItem, QFileDialog, QHeaderView,
                               QAbstractItemView)

from . import curves as C

COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
LIMIT = '#c0392b'


class CurvePlot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sets, self.items, self.markers, self._colors = [], [], [], {}
        self.hidden = set()                                         # (run label, curve name) unticked
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        for text, tip, slot in (('Fit', 'the whole of the curves shown', self.fit),
                                ('Clear markers', 'remove every marker (Delete removes the selected row\'s)', self.clear_markers),
                                ('Export CSV…', 'the curves shown, each run with its own frequencies', self.export_csv),
                                ('Save image…', 'the plot as a PNG', self.save_image)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=slot: f())
            row.addWidget(b)
        self.hint = QLabel('click: marker · drag a marker to move it · wheel / drag: zoom, pan')
        self.hint.setStyleSheet('color: gray')
        row.addWidget(self.hint)
        row.addStretch(1)
        lay.addLayout(row)
        self.split = QSplitter(Qt.Horizontal)
        self.split.setObjectName('curves')
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemChanged.connect(self._ticked)
        self.split.addWidget(self.tree)
        right = QSplitter(Qt.Vertical)
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        for ax in ('bottom', 'left'):                               # log axes: decades as they are
            self.plot.getAxis(ax).enableAutoSIPrefix(False)
        self.legend = self.plot.addLegend(offset=(-10, 10))
        self.plot.scene().sigMouseClicked.connect(self._clicked)
        right.addWidget(self.plot)
        self.table = QTableWidget(0, 1)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.hide()
        right.addWidget(self.table)
        right.setSizes([600, 140])
        self.split.addWidget(right)
        self.split.setSizes([220, 1000])
        lay.addWidget(self.split, 1)

    # ---- data ----
    def set_sets(self, run, others=()):
        """The run's curves (None: nothing) and those of other runs of the same kind laid over them."""
        same = bool(self.sets) and run is not None and self.sets[0].kind == run.kind
        self.sets = ([run] if run is not None else []) + [o for o in others if run is not None and o.kind == run.kind]
        if not same:
            self.clear_markers()
            self.hidden = set()
        self._fill_tree()
        self.redraw()
        self.fit()

    @property
    def main(self):
        return self.sets[0] if self.sets else None

    def _color(self, name):
        base = name.split(', bare planes')[0]                       # a load and its bare planes: one colour
        if base not in self._colors:
            self._colors[base] = COLORS[len(self._colors) % len(COLORS)]
        return self._colors[base]

    def _fill_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        for k, cs in enumerate(self.sets):
            top = QTreeWidgetItem([cs.label if k else f"{cs.label}  (this run)"])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setToolTip(0, cs.folder)
            self.tree.addTopLevelItem(top)
            for c in cs.curves:
                if c.role == 'limit' and k:                         # the run's own targets: once
                    continue
                it = QTreeWidgetItem([c.name])
                it.setData(0, Qt.UserRole, (cs.label, c.name))
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Unchecked if (cs.label, c.name) in self.hidden else Qt.Checked)
                it.setForeground(0, QBrush(QColor(LIMIT if c.role == 'limit' else self._color(c.name))))
                top.addChild(it)
        self.tree.expandAll()
        self.tree.blockSignals(False)

    def _ticked(self, it, _col):
        key = it.data(0, Qt.UserRole)
        if key is None:
            return
        key = tuple(key)
        (self.hidden.discard if it.checkState(0) == Qt.Checked else self.hidden.add)(key)
        self.redraw()

    def shown(self, roles=('data', 'reference', 'limit')):
        """[(set, curve, its number among the sets)] of the curves ticked, in the order drawn."""
        out = []
        for k, cs in enumerate(self.sets):
            for c in cs.curves:
                if c.role in roles and (cs.label, c.name) not in self.hidden and not (c.role == 'limit' and k):
                    out.append((cs, c, k))
        return out

    # ---- drawing ----
    def redraw(self):
        for it in self.items:
            self.plot.removeItem(it)
        self.items = []
        self.legend.clear()
        m = self.main
        if m is None:
            self.plot.setTitle('no curves in these results')
            self._update_table()
            return
        self.plot.setLogMode(x=m.logx, y=m.logy)
        self.plot.setTitle(m.title)
        self.plot.setLabel('bottom', m.xlabel)
        self.plot.setLabel('left', m.ylabel)
        for cs, c, k in self.shown():
            if c.role == 'limit':
                pen = pg.mkPen(LIMIT, width=1.5, style=Qt.DashLine)
            elif c.role == 'reference':
                pen = pg.mkPen(self._color(c.name), width=1, style=Qt.DotLine)
            else:                                                   # another run: the same colour, dashed
                pen = pg.mkPen(self._color(c.name), width=2, style=Qt.DashLine if k else Qt.SolidLine)
            x, y = np.asarray(c.x, float), np.asarray(c.y, float)
            ok = (x > 0 if m.logx else np.isfinite(x)) & (y > 0 if m.logy else np.isfinite(y))
            name = c.name if not k else f"{cs.label}: {c.name}"
            symbol = 'o' if c.role == 'data' and len(x) <= 24 else None     # a few points (harmonics): shown
            item = self.plot.plot(x[ok], y[ok], pen=pen, name=None if c.role == 'reference' else name,
                                  symbol=symbol, symbolSize=6, symbolBrush=pen.color() if symbol else None)
            self.items.append(item)
        self._update_table()

    def fit(self):
        """The data curves and the limits whole (a bare-planes curve reaching 1e11 Ω would squash the rest)."""
        m = self.main
        cs = self.shown(('data', 'limit')) or self.shown()
        if m is None or not cs:
            return
        xs = np.concatenate([np.asarray(c.x, float) for _, c, _ in cs])
        ys = np.concatenate([np.asarray(c.y, float) for _, c, _ in cs])
        xs, ys = xs[np.isfinite(xs) & (xs > 0 if m.logx else True)], ys[np.isfinite(ys) & (ys > 0 if m.logy else True)]
        if not len(xs) or not len(ys):
            return
        if m.logx:
            xr = (np.log10(xs.min()), np.log10(xs.max()))
        else:
            xr = (xs.min(), xs.max())
        if m.logy:
            yr = (np.log10(ys.min() / 2), np.log10(ys.max() * 2))
        else:
            pad = 0.05 * (ys.max() - ys.min() or 1.0)
            yr = (ys.min() - pad, ys.max() + pad)
        if xr[0] == xr[1]:
            xr = (xr[0] - 0.5, xr[1] + 0.5)
        self.plot.setXRange(*xr, padding=0.02)
        self.plot.setYRange(*yr, padding=0)

    # ---- markers ----
    def _x_of(self, pos):
        return float(10 ** pos) if self.main is not None and self.main.logx else float(pos)

    def _clicked(self, ev):
        if ev.button() != Qt.LeftButton or self.main is None or ev.isAccepted():
            return
        vb = self.plot.getPlotItem().vb
        if not vb.sceneBoundingRect().contains(ev.scenePos()):
            return
        self.add_marker(self._x_of(vb.mapSceneToView(ev.scenePos()).x()))

    def add_marker(self, x):
        """A marker at x (the axis's own unit, not its logarithm)."""
        if self.main is None or not np.isfinite(x) or (self.main.logx and x <= 0):
            return None
        line = pg.InfiniteLine(pos=np.log10(x) if self.main.logx else x, angle=90, movable=True,
                               pen=pg.mkPen('#444444', width=1), label=str(len(self.markers) + 1),
                               labelOpts=dict(position=0.95, color='#444444'))
        line.sigPositionChanged.connect(self._update_table)
        self.plot.addItem(line)
        self.markers.append(line)
        self._update_table()
        return line

    def marker_x(self):
        return [self._x_of(m.value()) for m in self.markers]

    def clear_markers(self):
        for m in self.markers:
            self.plot.removeItem(m)
        self.markers = []
        self._update_table()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.table.hasFocus():
            rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
            for r in rows:
                if r < len(self.markers):
                    self.plot.removeItem(self.markers.pop(r))
            for k, m in enumerate(self.markers):
                m.label.setFormat(str(k + 1))
            self._update_table()
            return
        super().keyPressEvent(ev)

    def _update_table(self, *_):
        m = self.main
        cols = self.shown(('data',))                                # the bare planes: on the plot, not here
        self.table.setVisible(bool(self.markers) and m is not None)
        if m is None or not self.markers:
            self.table.setRowCount(0)
            return
        self.table.setColumnCount(1 + len(cols))
        self.table.setHorizontalHeaderLabels(['marker'] + [c.name if not k else f"{cs.label}: {c.name}" for cs, c, k in cols])
        self.table.setRowCount(len(self.markers))
        for r, x in enumerate(self.marker_x()):
            self.table.setItem(r, 0, QTableWidgetItem(f"{r + 1}: {C.fmt_hz(x) if 'Hz' in m.xlabel else f'{x:.4g}'}"))
            for k, (cs, c, _n) in enumerate(cols):
                self.table.setItem(r, 1 + k, QTableWidgetItem(C.fmt(C.value_at(c, x, m.logx, m.logy), c.unit)))
        hd = self.table.horizontalHeader()
        hd.setSectionResizeMode(QHeaderView.ResizeToContents)

    def values(self):
        """The marker table as it reads: [[cell, ...]] (the tests', and what a copy would give)."""
        return [[self.table.item(r, c).text() if self.table.item(r, c) else '' for c in range(self.table.columnCount())]
                for r in range(self.table.rowCount())]

    # ---- export ----
    def export_csv(self, path=None):
        if not self.sets:
            return
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, 'Export the curves', f"{self.main.kind}_curves.csv", 'CSV (*.csv)')
        if path:
            keep = {(cs.label, c.name) for cs, c, _ in self.shown(('data', 'reference'))}
            sets = [C.CurveSet(cs.kind, cs.title, cs.xlabel, cs.ylabel,
                               [c for c in cs.curves if (cs.label, c.name) in keep], cs.logx, cs.logy, cs.folder, cs.label)
                    for cs in self.sets]
            C.export_csv(path, sets)

    def save_image(self, path=None):
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, 'Save the plot', 'results.png', 'PNG (*.png)')
        if path:
            self.plot.grab().save(path)
