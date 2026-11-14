"""The Log page: the runs of a study and where each is, openEMS's energy decay and mom25d's adaptive sweep, and
the log of each (RunTab); run_notes, what a run's summary says to note. Moved out of app.py (R-F2)."""
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel, QPlainTextEdit,
                               QProgressBar, QTreeWidget, QTreeWidgetItem, QHeaderView, QStackedWidget)
from .study import BY_KEY


COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']

class RunTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.stage = QLabel('idle')
        top.addWidget(self.stage, 1)
        self.stop_btn = QPushButton('Stop')
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(win.stop)
        top.addWidget(self.stop_btn)
        lay.addLayout(top)
        self.jobs = QTreeWidget()                                   # a study run's analyses: state and time
        self.jobs.setHeaderLabels(['Analysis', 'State', 'Time'])
        self.jobs.setRootIsDecorated(False)
        self.jobs.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.jobs.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.jobs.header().setStretchLastSection(False)
        self.jobs.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.jobs.hide()
        self.jobs.currentItemChanged.connect(lambda cur, _old: cur is not None and self.show_log(cur.data(0, Qt.UserRole)))
        self.job_rows = {}
        lay.addWidget(self.jobs)
        self.bars_box = QVBoxLayout()
        lay.addLayout(self.bars_box)
        self.bars, self.curves, self.hist, self._tol = {}, {}, {}, None
        plots = QVBoxLayout()                                       # one plot per kind of run: their x differ
        self.plot = pg.PlotWidget(title='openEMS: field energy / port signal decay')
        self.plot.setLabel('bottom', 'timestep')
        self.plot.setLabel('left', 'dB')
        self.plot.addLegend()
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.sweep = pg.PlotWidget(title="mom25d: the adaptive sweep's model change (max |dS|)")
        self.sweep.setLabel('bottom', 'EM solve')
        self.sweep.setLabel('left', 'dB')
        self.sweep.addLegend()
        self.sweep.showGrid(x=True, y=True, alpha=0.3)
        self.sweep.hide()
        plots.addWidget(self.plot, 1)
        plots.addWidget(self.sweep, 1)
        lay.addLayout(plots, 2)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        row = QHBoxLayout()                                         # whose log: the S-parameter run's, a page's
        self.log_label = QLabel('Log of')
        self.log_of = QComboBox()
        self.log_of.addItem(BY_KEY['rf'].title, 'rf')
        self.log_of.currentIndexChanged.connect(lambda i: self.logs.setCurrentIndex(max(i, 0)))
        row.addWidget(self.log_label)
        row.addWidget(self.log_of)
        row.addStretch(1)
        lay.addLayout(row)
        self.logs = QStackedWidget()
        self.logs.addWidget(self.log)
        lay.addWidget(self.logs, 1)
        self.log_label.hide()
        self.log_of.hide()

    def add_log(self, key, title, log):
        """Another analysis's log beside the S-parameter run's: a view of its page's own (the same document)."""
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setDocument(log.document())
        view.setFont(log.font())
        bar = view.verticalScrollBar()
        log.document().contentsChanged.connect(lambda: bar.setValue(bar.maximum()))      # follows, as the page's
        self.logs.addWidget(view)
        self.log_of.addItem(title, key)
        self.log_label.show()
        self.log_of.show()

    def show_log(self, key):
        i = self.log_of.findData(key)
        if i >= 0:
            self.log_of.setCurrentIndex(i)

    def set_jobs(self, jobs):
        """The analyses of a study run [(key, title)], queued; one alone: no list (the page as it was)."""
        self.jobs.clear()
        self.job_rows = {}
        for key, title in jobs:
            it = QTreeWidgetItem([title, 'queued', ''])
            it.setData(0, Qt.UserRole, key)
            self.jobs.addTopLevelItem(it)
            self.job_rows[key] = it
        self.jobs.setVisible(len(jobs) > 1)
        if jobs:
            rows = len(jobs)
            self.jobs.setFixedHeight(self.jobs.sizeHintForRow(0) * rows + self.jobs.header().sizeHint().height()
                                     + 2 * self.jobs.frameWidth() + 4)

    def job_state(self, key, text, seconds=None):
        it = self.job_rows.get(key)
        if it is None:
            return
        it.setText(1, text)
        it.setToolTip(1, text)
        f = it.font(1)
        f.setBold(text == 'running')
        it.setFont(1, f)
        if seconds is not None:
            it.setText(2, f"{int(seconds // 60)}:{int(seconds % 60):02d}")
        if text == 'running':
            self.jobs.setCurrentItem(it)                            # its log below

    def own_plots(self, on):
        """kicad2ems's own run's plots and bars: away while another analysis runs (its log has the page)."""
        if not on:
            for b in self.bars.values():
                b.hide()
            self.plot.hide()
            self.sweep.hide()

    def reset(self):
        for b in self.bars.values():
            b.deleteLater()
        self.bars, self.hist = {}, {}
        self.plot.clear()
        self.sweep.clear()
        self.curves = {}
        self._tol = None
        self.plot.show()
        self.sweep.hide()
        self.log.clear()

    def _sweep(self, run, ev):
        """mom25d's adaptive sweep, model by model: its largest change and its prediction error (max |dS|) in dB
        against the solve count, and the tolerance it stops at."""
        import math
        db = lambda v: 20 * math.log10(max(float(v), 1e-12))
        for key, label, style in (('change', 'model change', Qt.SolidLine), ('pred', 'prediction error', Qt.DashLine)):
            v = ev.get(key)
            name = f"{run} {label}"
            if name not in self.curves:
                pen = pg.mkPen(COLORS[len(self.curves) % len(COLORS)], width=2, style=style)
                self.curves[name] = self.sweep.plot([], [], pen=pen, symbol='o', symbolSize=5, name=name)
                self.hist[name] = ([], [])
            if v is not None and math.isfinite(float(v)):
                xs, ys = self.hist[name]
                xs.append(ev['afs_solves'])
                ys.append(db(v))
                self.curves[name].setData(xs, ys)
        if ev.get('tol') and self._tol is None:
            self._tol = pg.InfiniteLine(pos=db(ev['tol']), angle=0, pen=pg.mkPen('#c0392b', width=1, style=Qt.DotLine),
                                        label=f"tolerance {ev['tol']:g}", labelOpts=dict(position=0.08, color='#c0392b'))
            self.sweep.addItem(self._tol)
        self._layout()

    def _layout(self):
        """The plots with something in them: openEMS's energy (timesteps) and mom25d's sweep (EM solves) one
        above the other when both run; the energy plot alone while nothing has come in."""
        sweep = any(k.endswith(('model change', 'prediction error')) for k in self.curves)
        energy = any(not k.endswith(('model change', 'prediction error')) for k in self.curves)
        self.sweep.setVisible(sweep)
        self.plot.setVisible(energy or not sweep)

    def status(self, ev):
        run = ev.get('run', '?')
        if ev.get('change') is not None:                            # a step of mom25d's adaptive sweep
            self._sweep(run, ev)
            return
        if run not in self.bars:
            b = QProgressBar()
            b.setFormat(f"{run}: %p%")
            self.bars_box.addWidget(b)
            self.bars[run] = b
        b = self.bars[run]
        if ev.get('fraction') is not None:
            b.setValue(int(100 * ev['fraction']))
        eta = ev.get('eta')
        db = ev.get('db')
        what = (f"  {ev['solves']} EM solve(s), last at {ev.get('f_ghz') or 0:.3f} GHz" if ev.get('solves') is not None
                else f"  step {ev.get('step', 0):,}" + (f"  {db:.1f} dB" if db is not None else ''))     # MoM / openEMS
        b.setFormat(f"{run}: %p%{what}" + (f"  ETA {int(eta // 60)}m{int(eta % 60):02d}s" if eta else ''))
        if ev.get('step') is not None and db is not None:
            if run not in self.curves:                              # openEMS's energy: a curve once it has data
                pen = pg.mkPen(COLORS[len(self.curves) % len(COLORS)], width=2)
                self.curves[run] = self.plot.plot([], [], pen=pen, name=run)
                self.hist[run] = ([], [])
                self._layout()
            xs, ys = self.hist[run]
            xs.append(ev['step'])
            ys.append(db)
            self.curves[run].setData(xs, ys)




def run_notes(sm):
    """(warnings, notes) of a run's summary (<name>_run.json): its warnings (the log's WARNING lines), and the
    notes of the board's conversion (the ground plane, ports, parts), of the line model and the log's 'note:'
    lines (a setting ignored, an assumption made), each once and without its prefix."""
    import re
    strip = lambda t: re.sub(r'^\s*(?:[\w.-]+:\s+)?(?:WARNING|warning|note):\s*', '', str(t)).strip()
    warns = list(dict.fromkeys(strip(w) for w in sm.get('warnings') or [] if str(w).strip()))
    notes = list((sm.get('model') or {}).get('notes') or [])
    lines = sm.get('lines')
    if isinstance(lines, dict):
        notes += list(lines.get('notes') or [])
    notes += [l for l in sm.get('log') or [] if re.match(r'^\s*(?:[\w.-]+:\s+)?note:', str(l))]
    notes = [n for n in dict.fromkeys(strip(n) for n in notes) if n and n not in warns]
    return warns, notes
