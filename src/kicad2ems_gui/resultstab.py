"""The Plots page: S-parameters and antenna results as Cartesian, Smith and polar plots you add and remove, and
an analysis's curves (ResultsTab). Moved out of app.py (R-F2)."""
import os
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QComboBox, QPushButton, QLabel, QFileDialog, QMessageBox,
                               QToolButton, QStackedWidget, QMenu)
from .runner import find_results
from .splot import SPlot, default_layout
from .curveplot import CurvePlot
from .curves import load_sets
from .reportview import ReportView
from .panels import FlowLayout

from .runtab import run_notes

class ResultsTab(QWidget):
    """The Results page: the S-parameters of every solver and, for an antenna, its gain, efficiency and pattern
    cuts, as subplots you add and remove (splot.SPlot). The plots of a page are remembered: one layout for
    S-parameters, one for antennas. An analysis's result (a rail's drop and impedance, a near field, a circuit, a
    board's temperature: whatever kicad2ems's registry holds) takes the page instead with its curves
    (curveplot.CurvePlot; a result with several sets: one at a time), and has two more pages, which this one
    fills: Report, what it found, to read (`reportview`), and Tables, the report's tables to sort, copy and
    export (`tablesview`; reportview.ReportView both). Compare with lays other runs of the same kind over the
    plots."""
    MODES = ('Plots', 'Report', 'Tables')

    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        self.info = QLabel('no results yet')
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.info)
        self.notes_btn = QToolButton()                              # the run's notes and warnings, folded
        self.notes_btn.setCheckable(True)
        self.notes_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.notes_btn.setAutoRaise(True)
        self.notes_btn.toggled.connect(self._fold_notes)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.notes.setTextFormat(Qt.RichText)
        lay.addWidget(self.notes_btn)
        lay.addWidget(self.notes)
        self.set_notes([], [])
        top = FlowLayout()
        self.which = QComboBox()                                    # openEMS's and mom25d's antenna results
        self.which.setToolTip("The antenna results to show (a folder can hold openEMS's and mom25d's)")
        self.which.currentIndexChanged.connect(
            lambda i: self.load_antenna(self.out, self.which.itemData(i)) if i >= 0 and self.out else None)
        self.which.hide()
        top.addWidget(self.which)
        self.cmp_btn = QToolButton()                                # other runs over this one
        self.cmp_btn.setText('Compare with')
        self.cmp_btn.setToolTip("Lay other runs of this board over the one shown, each labelled by its folder: "
                                "their S-parameters, or the same kind of curves (a rail's impedance, a spectrum)")
        self.cmp_btn.setPopupMode(QToolButton.InstantPopup)
        self.cmp_menu = QMenu(self.cmp_btn)
        self.cmp_menu.aboutToShow.connect(self._fill_compare)
        self.cmp_btn.setMenu(self.cmp_menu)
        top.addWidget(self.cmp_btn)
        self.folder_btn = QPushButton('Open folder')
        self.folder_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(
            self.out if self.analysis and self.out else self.win.out_dir())))
        top.addWidget(self.folder_btn)
        self.set_box = QComboBox()                                  # a result with several curve sets: which
        self.set_box.setToolTip("The result's curves to plot (a circuit: each point's voltages and currents)")
        self.set_box.setMinimumWidth(220)
        self.set_box.currentIndexChanged.connect(self._pick_set)
        self.set_box.hide()
        top.addWidget(self.set_box)
        lay.addLayout(top)
        from .steering import SteeringBar
        self.steer = SteeringBar()
        lay.addWidget(self.steer)
        self.steers = []
        self.link_steering(self.steer)
        self.splot = SPlot()
        self.splot.layout_changed.connect(self._save_layout)
        self.curveplot = CurvePlot()
        self.reportview, self.tablesview = ReportView(), ReportView()       # the Report and Tables pages
        self.reportview.set_mode('Report')
        self.tablesview.set_mode('Tables')
        self.views = QStackedWidget()                               # the S-parameter plots, or an analysis's
        self.views.addWidget(self.splot)                            # curves
        self.views.addWidget(self.curveplot)
        lay.addWidget(self.views, 1)
        self.report, self.added, self._files, self.out, self._mode = None, [], [], None, None
        self.analysis, self.analysis_report = None, None            # the analysis whose result is shown, its report
        self.curve_sets, self.curves, self.added_sets = [], None, []    # its curve sets, the one plotted, other runs'
        self.mode = None                                            # the view of an analysis's result
        self._restore_layout('sparams')

    # ---- the plots a page has: remembered per kind of result ----
    def _key(self, mode):
        return f"results/layout/{mode}"

    def _restore_layout(self, mode):
        if mode == self._mode:
            return
        self._mode = mode
        spec = self.win.qsettings.value(self._key(mode)) if hasattr(self.win, 'qsettings') else None
        spec = [spec] if isinstance(spec, str) else list(spec or [])
        self.splot.set_layout(spec or default_layout(mode == 'antenna'))

    def _save_layout(self):
        if hasattr(self.win, 'qsettings') and self._mode:
            self.win.qsettings.setValue(self._key(self._mode), self.splot.layout_spec())

    # ---- data ----
    def open_report(self):
        if self.report:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.report))

    def _add(self):
        d = QFileDialog.getExistingDirectory(self, 'Another results folder to overlay', self.win.out_dir())
        if d and not self.add_folder(d):
            QMessageBox.information(self, 'Results', f"No {'S-parameters' if self.curves is None else self.curves.title.lower()} in {d}")

    def kind(self):
        """What the page shows: 'rf' (S-parameters, antenna) or the analysis whose result it is ('pdn', 'thermal')."""
        return self.analysis or 'rf'

    def compared(self):
        """The folders laid over the run shown (of its kind)."""
        if self.analysis is not None:
            return [sets[0].folder for sets in self.added_sets if sets and sets[0].kind == self.analysis]
        return [d for _label, _files, d in self.added]

    def add_folder(self, d):
        """Another run over the one shown: its S-parameters, or its curves when the page shows an analysis's
        (the same kind only). False: nothing of that kind in the folder."""
        d = os.path.abspath(d)
        if d in self.compared():
            return True
        if self.analysis is not None:
            sets = load_sets(d)
            if not sets or sets[0].kind != self.analysis:
                return False
            self.added_sets.append(sets)
            self._show_analysis()
            return True
        files = find_results(d)
        if not files:
            return False
        self.added.append((os.path.basename(os.path.normpath(d)) or d, files, d))
        self.show_files(self._files)
        return True

    def remove_folder(self, d=None):
        """One compared run off the page (None: all of the kind shown)."""
        if self.analysis is not None:
            self.added_sets = [sets for sets in self.added_sets
                               if sets[0].kind != self.analysis or (d and sets[0].folder != d)]
            self._show_analysis()
        else:
            self.added = [a for a in self.added if d and a[2] != d]
            self.show_files(self._files)

    def _fill_compare(self):
        """The Compare with menu: this board's other runs of the kind shown (ticked: laid over), another folder,
        none."""
        m = self.cmp_menu
        m.clear()
        kind, on = self.kind(), self.compared()
        here = os.path.abspath(self.out) if self.out else None
        srcs = self.win.sources() if hasattr(self.win, 'sources') else []
        listed = set()
        for src in srcs:
            d = os.path.abspath(src['folder'])
            if src['kind'] != kind or d == here:
                continue
            a = m.addAction(src['label'])
            a.setCheckable(True)
            a.setChecked(d in on)
            a.toggled.connect(lambda tick, d=d: (self.add_folder(d) if tick else self.remove_folder(d)))
            listed.add(d)
        for d in on:                                                # added from elsewhere
            if d not in listed:
                a = m.addAction(os.path.basename(d))
                a.setCheckable(True)
                a.setChecked(True)
                a.toggled.connect(lambda tick, d=d: None if tick else self.remove_folder(d))
        if not m.actions():
            a = m.addAction('no other run of this kind for this board yet')
            a.setEnabled(False)
        m.addSeparator()
        m.addAction('Another folder…').triggered.connect(self._add)
        a = m.addAction('None')
        a.setEnabled(bool(on))
        a.triggered.connect(lambda: self.remove_folder(None))

    def load_analysis(self, out_dir):
        """A folder's result of an analysis (whichever kicad2ems's registry says it is of) onto the page in place
        of the S-parameter plots: its report and its curves. False: it holds none, and the page shows
        S-parameters."""
        from kicad2ems.api.frontend import analyses, analysis_of
        made = analysis_of(out_dir) if out_dir else None
        rep, sets = None, []
        if made is not None and made[0] in analyses():
            folder = os.path.abspath(out_dir)
            try:
                rep = analyses()[made[0]].report(folder)
            except Exception:                                       # a plugin's fault, a damaged file: no report
                rep = None
            if rep:
                rep = self._with_engines(made[0], folder, rep)
            sets = load_sets(folder)
        self.analysis = made[0] if made is not None and (rep or sets) else None
        self.analysis_report, self.curve_sets = (rep, sets) if self.analysis else (None, [])
        if self.analysis:
            self.out = os.path.abspath(out_dir)
        keep = self.set_box.currentText()
        self.set_box.blockSignals(True)
        self.set_box.clear()
        self.set_box.addItems([cs.title for cs in self.curve_sets])
        self.set_box.setCurrentIndex(max(self.set_box.findText(keep), 0) if self.curve_sets else -1)
        self.set_box.blockSignals(False)
        self._show_analysis()
        return self.analysis is not None

    load_curves = load_analysis                                     # its name before reports

    def _with_engines(self, name, folder, report):
        """A result's report with the other engines' answers to the same question beside it: a section 'Engines
        compared' whose table has the figures they name (kicad2ems.api.frontend.compare_engines: this result and
        each other engine's newest on this board) against the engines, and the difference where two give one.
        Nothing to compare: the report as it is."""
        from kicad2ems.api.frontend import compare_engines, engines, questions
        try:
            es, qs = engines(), questions()
            me = es.get(name)
            latest = dict(self.win.latest_results()) if hasattr(self.win, 'latest_results') else {}
            latest[name] = folder
            added = []
            for q in (me.provides if me is not None else ()):
                names = [e.name for e in es.values() if e.kind == 'analysis' and q in e.provides and e.name in latest]
                if len(names) < 2:
                    continue
                c = compare_engines({n: latest[n] for n in names})
                if not any(r['spread'] is not None for r in c['rows']):
                    continue                                        # no figure two of them give
                n = len(c['labels'])
                rows = [[r['name'], r['unit'], *['' if v is None else v for v in r['values']],
                         '' if r['spread'] is None else r['spread']] for r in c['rows']]
                where = '; '.join(f"{lab}: {os.path.basename(latest[k])}" for lab, k in zip(c['labels'], c['engines']))
                added.append(dict(title=f"Engines compared: {qs[q].label if q in qs else q}",
                                  text=f"Each engine's newest result on this board ({where}). A figure both name is "
                                       "the same quantity; one only an engine has is its own.",
                                  table=dict(columns=['figure', 'unit', *c['labels'], 'difference'], rows=rows,
                                             formats=[None, None, *['.4g'] * n, '.3g'])))
            if not added:
                return report
            sections = list(report.get('sections') or [])
            at = 1 if sections and not sections[0].get('title') else 0     # after its opening words
            return dict(report, sections=sections[:at] + added + sections[at:])
        except Exception:                                           # noqa: BLE001 (a plugin's figures, a damaged file)
            return report

    def _pick_set(self, *_):
        if self.analysis is not None:
            self._show_analysis()

    def modes(self):
        """The views the result shown has: Plots (it has curves), Report, Tables (its report has tables)."""
        rep = self.analysis_report
        has = dict(Plots=bool(self.curve_sets), Report=bool(rep),
                   Tables=bool(rep) and any(sec.get('table') for sec in rep.get('sections', [])))
        return [m for m in self.MODES if has[m]] if self.analysis else []

    def set_mode(self, mode):
        """The page of an analysis's result in front: Plots, Report or Tables (one the result has; else its
        first). They are pages of their own, so this only brings one forward."""
        has = self.modes()
        if not has:
            return
        self.mode = mode if mode in has else has[0]
        win = self.win
        if win is not None and hasattr(win, 'docks'):
            win.show_panel('Results' if self.mode == 'Plots' else self.mode)

    def _show_analysis(self):
        """The result of an analysis on its pages (the curves here, the report and its tables on theirs); none:
        the S-parameter plots here, and nothing on those."""
        has = self.modes()
        if not has:
            self.curves = None
            self.set_box.hide()
            self.cmp_btn.setEnabled(True)
            self.views.setCurrentWidget(self.splot)
            for view in (self.reportview, self.tablesview):
                view.set_report(None)
            return
        i = self.set_box.currentIndex()
        self.curves = self.curve_sets[i] if 0 <= i < len(self.curve_sets) else None
        if self.curves is not None:                                 # other runs: their set of the same title
            others = [next((o for o in sets if o.title == self.curves.title), None) for sets in self.added_sets
                      if sets and sets[0].kind == self.analysis and sets[0].folder != self.curves.folder]
            self.curveplot.set_sets(self.curves, [o for o in others if o is not None])
        else:
            others = []
            self.curveplot.set_sets(None)
        for view in (self.reportview, self.tablesview):
            view.set_report(self.analysis_report)
        self.views.setCurrentWidget(self.curveplot)
        self.set_box.setVisible(len(self.curve_sets) > 1)
        self.cmp_btn.setEnabled(bool(self.curve_sets))
        self.which.hide()
        self.steer.hide()
        self.report = None
        rep = self.analysis_report or {}
        self.set_notes([], [])                                      # the report has its own
        head = rep.get('summary') or (self.curves.info if self.curves is not None else '')
        if not self.curve_sets and rep:
            head += '  ·  no curves in this result: its Report page has it'
        self.info.setText(head + (f"  ·  with {', '.join(o.label for o in others if o is not None)}" if others else ''))
        self.mode = self.mode if self.mode in has else has[0]

    def _load(self):
        d = QFileDialog.getExistingDirectory(self, 'A results folder (the run\'s output folder)', self.win.out_dir())
        if d:
            self.win.open_results(d)

    def load_antenna(self, out_dir, path=None):
        """The antenna results of a folder (path: which; default the newest) into the plots; False: none."""
        from .antennatab import find_antenna, antenna_files, load_sphere, load_array
        self.out = out_dir
        files = antenna_files(out_dir) if out_dir else []
        self.which.blockSignals(True)
        self.which.clear()
        for f in files:
            try:
                from kicad2ems.api.frontend import read_antenna
                solver = read_antenna(f).get('solver', 'openems')
            except (OSError, ValueError):
                solver = os.path.basename(f)
            self.which.addItem(solver, f)
        if files:
            self.which.setCurrentIndex(files.index(path) if path in files else len(files) - 1)
        self.which.setVisible(len(files) > 1)
        self.which.blockSignals(False)
        try:
            found = find_antenna(out_dir, path) if files else None
            sph = load_sphere(found[1]) if found and found[1] else None
        except Exception as e:                                      # a damaged file must not take the GUI down
            found, sph = None, None
            self.info.setText(f"could not read the antenna results: {e}")
        res = found[0] if found else None
        try:
            arr = load_array(out_dir, res) if res else None
        except Exception:                                           # no steering then
            arr = None
        self.splot.set_antenna(res, sph)                            # first: the plots' antenna options exist then
        self._restore_layout('antenna' if res else 'sparams')
        for b in self.steers:
            b.set_data(res, arr)
        if res:
            m = res['match']
            bw = (f", −10 dB band {m['bw10_lo'] / 1e9:.3f}–{m['bw10_hi'] / 1e9:.3f} GHz" if m.get('bw10') else
                  ', S11 never below −10 dB')
            self.info.setText(f"{res.get('solver', 'openems')} antenna, {res.get('port', '')}: resonance "
                              f"{m['f_res'] / 1e9:.4f} GHz, S11 {m['s11_db']:.1f} dB, Zin {m['zin'][0]:.1f} "
                              f"{'+' if m['zin'][1] >= 0 else '−'} j{abs(m['zin'][1]):.1f} Ω{bw}")
        return bool(res)

    def link_steering(self, bar):
        """A Beam steering bar (this page's, the 3D view's): every bar shows the same drive, and steering any
        redraws the antenna plots and the 3D pattern."""
        self.steers.append(bar)
        bar.steered.connect(lambda res, sphere, src=bar: self._steered(res, sphere, src))
        bar.anim.toggled.connect(lambda on, src=bar: [b.follow_animation(on) for b in self.steers if b is not src])

    def _steered(self, res, sphere, src=None):
        """A steered drive (a Beam steering bar): the antenna plots, the 3D view's pattern, the other bars."""
        self.splot.update_antenna(res, sphere)
        vol = getattr(self.win, 'volume', None)
        if vol is not None and hasattr(vol, 'set_far'):
            vol.set_far(res, sphere)
        for b in self.steers:
            if b is not src:
                b.mirror(src)

    def set_notes(self, warns, notes):
        """The run's warnings (red) and notes under a fold, open when there is a warning; hidden when none."""
        import html
        self.notes_btn.setVisible(bool(warns or notes))
        parts = []
        if warns:
            parts.append(f"{len(warns)} warning{'s' if len(warns) > 1 else ''}")
        if notes:
            parts.append(f"{len(notes)} note{'s' if len(notes) > 1 else ''}")
        self.notes_btn.setText(f"Notes and warnings ({', '.join(parts)})" if parts else '')
        items = [f"<li style='color:#c62828'>{html.escape(w)}</li>" for w in warns] + \
                [f"<li>{html.escape(n)}</li>" for n in notes]
        self.notes.setText(f"<ul style='margin:0'>{''.join(items)}</ul>" if items else '')
        self.notes_btn.blockSignals(True)
        self.notes_btn.setChecked(bool(warns))
        self.notes_btn.blockSignals(False)
        self._fold_notes(bool(warns))

    def _fold_notes(self, on):
        self.notes_btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.notes.setVisible(bool(on) and self.notes_btn.isVisibleTo(self))

    def show_files(self, files, compare=None):
        """The S-parameters of a run's files (openEMS, mom25d, line model) and a compare file."""
        from .traces import load_traces
        self._files = list(files)
        if self.analysis is not None:                               # an analysis's result has the page
            return
        self.report = next((p for l, p in files if p.endswith('_report.html')), None)
        z0 = 50.0
        summary = next((p for l, p in files if p.endswith(('_run.json', '_openems.json'))), None)
        self.set_notes([], [])
        if summary and os.path.exists(summary):
            try:
                from kicad2ems.api.frontend import read_summary
                sm = read_summary(summary)
                self.set_notes(*run_notes(sm))
                compare = compare or (sm.get('settings') or {}).get('compare')
                zr = sm.get('zref')
                z0 = float(zr[0] if isinstance(zr, list) else zr or 50.0)
            except (ValueError, TypeError, OSError):
                pass
        if compare is None:
            compare = self.win.setup.values().get('compare')
        try:
            traces = load_traces(files, compare)
            for label, fs, _d in self.added:                         # other runs: their solvers under the folder's name
                for tr in load_traces(fs):
                    tr.source = f"{label}: {tr.source}"
                    traces.append(tr)
        except Exception as e:                                       # a damaged file must not take the GUI down
            self.info.setText(f"could not read the S-parameters: {e}")
            return
        self.splot.set_traces(traces, z0)
        shown = sorted({os.path.basename(t.path) for t in traces})
        if self.splot.antenna is None:
            self.info.setText(', '.join(shown) if shown else 'no S-parameters in this run')
