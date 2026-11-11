"""
kicad2ems GUI (PySide6 + pyqtgraph): set up a study, preview it, watch it, see the results. The window has the
study on the left (the board, the analyses made of it and the settings of the one selected: study.py) and its pages:

    Viewer   the board in 3D or from above, a solver's mesh, the line model coloured by Z0 (pick a section to read
             it), field dumps in place or as cuts (live while the run goes), the far field, the run's plots
    Run      the analyses of the run and where each is, openEMS's energy decay and mom25d's adaptive sweep, the
             log of each
    Results  S-parameters and antenna results as Cartesian, Smith and polar plots you add and remove
    Filter Synthesis
             design a microstrip filter with dfsynth, validate and tune it on the solvers, open its board here
    Power Integrity, Near field, Circuit
             the results of pcbqs's tools (python -m pcbqs.pdn, .mqs, .power_circuit): a rail's DC drop and PDN
             impedance, a converter's input loop and its magnetic field, ngspice operating points. Their settings
             are in the study, and the toolbar's Run starts them with the rest

Run starts the analyses ticked in the study one after the other (run_study), each after the one it starts from.
Every run is the command-line tool started as a separate process with --events; the GUI follows its event
stream, so a closed window never kills a simulation's results and the GUI needs no openEMS of its own. The
window's size, its docks and splitters, and the Results plots are remembered between sessions.

    kicad2ems-gui [config.toml]
"""
import json, os, sys
from PySide6.QtCore import Qt, QProcess, QTimer, QUrl, QSettings
from PySide6.QtGui import QDesktopServices, QAction, QKeySequence, QIcon
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
                               QLineEdit, QCheckBox, QComboBox, QPushButton, QLabel, QPlainTextEdit, QProgressBar,
                               QFileDialog, QScrollArea, QMessageBox, QDockWidget, QToolBar, QStyle, QToolButton,
                               QDialog, QTabWidget, QApplication, QTreeWidget, QTreeWidgetItem, QHeaderView,
                               QStackedWidget, QMenu)
import pyqtgraph as pg
from .runner import (FIELDS, SEMICOLON_LISTS, SECTION_SOLVERS, SECTION_TITLES, TICK, Run, EventTail, stop_runs, settings_values,
                     extra_values, find_results, save_config, solvers_from_form, solver_ticks)
from kicad2ems.api.frontend import G_DUMP
from .splot import SPlot, default_layout
from .curveplot import CurvePlot
from .curves import load_curves
from .panels import Section, FlowLayout
from .systempanel import SystemPanel
from .viewer import Viewer, VIEWS
from .statusbar import MemoryMeters, EstimateButton
from .meters import duration
from .filtertab import FilterTab
from .pdntab import PdnTab
from .mqstab import MqsTab
from .powercircuittab import PowerCircuitTab
from .study import StudyList, ANALYSES, BY_KEY, run_order, dependents

pg.setConfigOptions(antialias=True, background='w', foreground='k')
DOCS = 'https://github.com/lowprocess/kicad2ems/blob/main/docs/index.md'
MAX_RECENT = 8
PANELS = ('Viewer', 'Run', 'Results', 'Filter', 'PDN', 'Near field', 'Circuit')
TITLES = {'Filter': 'Filter Synthesis', 'PDN': 'Power Integrity'}                           # a page's tab title, when not its name
ON_DEMAND = ('Filter',)                         # pages closed when the window opens: the toolbar's Filter opens it
FOLLOWS_TICK = {'Circuit': 'circuit'}           # pages shown while their analysis is ticked (or opened by hand)
WAND = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wand.svg')
STATE_VERSION = 2                                                   # saved dock layouts of older windows: ignored
COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']


class SetupTab(QWidget):
    """The study's settings, in a scroll area: the board (one for every analysis), the analyses (study.StudyList,
    once the window gave its pages: set_study) and the settings of the analysis selected there. Each group is a
    collapsible section (collapsed when the window opens; the header counts the settings set). Open / Save /
    Preview / Run are the window's toolbar."""
    def __init__(self, win):
        super().__init__()
        from kicad2ems.api.frontend import Settings
        self.win, self.edits, self.extra = win, {}, {}
        self.path, self.dirty, self._loading, self.est = None, False, False, None
        self.defaults = Settings()
        defaults = self.defaults
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        left.setSpacing(2)
        rf = QVBoxLayout()                                          # the S-parameter run's own sections
        rf.setContentsMargins(0, 0, 0, 0)
        rf.setSpacing(2)
        top_of = lambda group: left if group == 'Board' else rf     # the board: above the analyses, for all
        groups, self.sections, self.group_of, self.solver_boxes, self.solver_labels = {}, {}, {}, {}, {}
        self.parents = {}                                           # 'openEMS': (its section, the layout of its subs)
        self.field_labels = {}                                      # key: its label (greyed with the field)
        for key, label, kind, group in FIELDS:
            if '/' in group and group.split('/')[0] not in self.parents:     # a solver's section of sub-sections
                top = group.split('/')[0]
                holder = QWidget()
                sub = QVBoxLayout(holder)
                sub.setContentsMargins(0, 0, 0, 0)
                sub.setSpacing(2)
                self.parents[top] = (Section(SECTION_TITLES.get(top, top), holder), sub)
                rf.addWidget(self.parents[top][0])
            if group not in groups:
                box = QWidget()
                groups[group] = QFormLayout(box)
                groups[group].setContentsMargins(0, 0, 0, 0)
                groups[group].setRowWrapPolicy(QFormLayout.WrapLongRows)     # narrow: the field under its label
                groups[group].setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
                extra = None
                if group == 'Solvers':                              # what can run here: the Solvers window
                    extra = QToolButton()
                    extra.setText('?')
                    extra.setAutoRaise(True)
                    extra.setToolTip('Solvers and hardware: what can run here, the GPU, the memory, the estimates')
                    extra.clicked.connect(lambda: self.win.show_solvers())
                    self.help_btn = extra
                self.sections[group] = Section(group.split('/')[-1], box, extra=extra)
                (self.parents[group.split('/')[0]][1] if '/' in group else top_of(group)).addWidget(self.sections[group])
            self.group_of[key] = group
            if kind == 'bool':
                w = QCheckBox()
                w.toggled.connect(self._changed)
                if key.startswith(TICK):
                    self.solver_boxes[key[len(TICK):]] = w
            elif isinstance(kind, tuple):
                w = QComboBox()
                w.addItems([c or '(none)' for c in kind])
                w.currentIndexChanged.connect(self._changed)
            else:
                w = QLineEdit()
                d = getattr(defaults, key, None)
                if d not in (None, '', []) and kind != 'dir':
                    w.setPlaceholderText(f"default: {', '.join(map(str, d)) if isinstance(d, (list, tuple)) else d}")
                w.textChanged.connect(self._changed)
            if kind in ('file', 'dir'):
                row = QHBoxLayout()
                row.addWidget(w)
                b = QPushButton('…')
                b.setFixedWidth(28)
                b.clicked.connect(lambda _=False, k=key, d=(kind == 'dir'): self._browse(k, d))
                row.addWidget(b)
                holder = QWidget()
                holder.setLayout(row)
                row.setContentsMargins(0, 0, 0, 0)
                groups[group].addRow(label, holder)
            elif key.startswith(TICK):                              # a solver: its name on the box, a whole row
                w.setText(label)
                self.solver_labels[key[len(TICK):]] = label
                groups[group].addRow(w)
            else:
                groups[group].addRow(label, w)
            self.field_labels[key] = groups[group].labelForField(w)
            self.edits[key] = (w, kind)
        if G_DUMP in groups:                                        # an FDTD solver installed
            groups[G_DUMP].addRow('Add a dump', self._dump_builder())
        for top, need in SECTION_SOLVERS.items():                   # a solver's own section, when it also shares
            shared = [t for t, n in SECTION_SOLVERS.items() if t != top and len(n) > 1 and need <= n]   # another
            if len(need) == 1 and shared and top in groups:
                note = QLabel(f"{top} also uses the settings under {SECTION_TITLES[shared[0]]} above")
                note.setWordWrap(True)
                note.setEnabled(False)                              # greyed: a note, not a setting
                groups[top].insertRow(0, note)
        self.study = None                                           # the analyses' list (set_study)
        self.study_slot = QVBoxLayout()
        self.study_slot.setContentsMargins(0, 0, 0, 0)
        left.addLayout(self.study_slot)
        self.panel_title = QLabel('')                               # whose settings follow
        self.panel_title.setStyleSheet('font-weight: bold; padding: 8px 4px 2px 4px;')
        self.panel_title.hide()
        left.addWidget(self.panel_title)
        self.rf_box = QWidget()
        self.rf_box.setLayout(rf)
        self.panels = {'rf': self.rf_box}                           # analysis: its settings (one shown)
        left.addWidget(self.rf_box)
        left.addStretch(1)
        self._left = left
        lw = QWidget()
        lw.setLayout(left)
        scroll = QScrollArea()
        scroll.setWidget(lw)
        scroll.setWidgetResizable(True)
        # the form wraps its rows instead of scrolling sideways: as wide as its narrowest layout, plus room for
        # the vertical scroll bar (a long form shows it, and without that room a sideways one appeared too)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll, self._lw = scroll, lw
        self._fit_width()
        outer.addWidget(scroll)
        self._update_sections()                                     # before any config: nothing ticked, all greyed

    def _fit_width(self):
        """The dock at least as wide as its widest settings (the hidden analyses' too: selecting one must not
        cut its fields off, the form having no sideways scroll bar)."""
        bar = self.scroll.verticalScrollBar().sizeHint().width()
        need = max([self._lw.minimumSizeHint().width()] + [p.minimumSizeHint().width() for p in self.panels.values()])
        self.scroll.setMinimumWidth(max(270, min(need, 420) + bar + 2 * self.scroll.frameWidth() + 2))

    def set_study(self, study, panels):
        """The analyses' list under the board, and each analysis's settings {key: widget} (a page's own form,
        moved here): the selected analysis's are the ones shown."""
        from .study import ANALYSES
        self.study = study
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(study)
        self.study_note = QLabel('ticked: Preview and Run include it')
        self.study_note.setWordWrap(True)
        self.study_note.setEnabled(False)                           # greyed: a note, not a setting
        hl.addWidget(self.study_note)
        self.study_section = Section('Analyses', holder, expanded=True)
        self.study_slot.addWidget(self.study_section)
        at = self._left.indexOf(self.rf_box) + 1
        for a in ANALYSES:
            w = panels.get(a.key)
            if w is None or a.key in self.panels:
                continue
            self.panels[a.key] = w
            self._left.insertWidget(at, w)
            at += 1
        study.selected.connect(self.show_settings)
        study.ticks_changed.connect(self._ticks)
        self._fit_width()
        self.show_settings(study.current())
        self._solvers_text()
        self._ticks()

    def show_settings(self, key):
        """The settings of one analysis under the list, the others' hidden."""
        from .study import BY_KEY
        for k, w in self.panels.items():
            w.setVisible(k == key)
        a = BY_KEY.get(key)
        self.panel_title.setText(f"{a.title} settings" if a else '')
        self.panel_title.setVisible(a is not None and self.study is not None)

    def _solvers_text(self):
        """The S-parameters analysis's With in the list: the solvers ticked under Solvers."""
        if self.study is not None:
            on = [n for n, w in self.solver_boxes.items() if w.isChecked()]
            self.study.set_tool('rf', ', '.join(on) if on else 'no solver ticked')

    def _ticks(self):
        from .study import ANALYSES
        n = len(self.study.ticked())
        self.study_section.head.setText(f"Analyses  ({n} of {len(ANALYSES)})")
        if hasattr(self.win, 'ticks_changed'):
            self.win.ticks_changed()

    def set_availability(self, info):
        """The machine's solvers (sysinfo): a solver that cannot run here says why on its tick box."""
        for s in info.get('solvers', []):
            w = self.solver_boxes.get(s['name'])
            if w is not None:
                w.setToolTip('' if s['ok'] else f"not available here: {s['what']} (? for the Solvers window)")
                w.setStyleSheet('' if s['ok'] else 'QCheckBox { color: gray; }')

    def set_estimates(self, est):
        """A preview's estimates beside the full-wave solvers' tick boxes: time and memory on that board (None:
        none, the box shows its name alone). The window's toolbar shows them for the solvers ticked."""
        self.est = est
        rows = (est or {}).get('solvers', {})
        for name, w in self.solver_boxes.items():
            e = rows.get(name)
            w.setText(self.solver_labels.get(name, name))
            if not e:
                continue
            t = duration(e.get('seconds', 0))
            w.setText(f"{self.solver_labels.get(name, name)}  ·  {t}, {e['gb']:.1f} GB")
            w.setToolTip(f"last preview: {t}, {e['gb']:.1f} GB" + (f"; {e['what']}" if e.get('what') else ''))
        if hasattr(self.win, 'update_estimate'):
            self.win.update_estimate()

    def _count(self):
        """Per section: how many of its fields are set (non-empty, a ticked box differing from the default)."""
        counts = dict.fromkeys(self.sections, 0)
        for key, (w, kind) in self.edits.items():
            if kind == 'bool':
                d = getattr(self.defaults, key, False) if not key.startswith(TICK) else key == f"{TICK}auto"
                on = w.isChecked() != bool(d)
            elif isinstance(kind, tuple):
                on = w.currentIndex() > 0 and w.currentText() != str(getattr(self.defaults, key, ''))
            else:
                on = bool(w.text().strip())
            counts[self.group_of[key]] += on
        for g, n in counts.items():
            self.sections[g].set_count(n)
        for top, (sec, _) in self.parents.items():                  # a solver's section: its sub-sections' sum
            sec.set_count(sum(n for g, n in counts.items() if g.split('/')[0] == top))

    def _update_sections(self):
        """A solver's section (and the shared ones) greyed while none of its solvers is ticked: auto may run
        openEMS, mom25d and the line model."""
        from kicad2ems.api.frontend import registry
        self._solvers_text()
        ticked = {n for n, w in self.solver_boxes.items() if w.isChecked()}
        auto = self.edits.get(f"{TICK}auto", (None,))[0]
        if auto is not None and auto.isChecked():                   # the solvers auto may run, the line model's
            ticked |= {n for n, sv in registry().items() if sv.in_auto or sv.consumes == 'network'}
        tops = {g.split('/')[0]: sec for g, sec in self.sections.items() if '/' not in g}
        tops.update({t: sec for t, (sec, _) in self.parents.items()})
        for top, sec in tops.items():
            need = SECTION_SOLVERS.get(top)
            if need is None:
                continue
            on = bool(need & ticked)
            sec.setEnabled(on)
            names = ', '.join(self.solver_labels.get(n, n) for n in sorted(need) if n in self.solver_labels)
            sec.setToolTip('' if on else f"for {names}: tick it under Solvers to use these settings")
        from .runner import ANTENNA_FIELDS
        mode = self.edits.get('mode', (None,))[0]
        radiating = [n for n, sv in registry().items() if sv.capabilities.get('antenna', 'no').split(':')[0] != 'no']
        antenna = mode is not None and mode.currentText() == 'antenna' and bool(set(radiating) & ticked)
        for key in ANTENNA_FIELDS:                                  # antenna settings: antenna mode only
            if key not in self.edits:
                continue
            w = self.edits[key][0]
            w.setEnabled(antenna)
            lab = self.field_labels.get(key)
            if lab is not None:
                lab.setEnabled(antenna)
            w.setToolTip('' if antenna else "antenna mode only (Solvers: Mode = antenna, with " +
                         " or ".join(self.solver_labels.get(n, n) for n in radiating) + ")")

    def _dump_builder(self):
        """FIELD, where (a layer, an x / y / z plane, the volume), GHz -> a spec appended to the dumps."""
        fld = QComboBox()
        fld.addItems(['E', 'H', 'J'])
        fld.setToolTip('J: current density (shows the copper currents)')
        kind = QComboBox()
        kind.addItems(['layer', 'x =', 'y =', 'z =', 'volume'])
        at = QComboBox()
        at.setEditable(True)
        at.addItems(['F.Cu', 'B.Cu', 'In1.Cu', 'In2.Cu', 'F.Cu-0.1'])
        at.setToolTip('layer: a copper layer, with an offset in mm (F.Cu-0.1: in the dielectric below); '
                      'x / y / z: mm (KiCad x, y; z from the bottom copper)')
        kind.currentIndexChanged.connect(lambda i: (at.setEnabled(i != 4), at.setEditText(['F.Cu', '0', '0', '0', ''][i])))
        ghz = QLineEdit()
        ghz.setPlaceholderText('GHz (empty: time domain)')
        ghz.setToolTip('Frequencies (GHz, comma-separated): a frequency-domain dump, animated over the phase. '
                       'Empty: a time-domain dump, viewable live during the run')
        add = QPushButton('Add')

        def append():
            k = kind.currentIndex()
            where = 'volume' if k == 4 else (at.currentText().strip() if k == 0 else f"{'xyz'[k - 1]}={at.currentText().strip()}")
            spec = f"{fld.currentText()}@{where}" + (f"@{ghz.text().strip()}" if ghz.text().strip() else '')
            w = self.edits['dump'][0]
            w.setText('; '.join([t for t in [w.text().strip()] if t] + [spec]))
        add.clicked.connect(append)
        grid = QGridLayout()                                        # two short rows: fits a narrow settings dock
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(fld, 0, 0)
        grid.addWidget(kind, 0, 1)
        grid.addWidget(at, 0, 2)
        grid.addWidget(ghz, 1, 0, 1, 2)
        grid.addWidget(add, 1, 2)
        grid.setColumnStretch(2, 1)
        holder = QWidget()
        holder.setLayout(grid)
        return holder

    def _browse(self, key, folder):
        w = self.edits[key][0]
        if folder:
            p = QFileDialog.getExistingDirectory(self, 'Output folder', w.text() or os.getcwd())
        else:
            flt = 'KiCad board (*.kicad_pcb)' if key == 'board' else 'Pick-and-place (*.pos *.csv);;All files (*)'
            p, _ = QFileDialog.getOpenFileName(self, 'Choose a file', w.text() or os.getcwd(), flt)
        if p:
            w.setText(p)
            if key == 'board' and not self.edits['out'][0].text():
                self.edits['out'][0].setText(os.path.join(os.path.dirname(p), 'out'))

    # ---- values <-> widgets ----
    def values(self):
        """The settings of the form (the solver tick boxes as `solvers`, see runner.solvers_from_form)."""
        out = dict(self.extra)                                       # config settings without a field here
        for key, (w, kind) in self.edits.items():
            if kind == 'bool':
                out[key] = w.isChecked()
                continue
            if isinstance(kind, tuple):
                t = w.currentText()
                out[key] = '' if t == '(none)' else t
                continue
            t = w.text().strip()
            if not t:
                continue
            if kind == 'float':
                out[key] = float(t)
            elif kind == 'int':
                out[key] = int(float(t))
            elif kind == 'list':
                out[key] = [x.strip() for x in t.replace(';', ',').split(',') if x.strip()] \
                    if key not in SEMICOLON_LISTS else [x.strip() for x in t.split(';') if x.strip()]
            elif key == 'region' and t.replace(',', '').replace('.', '').replace('-', '').replace(' ', '').isdigit():
                out[key] = [float(x) for x in t.split(',')]
            else:
                out[key] = t
        out = solvers_from_form(out)
        return out

    def set_values(self, vals):
        """Fill the form (a loaded config): not an edit, so the settings stay unchanged."""
        loading, self._loading = self._loading, True
        try:
            self._set_values(vals)
        finally:
            self._loading = loading
        self._count()
        self._update_sections()

    def _set_values(self, vals):
        if not any(k.startswith(TICK) for k in vals):              # settings rather than the form's own values
            vals = dict(vals, **solver_ticks(vals))
        for key, (w, kind) in self.edits.items():
            v = vals.get(key)
            if kind == 'bool':
                w.setChecked(bool(v))
            elif isinstance(kind, tuple):
                i = w.findText(v or '(none)')
                w.setCurrentIndex(max(i, 0))
            elif v is None:
                w.setText('')
            elif isinstance(v, (list, tuple)):
                sep = '; ' if key in SEMICOLON_LISTS else ','
                w.setText(sep.join(str(x) if not isinstance(x, (list, tuple)) else ' '.join(map(str, x)) for x in v))
            else:
                w.setText(str(v))

    def _changed(self, *_):
        self._count()
        self._update_sections()
        if not self._loading and not self.dirty:
            self.dirty = True
            self.win.update_title()
        if hasattr(self.win, 'update_estimate'):                    # the toolbar's: the solvers ticked now
            self.win.update_estimate()

    def _start_dir(self):
        if self.path:
            return os.path.dirname(self.path)
        from kicad2ems.api.frontend import examples_folder
        return examples_folder() if os.path.isdir(examples_folder()) else os.getcwd()

    def maybe_save(self):
        """True when the form may be replaced: saved, discarded or unchanged."""
        if not self.dirty:
            return True
        r = QMessageBox.question(self, 'Unsaved settings', 'Save the changes to the settings first?',
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def new(self):
        if not self.maybe_save():
            return
        self.set_values({})
        self.set_estimates(None)                                    # another board: the last one's no longer apply
        self.extra, self.path, self.dirty = {}, None, False
        self.win.update_title()

    def load(self, path=None):
        if path is None and not self.maybe_save():
            return False
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, 'Open a config', self._start_dir(), 'TOML (*.toml)')
        if not path:
            return False
        from kicad2ems.api.frontend import build_settings
        try:
            vals, extra = settings_values(path), extra_values(path)
            notes = build_settings({}, path).notes
        except Exception as e:
            QMessageBox.warning(self, 'Config', str(e))
            return False
        self.set_values(vals)
        self.set_estimates(None)                                    # another board: the last one's no longer apply
        self.extra, self.path, self.dirty = extra, os.path.abspath(path), False
        self.win.remember(self.path)
        self.win.update_title()
        board = vals.get('board')
        if board and not os.path.exists(board):
            notes = notes + [f"board not found: {board} (generated examples: see the commands at the top of the file)"]
        self.win.statusBar().showMessage('; '.join(notes) if notes else f"opened {path}", 0 if notes else 5000)
        self.win.board_loaded()                                     # its last run, and a fresh preview
        return True

    def save(self):
        if not self.path:
            return self.save_as()
        return self._write(self.path)

    def save_as(self):
        start = self.path or os.path.join(self._start_dir(), 'config.toml')
        path, _ = QFileDialog.getSaveFileName(self, 'Save the config as', start, 'TOML (*.toml)')
        if not path:
            return False
        if not path.endswith('.toml'):
            path += '.toml'
        return self._write(path)

    def _write(self, path):
        try:
            save_config(path, self.values(), template=self.path)       # keeps the comments of the loaded file
        except Exception as e:
            QMessageBox.warning(self, 'Config', f"could not save {path}: {e}")
            return False
        self.path, self.dirty = os.path.abspath(path), False
        self.win.remember(self.path)
        self.win.update_title()
        self.win.statusBar().showMessage(f"saved {path}", 5000)
        return True


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


class ResultsTab(QWidget):
    """The Results page: the S-parameters of every solver and, for an antenna, its gain, efficiency and pattern
    cuts, as subplots you add and remove (splot.SPlot). The plots of a page are remembered: one layout for
    S-parameters, one for antennas. Results that are curves of another kind (a rail's impedance, a near field's
    spectrum: curves.py) take the page instead (curveplot.CurvePlot). Compare with lays other runs of the same
    kind over the one shown."""
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
        self.folder_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.win.out_dir())))
        top.addWidget(self.folder_btn)
        lay.addLayout(top)
        from .steering import SteeringBar
        self.steer = SteeringBar()
        lay.addWidget(self.steer)
        self.steers = []
        self.link_steering(self.steer)
        self.splot = SPlot()
        self.splot.layout_changed.connect(self._save_layout)
        self.curveplot = CurvePlot()
        self.views = QStackedWidget()                               # the S-parameter plots, or an analysis's curves
        self.views.addWidget(self.splot)
        self.views.addWidget(self.curveplot)
        lay.addWidget(self.views, 1)
        self.report, self.added, self._files, self.out, self._mode = None, [], [], None, None
        self.curves, self.added_curves = None, []                   # the curves shown (None: S-parameters), others'
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
        """What the page shows: 'rf' (S-parameters, antenna) or the analysis its curves are of ('pdn', 'mqs')."""
        return self.curves.kind if self.curves is not None else 'rf'

    def compared(self):
        """The folders laid over the run shown (of its kind)."""
        if self.curves is not None:
            return [o.folder for o in self.added_curves if o.kind == self.curves.kind]
        return [d for _label, _files, d in self.added]

    def add_folder(self, d):
        """Another run over the one shown: its S-parameters, or its curves when the page shows an analysis's
        (the same kind only). False: nothing of that kind in the folder."""
        d = os.path.abspath(d)
        if d in self.compared():
            return True
        if self.curves is not None:
            cs = load_curves(d)
            if cs is None or cs.kind != self.curves.kind:
                return False
            self.added_curves.append(cs)
            self._show_curves()
            return True
        files = find_results(d)
        if not files:
            return False
        self.added.append((os.path.basename(os.path.normpath(d)) or d, files, d))
        self.show(self._files)
        return True

    def remove_folder(self, d=None):
        """One compared run off the page (None: all of the kind shown)."""
        if self.curves is not None:
            self.added_curves = [o for o in self.added_curves if o.kind != self.curves.kind or (d and o.folder != d)]
            self._show_curves()
        else:
            self.added = [a for a in self.added if d and a[2] != d]
            self.show(self._files)

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

    def load_curves(self, out_dir):
        """A folder's curves (curves.load_curves) onto the page in place of the S-parameter plots; False: it has
        none, and the page shows S-parameters."""
        self.curves = load_curves(os.path.abspath(out_dir)) if out_dir else None
        self._show_curves()
        return self.curves is not None

    def _show_curves(self):
        cs = self.curves
        self.views.setCurrentWidget(self.curveplot if cs is not None else self.splot)
        if cs is None:
            return
        others = [o for o in self.added_curves if o.kind == cs.kind and o.folder != cs.folder]
        self.curveplot.set_sets(cs, others)
        self.which.hide()
        self.steer.hide()
        self.set_notes([], [])
        self.report = None
        self.info.setText(cs.info + (f"  ·  with {', '.join(o.label for o in others)}" if others else ''))

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

    def show(self, files, compare=None):
        """The S-parameters of a run's files (openEMS, mom25d, line model) and a compare file."""
        from .traces import load_traces
        self._files = list(files)
        if self.curves is not None:                                 # an analysis's curves have the page
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


class SolversDialog(QDialog):
    """Help > Solvers and hardware: the solvers this machine can run (✔ / ✖ and why), the GPU, the memory, and
    the last preview's estimates."""
    def __init__(self, win, panel):
        super().__init__(win)
        self.setWindowTitle('Solvers and hardware - kicad2ems')
        self.setModal(False)
        lay = QVBoxLayout(self)
        lay.addWidget(panel)
        row = QHBoxLayout()
        row.addStretch(1)
        b = QPushButton('Close')
        b.clicked.connect(self.close)
        row.addWidget(b)
        lay.addLayout(row)
        self.resize(780, 660)


class ViewerWindow(QWidget):
    """A second Viewer, its own window: another run of the board beside the one the main Viewer shows (a drop
    map against the last one's, an S-parameter run's fields against another's). Its runs are the main window's
    Results of choice, refreshed when it opens."""
    def __init__(self, win):
        super().__init__(None, Qt.Window)
        self.win = win
        self.setWindowTitle('Viewer - kicad2ems')
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel('Results of'))
        self.runs = QComboBox()
        self.runs.setMinimumWidth(320)
        self.runs.activated.connect(lambda i: self.show_run(self.runs.itemData(i)))
        row.addWidget(self.runs, 1)
        lay.addLayout(row)
        self.viewer = Viewer(win)
        lay.addWidget(self.viewer, 1)
        self.resize(1100, 760)

    def refresh(self, select=None):
        keep = select or self.runs.currentData()
        self.runs.clear()
        for src in self.win.sources():
            self.runs.addItem(src['label'], src['folder'])
        i = self.runs.findData(keep) if keep else -1
        if i < 0:                                                   # the run before the one the main Viewer shows
            here = self.win.runs_box.currentData()
            i = next((k + 1 for k in range(self.runs.count() - 1) if self.runs.itemData(k) == here), 0)
            i = min(i, self.runs.count() - 1)
        if i >= 0:
            self.runs.setCurrentIndex(i)
            self.show_run(self.runs.itemData(i))

    def show_run(self, folder):
        if folder and os.path.isdir(folder):
            self.viewer.load(folder)
            if self.win.viewer.view() in self.viewer.buttons and self.viewer.buttons[self.win.viewer.view()].isEnabled():
                self.viewer.set_view(self.win.viewer.view())        # the same view as the main one
            here = self.win.viewer.cuts.src
            if here is not None:                                    # and the same dump, when it has it
                self.viewer.show_dump(here.label)
            self.setWindowTitle(f"{self.runs.currentText()} - Viewer - kicad2ems")


class MainWindow(QMainWindow):
    def __init__(self, config=None):
        super().__init__()
        self.setWindowTitle('kicad2ems')
        self.qsettings = QSettings('kicad2ems', 'gui')
        self.proc, self.tail, self.files, self.current, self.ticks = None, None, [], None, 0
        self._traceback = self._stopping = False
        self.setup, self.runtab, self.results = SetupTab(self), RunTab(self), ResultsTab(self)
        self.viewer = Viewer(self)
        self.filter = FilterTab(self)
        self.pdn = PdnTab(self)
        self.mqs = MqsTab(self)
        self.circuit = PowerCircuitTab(self)
        self._study()
        self.fields, self.volume = self.viewer.cuts, self.viewer.volume      # the field views, inside the viewer
        if getattr(self.volume, 'steer', None) is not None:          # its Far field section steers too
            self.results.link_steering(self.volume.steer)
        self.system = SystemPanel()                                 # the Solvers window's content: checked now,
        self.system.ready.connect(self.setup.set_availability)      # so the tick boxes can say what cannot run
        self.meters = MemoryMeters()                                # the status bar: RAM, GPU, the run's memory
        self.system.ready.connect(self.meters.set_info)
        self.system.ready.connect(lambda *_: self.update_estimate())
        self._est_basis = None                                      # the settings the estimates were made with
        self.solvers_dialog = SolversDialog(self, self.system)
        # the study (the board, the analyses, the selected one's settings): a dock of the window; the pages:
        # Viewer, Run, Results and each analysis's own (tabbed, split or floated)
        sd = QDockWidget('Study', self)
        sd.setObjectName('Settings')                                # its name in saved layouts, from when it was
        sd.setWidget(self.setup)
        sd.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.LeftDockWidgetArea, sd)
        self.settings_dock = sd
        self.work = QMainWindow()
        self.work.setObjectName('work')
        self.work.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks | QMainWindow.AllowNestedDocks)
        self.work.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)
        hidden = QWidget()
        hidden.hide()
        self.work.setCentralWidget(hidden)                          # the pages take the whole workspace
        self.docks = {}
        for name, w in zip(PANELS, (self.viewer, self.runtab, self.results, self.filter, self.pdn, self.mqs, self.circuit)):
            d = QDockWidget(TITLES.get(name, name), self.work)
            d.setObjectName(name)
            d.setWidget(w)
            # closable: a page can be hidden and shown again (View menu); not closable, a floated page the window
            # manager closed (or that went behind the window) had no way back, its View action disabled
            d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable |
                          QDockWidget.DockWidgetClosable)
            d.topLevelChanged.connect(lambda floating, d=d: floating and QTimer.singleShot(100, lambda: self._fit_floating(d)))
            self.work.addDockWidget(Qt.TopDockWidgetArea, d)
            if self.docks:
                self.work.tabifyDockWidget(self.docks[PANELS[0]], d)
            self.docks[name] = d
            key = next((a.key for a in ANALYSES if a.page == name), None)
            if key:                                                 # an analysis's page in front: its settings
                d.visibilityChanged.connect(lambda on, k=key: on and self._study_ready and self.study.select(k))
        self.docks[PANELS[0]].raise_()
        self.setCentralWidget(self.work)
        self._toolbar()
        self._menus()
        self.statusBar().addPermanentWidget(self.meters)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self._restore_shape()
        self.update_title()
        self._study_ready = True
        if config:
            self.setup.load(config)

    # ---- the study: the analyses, which a Run includes, their settings in the dock ----
    def _study(self):
        """The analyses' list into the settings dock, with each page's own settings under it (the pages keep
        their results); the ticks of the last session (the first time: S-parameters, as Run always did)."""
        from . import pdntab, mqstab
        self._study_ready = False
        self.queue, self.job, self._job_t0, self._queue_preview, self._queue_stopped = [], None, 0.0, False, False
        self.pages = {'pdn': self.pdn, 'mqs': self.mqs, 'circuit': self.circuit}
        self.study = StudyList()
        panels = {k: p.settings_panel() for k, p in self.pages.items()}
        for a in ANALYSES:
            if a.planned:                                           # no tool, so no settings: what it will be
                note = QLabel(a.note)
                note.setWordWrap(True)
                note.setEnabled(False)
                note.setContentsMargins(6, 0, 6, 0)
                panels[a.key] = note
        self.setup.set_study(self.study, panels)
        for key, mod in (('pdn', pdntab), ('mqs', mqstab)):
            if self.pages[key].desc is None:
                self.study.set_available(key, False, mod.why_not() or pdntab.QS_PIP)
        if not self.circuit.run_btn.isEnabled():                    # its template could not be made: why
            self.study.set_available('circuit', False, self.circuit.status.text())
        for key, page in self.pages.items():
            self.runtab.add_log(key, BY_KEY[key].title, page.log)
        saved = self.qsettings.value('study/ticked')
        saved = ['rf'] if saved is None else ([saved] if isinstance(saved, str) else list(saved))
        self.study.set_ticked([k for k in saved if k in BY_KEY])
        self.study.opened.connect(self.show_analysis)
        self.study.run_one.connect(lambda k: self.run_study(only=k))

    def ticks_changed(self):
        if getattr(self, '_study_ready', False):
            self.qsettings.setValue('study/ticked', self.study.ticked() or '')
            self._page_visibility()

    def show_analysis(self, key):
        """An analysis's page in front (S-parameters: Results), its settings in the dock."""
        self.study.select(key)
        if key in BY_KEY and not BY_KEY[key].planned:
            self.show_panel(BY_KEY[key].page or 'Results')

    def busy(self):
        """A run of the window's or a tool of a page's is going."""
        return (self.proc is not None or self.job is not None or bool(self.queue)
                or any(p.proc is not None for p in self.pages.values()))

    def run_study(self, preview=False, only=None):
        """Run (preview) the ticked analyses, one after the other, each after what it starts from; only: that
        analysis alone. One that cannot start (a setting missing) says why in the list, and the rest go on,
        except those that start from it."""
        if self.busy():
            QMessageBox.information(self, 'Busy', 'A run is going: stop it first')
            return
        keys = [only] if only else run_order(self.study.ticked(), preview, self.study.available())
        if only and (only in self.study.why or (preview and not BY_KEY[only].preview)):
            keys = []
        if not keys:
            QMessageBox.warning(self, 'Study', 'None of the ticked analyses has a preview: tick S-parameters or '
                                'Near field under Analyses' if preview else 'Tick an analysis under Analyses first')
            return
        self.queue, self._queue_preview, self._queue_stopped = list(keys), preview, False
        self.runtab.set_jobs([(k, BY_KEY[k].title) for k in keys])
        for k in keys:
            self.study.set_state(k, 'queued', 'gray')
        self._next_job()

    def _next_job(self):
        import time
        if self.job is not None:                                    # one at a time
            return
        while self.queue:
            key = self.queue.pop(0)
            self.job, self._job_t0 = key, time.monotonic()
            why = self._start_job(key, self._queue_preview)
            if why is None:
                self._job_state(key, 'running')
                self.acts['Stop'].setEnabled(True)
                self.runtab.stop_btn.setEnabled(True)
                self.show_panel('Run', front=not self._queue_preview)
                return
            self._job_state(key, f"not started: {why}", bad=True)
            self._drop_after(key)
        self.job = None
        self.acts['Stop'].setEnabled(self.proc is not None)
        self.runtab.stop_btn.setEnabled(self.proc is not None)

    def _start_job(self, key, preview):
        """Start one analysis; None, or why it did not start."""
        if key == 'rf':
            return self.start(preview)
        page = self.pages[key]
        page.start(preview=True) if preview else page.start()
        proc = page.proc
        if proc is None:                                            # the page said why on its status line
            return page.status.text() or 'see its page'
        proc.finished.connect(lambda code, _st=None, k=key: self._job_done(k, code))
        proc.errorOccurred.connect(lambda err, k=key: err == QProcess.FailedToStart and self._job_done(k, -1))
        return None

    def _job_state(self, key, text, bad=False, seconds=None):
        self.runtab.job_state(key, text, seconds)
        self.study.set_state(key, text, 'bad' if bad else '')
        if key != 'rf':                                             # kicad2ems's own run says its stages itself
            self.runtab.stage.setText(f"{BY_KEY[key].title}: {text}")
            if text == 'running':
                self.runtab.own_plots(False)

    def _drop_after(self, key):
        """The queued analyses that start from one that failed: not run."""
        for k in [k for k in self.queue if k in dependents(key)]:
            self.queue.remove(k)
            self._job_state(k, f"not run: {BY_KEY[key].title} did not finish", bad=True)

    def _job_done(self, key, code):
        """An analysis of the queue ended: its state and time, then the next (the last one's page in front)."""
        import time
        if self.job != key:
            return
        took = time.monotonic() - self._job_t0
        if code == 0:
            self._job_state(key, f"done {time.strftime('%H:%M')}", seconds=took)
            out = getattr(self.pages.get(key), 'out', None)
            if key in ('pdn', 'mqs') and out and os.path.isdir(str(out)):   # its maps and curves, its summary
                self.refresh_runs(select=str(out))
                self.open_results(str(out), quiet=True, front=False)
        else:
            self._job_state(key, 'stopped' if self._queue_stopped else f"failed (exit {code})",
                            bad=not self._queue_stopped, seconds=took)
            self._drop_after(key)
        self.job = None
        if self.queue:                                              # after this one's own end is dealt with
            QTimer.singleShot(0, self._next_job)
            return
        self._next_job()                                            # none left: the toolbar's Stop
        if key != 'rf' and code == 0:                               # S-parameters: _finished chose its page
            if key == 'mqs' and self._queue_preview:                # a mesh preview: the mesh, in the plan
                self.viewer.set_view('Plan')
                self.show_panel('Viewer')
            else:
                self.show_panel(BY_KEY[key].page)

    # ---- the window's shape: remembered between sessions ----
    def _splitters(self):
        return {'viewer': self.viewer.split, 'results': self.results.splot.split, 'filter': self.filter.split,
                'pdn': self.pdn.split, 'mqs': self.mqs.split, 'circuit': self.circuit.split,
                **({'viewer3d': self.volume.split} if getattr(self.volume, 'split', None) is not None else {})}

    def _restore_shape(self):
        """The size, position, docks and splitters of the last session; the first time, most of the screen."""
        q = self.qsettings
        geo = q.value('window/geometry')
        if geo is None or not self.restoreGeometry(geo):
            scr = self.screen().availableGeometry() if self.screen() else None
            if scr is not None and scr.width() > 0:
                w, h = int(scr.width() * 0.85), int(scr.height() * 0.85)
                self.resize(min(w, 1700), min(h, 1050))
                self.move(scr.x() + (scr.width() - self.width()) // 2, scr.y() + (scr.height() - self.height()) // 2)
            else:
                self.resize(1500, 950)
        for key, obj in (('window/state', self), ('work/state', self.work)):
            st = q.value(key)
            if st is not None:
                obj.restoreState(st, STATE_VERSION)
        for name, sp in self._splitters().items():
            st = q.value(f"splitter/{name}")
            if st is not None:
                sp.restoreState(st)
        saved = q.value('work/pages')
        saved = [saved] if isinstance(saved, str) else list(saved or PANELS[:3])    # before the Filter page: 3
        for name, d in self.docks.items():
            if name not in saved:                                   # a page newer than the saved layout: Qt would
                d.setFloating(False)                                # leave it floating; tabbed with the others
                self.work.addDockWidget(Qt.TopDockWidgetArea, d)
                self.work.tabifyDockWidget(self.docks[PANELS[0]], d)
            d.show()                                                # a page closed last time: back
        self._page_visibility(opening=True)
        self.docks[PANELS[0]].raise_()

    def _page_visibility(self, opening=False):
        """The pages that come and go: Filter Synthesis closed when the window opens (the toolbar's Filter, or
        View, opens it); Circuit there while Circuit is ticked under Analyses, and gone when it is unticked."""
        if opening:
            for name in ON_DEMAND:
                self.docks[name].hide()
        ticked = set(self.study.ticked())
        for name, key in FOLLOWS_TICK.items():
            d = self.docks[name]
            if key in ticked and d.isHidden():
                if d.isFloating() and not opening:
                    d.setFloating(False)
                d.show()
            elif key not in ticked and not d.isHidden() and not (self.job == key or self.queue and key in self.queue):
                d.hide()

    def _save_shape(self):
        q = self.qsettings
        q.setValue('window/geometry', self.saveGeometry())
        q.setValue('window/state', self.saveState(STATE_VERSION))
        q.setValue('work/state', self.work.saveState(STATE_VERSION))
        q.setValue('work/pages', list(PANELS))
        for name, sp in self._splitters().items():
            q.setValue(f"splitter/{name}", sp.saveState())

    def reset_layout(self):
        """The pages tabbed again, the settings on the left, the splitters at their first sizes."""
        self.settings_dock.setFloating(False)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.settings_dock)
        self.settings_dock.show()
        for d in self.docks.values():
            d.setFloating(False)
            self.work.addDockWidget(Qt.TopDockWidgetArea, d)
            d.show()
        for name in PANELS[1:]:
            self.work.tabifyDockWidget(self.docks[PANELS[0]], self.docks[name])
        self._page_visibility(opening=True)
        self.docks[PANELS[0]].raise_()
        self.viewer.split.setSizes([880, 380])
        self.results.splot.split.setSizes([220, 1000])

    # ---- toolbar, pages, menus, title, recent files ----
    def _toolbar(self):
        tb = QToolBar('Main')
        tb.setObjectName('Main toolbar')
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tb.setMovable(False)
        st = self.style()
        self.acts = {}
        for name, icon, tip, slot in (
                ('New', 'SP_FileIcon', 'New settings (Ctrl+N)', self.setup.new),
                ('Open', 'SP_DialogOpenButton', 'Open a config (Ctrl+O)', lambda: self.setup.load()),
                ('Save', 'SP_DialogSaveButton', 'Save the config (Ctrl+S)', self.setup.save),
                ('Save as', 'SP_DriveFDIcon', 'Save the config as (Ctrl+Shift+S)', self.setup.save_as),
                (None, None, None, None),
                ('Preview', 'SP_FileDialogContentsView', 'The ticked analyses\' models and meshes (the line model too), '
                 'no solve (Ctrl+P)', self.preview),
                ('Run', 'SP_MediaPlay', 'Run the ticked analyses, one after the other (Ctrl+R)', self.run),
                ('Stop', 'SP_MediaStop', 'Stop the run and what is queued after it (Ctrl+.)', self.stop),
                (None, None, None, None),
                ('Results', 'SP_DirOpenIcon', 'Open a results folder', self.results._load),
                ('Report', 'SP_FileDialogInfoView', 'Open the HTML report of the results', self.results.open_report),
                (None, None, None, None),
                ('Filter', WAND, 'Filter Synthesis: design a microstrip filter with dfsynth',
                 lambda: self.show_panel('Filter'))):
            if name is None:
                tb.addSeparator()
                continue
            a = QAction(QIcon(icon) if os.path.isfile(icon) else st.standardIcon(getattr(QStyle.StandardPixmap, icon)),
                        name, self)
            a.setToolTip(tip)
            a.triggered.connect(slot)
            tb.addAction(a)
            self.acts[name] = a
        self.acts['Stop'].setEnabled(False)
        self.acts['Report'].setEnabled(False)
        self.runs_box = QComboBox()                                 # whose results the pages show
        self.runs_box.setToolTip("the results the Viewer and Results pages show: this board's preview, or one of "
                                 "its runs (each in its own folder: <board>_<date>_<time>)")
        self.runs_box.setMinimumWidth(260)
        self.runs_box.activated.connect(lambda i: self._pick_run(self.runs_box.itemData(i)))
        tb.addSeparator()
        tb.addWidget(QLabel(' Results of '))
        tb.addWidget(self.runs_box)
        self.est_btn = EstimateButton()                             # beside Run / Stop: what a run would take
        self.est_btn.clicked.connect(self.show_solvers)
        acts = tb.actions()
        tb.insertWidget(acts[acts.index(self.acts['Results']) - 1], self.est_btn)     # before Results' separator
        self.addToolBar(Qt.TopToolBarArea, tb)

    def show_panel(self, name, front=True):
        """Open a page (it may have been closed) and, front: bring it to the front of its tab group. A floated page
        that was closed comes back docked: on Wayland a separate window can't be raised or placed by the app."""
        d = self.docks[name]
        if d.isFloating() and not d.isVisible():
            d.setFloating(False)
        closed = d.isHidden()
        d.show()
        if closed and not d.isFloating() and name != PANELS[0] and \
                d not in self.work.tabifiedDockWidgets(self.docks[PANELS[0]]):    # a page that starts closed: tabbed
            self.work.tabifyDockWidget(self.docks[PANELS[0]], d)            # with the others, not beside them
        if front:
            d.raise_()

    def _fit_floating(self, d):
        """A page just floated: at most 80 % of the screen, centred on the window (a floated page as wide as the
        whole workspace could open partly off the screen)."""
        scr = (self.screen() or d.screen()).availableGeometry()
        w, h = min(d.width(), int(0.8 * scr.width())), min(d.height(), int(0.8 * scr.height()))
        d.resize(w, h)
        c = self.frameGeometry().center()
        d.move(max(scr.x(), min(c.x() - w // 2, scr.right() - w)), max(scr.y(), min(c.y() - h // 2, scr.bottom() - h)))

    def second_viewer(self):
        """A Viewer window of its own, showing another run of the board (ViewerWindow); one at a time."""
        if getattr(self, '_viewer2', None) is None:
            self._viewer2 = ViewerWindow(self)
        self._viewer2.refresh()
        self._viewer2.show()
        self._viewer2.raise_()
        return self._viewer2

    def show_solvers(self):
        """The Solvers window: what can run here, the GPU, the memory, the last preview's estimates."""
        self.solvers_dialog.show()
        self.solvers_dialog.raise_()
        self.solvers_dialog.activateWindow()

    def _menus(self):
        fm = self.menuBar().addMenu('&File')
        for text, key, slot in (('&New', QKeySequence.New, self.setup.new),
                                ('&Open…', QKeySequence.Open, lambda: self.setup.load()),
                                (None, None, None),
                                ('&Save', QKeySequence.Save, self.setup.save),
                                ('Save &as…', QKeySequence.SaveAs, self.setup.save_as)):
            if text is None:
                self.recent_menu = fm.addMenu('Open &recent')
                self.examples_menu = fm.addMenu('&Examples')
                continue
            a = QAction(text, self)
            a.setShortcut(key)
            a.triggered.connect(slot)
            fm.addAction(a)
        fm.addSeparator()
        a = QAction(QIcon(WAND), 'New &filter (Filter Synthesis)…', self)
        a.setToolTip('design a microstrip filter with dfsynth')
        a.triggered.connect(lambda: self.show_panel('Filter'))
        fm.addAction(a)
        a = QAction('Open &results folder…', self)
        a.triggered.connect(self.results._load)
        fm.addAction(a)
        fm.addSeparator()
        a = QAction('&Quit', self)
        a.setShortcut(QKeySequence.Quit)
        a.triggered.connect(self.close)
        fm.addAction(a)
        vm = self.menuBar().addMenu('&View')
        vm.addAction(self.settings_dock.toggleViewAction())
        for name in PANELS:
            a = self.docks[name].toggleViewAction()
            a.triggered.connect(lambda on, d=self.docks[name]: on and d.isFloating() and d.setFloating(False))  # back, docked
            vm.addAction(a)
        vm.addSeparator()
        for name in VIEWS:
            a = QAction(f"Viewer: {name}", self)
            a.triggered.connect(lambda _=False, n=name: (self.show_panel('Viewer'), self.viewer.set_view(n)))
            vm.addAction(a)
        vm.addSeparator()
        a = QAction('A second &Viewer…', self)
        a.setShortcut(QKeySequence('Ctrl+Shift+V'))
        a.setToolTip('another run of this board in a window of its own, beside the Viewer')
        a.triggered.connect(self.second_viewer)
        vm.addAction(a)
        vm.addSeparator()
        a = QAction('&Reset layout', self)
        a.triggered.connect(self.reset_layout)
        vm.addAction(a)
        rm = self.menuBar().addMenu('&Run')
        for text, key, slot in (('&Preview', 'Ctrl+P', self.preview), ('&Run', 'Ctrl+R', self.run),
                                ('Run the selected &analysis alone', 'Ctrl+Shift+R',
                                 lambda: self.run_study(only=self.study.current())),
                                ('&Stop', 'Ctrl+.', self.stop)):
            a = QAction(text, self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(slot)
            rm.addAction(a)
        hm = self.menuBar().addMenu('&Help')
        a = QAction('&Solvers and hardware…', self)
        a.triggered.connect(self.show_solvers)
        hm.addAction(a)
        a = QAction('&Documentation', self)
        a.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(DOCS)))
        hm.addAction(a)
        self._fill_recent()
        self._fill_examples()

    def _fill_examples(self):
        """kicad2ems's examples (installed with it): one opens from a folder of the user's, where it is copied, its
        board made if it is generated."""
        from kicad2ems.api.frontend import examples
        self.examples_menu.clear()
        names = list(examples())
        for n in names:
            a = QAction(n, self)
            a.triggered.connect(lambda _=False, n=n: self.open_example(n))
            self.examples_menu.addAction(a)
        self.examples_menu.setEnabled(bool(names))

    def open_example(self, name):
        from kicad2ems.api.frontend import prepare_example
        if not self.setup.maybe_save():
            return
        self.statusBar().showMessage(f"preparing the example {name}...")
        QApplication.processEvents()
        try:
            path = prepare_example(name)
        except Exception as e:                                      # a generator that failed: say so, keep the form
            QMessageBox.warning(self, 'Examples', f"{name}: {type(e).__name__}: {e}")
            return
        self.setup.load(path)

    def recent(self):
        v = self.qsettings.value('recent', [])
        v = [v] if isinstance(v, str) else list(v or [])
        return [p for p in v if os.path.exists(p)]

    def remember(self, path):
        r = [path] + [p for p in self.recent() if p != path]
        self.qsettings.setValue('recent', r[:MAX_RECENT])
        self._fill_recent()

    def _fill_recent(self):
        self.recent_menu.clear()
        r = self.recent()
        for p in r:
            a = QAction(p, self)
            a.triggered.connect(lambda _=False, p=p: self._open(p))
            self.recent_menu.addAction(a)
        self.recent_menu.setEnabled(bool(r))

    def _open(self, path):
        if self.setup.maybe_save():
            self.setup.load(path)

    def _basis(self):
        """The settings an estimate depends on: all but the solver choice (which the estimate follows) and where the
        results go."""
        v = self.setup.values()
        for k in ('solvers', 'out', 'compare', 'no_report', 'events'):
            v.pop(k, None)
        return json.dumps(v, sort_keys=True, default=str)

    def new_estimates(self, est):
        """A preview's estimates: beside the tick boxes and in the toolbar, for the settings as they are now."""
        self.setup.set_estimates(est)
        self._est_basis = self._basis() if est else None
        self.update_estimate()

    def update_estimate(self):
        """The toolbar's estimate for the solvers ticked now (greyed when other settings changed since)."""
        if not hasattr(self, 'est_btn'):
            return
        from .meters import estimate
        est = self.setup.est
        if not est:
            self.est_btn.show_estimate(None, has_preview=False)
            return
        info = self.system.info or {}
        usable = {x['name'] for x in info.get('solvers', []) if x['ok']} if info.get('solvers') else None
        e = estimate(est, self.setup.values(), usable, self.meters.free_gb)
        labels = {x['name']: x['label'].split(' (')[0] for x in info.get('solvers', [])}
        self.est_btn.show_estimate(e, stale=self._est_basis is not None and self._basis() != self._est_basis,
                                   labels=labels)

    def update_title(self):
        name = os.path.basename(self.setup.path) if self.setup.path else 'untitled'
        self.setWindowTitle(f"{name}{'*' if self.setup.dirty else ''} - kicad2ems")

    def closeEvent(self, ev):
        if self.setup.maybe_save():
            self._save_shape()
            self.circuit.stop()
            if self.circuit.proc is not None:self.circuit.proc.waitForFinished(3000)
            self.system.stop()
            self.meters.stop()
            self.solvers_dialog.close()
            if getattr(self, '_viewer2', None) is not None:
                self._viewer2.close()
            ev.accept()
        else:
            ev.ignore()

    # ---- results into the pages ----
    def open_results(self, out_dir, quiet=False, front=True):
        """The results already in a folder, whatever analysis wrote them: the viewer (board, meshes, line model,
        dumps, far field), the results page (S-parameters and antenna, or the analysis's curves) and, for a
        Power integrity or Near field result, its page's summary; front: the page with something new in front."""
        from .runfolders import tool_kind
        files = find_results(out_dir)
        ant = self.results.load_antenna(out_dir)                    # first: it decides the page's plots
        curves = self.results.load_curves(out_dir)                  # an analysis's curves: the page is theirs
        if files:
            self.results.show(files)
        seen = self.viewer.load(out_dir)
        kind = tool_kind(out_dir)
        if kind in self.pages:
            self._show_tool_result(kind, out_dir)
        if self.system.load_estimates(out_dir):
            self.new_estimates(self.system.est)
        self.acts['Report'].setEnabled(bool(self.results.report))
        i = self.runs_box.findData(out_dir)
        if i >= 0:
            self.runs_box.setCurrentIndex(i)
        if front and (files or ant):
            self.show_panel('Results')
        elif front and seen:
            self.show_panel('Viewer')
        elif front and curves:
            self.show_panel('Results')
        if not quiet and not (files or seen or ant or curves):
            QMessageBox.information(self, 'Results', f"No results in {out_dir}")

    def _show_tool_result(self, kind, out_dir):
        """A Power integrity or Near field folder: its page's summary, and in the viewer the map to start from
        (the rail's drop on the layer that drops most; the near field's own mesh in the plan)."""
        from . import pdntab, mqstab
        page = self.pages[kind]
        try:
            res = (pdntab if kind == 'pdn' else mqstab).load_result(out_dir)
        except (OSError, ValueError, KeyError):
            res = None
        if res is None:
            return
        page.out = out_dir
        page.show_result(res)
        if kind == 'pdn':
            drops = [s for s in self.viewer.cuts.srcs if s.field == 'V' and s.run == 'power']
            if drops:
                self.viewer.show_dump(max(drops, key=lambda s: float(abs(s.load(0)[1]).max())).label)
        elif self.viewer.plan.mesh.findData('mqs') >= 0:
            self.viewer.plan.mesh.setCurrentIndex(self.viewer.plan.mesh.findData('mqs'))

    # ---- this board's runs: a folder each (runfolders.py) ----
    def board_loaded(self):
        """A config was opened: its newest run into the pages, and a preview to show the board as it is now (the
        Viewer then shows the preview; the toolbar's Results of picks a run instead)."""
        from .runfolders import preview_dir
        rs = self.refresh_runs()
        board = self.setup.values().get('board')
        if rs:
            self.open_results(rs[0][0], quiet=True)
        else:                                                       # nothing of the last board left in the pages
            self.results.load_antenna(None)
            self.results.show([])
            self.viewer.load(preview_dir(self.out_dir(), board) if board else os.path.join(os.getcwd(), 'out', '-'))
        QTimer.singleShot(0, self._auto_preview)

    def _auto_preview(self):
        """The preview a newly opened config gets: only in a window on the screen (not a test's), when idle."""
        board = self.setup.values().get('board')
        if self.isVisible() and board and os.path.exists(board) and not self.busy():
            self.start(True)                                        # kicad2ems's own: the board, whatever is ticked

    def sources(self):
        """This board's results, as the Results of box lists them: [{folder, kind, label}], kind 'preview', 'rf'
        (a run of kicad2ems's own), 'pdn' or 'mqs'; each kind's newest first."""
        from .runfolders import runs, preview_dir, tool_runs
        try:
            vals = self.setup.values()
        except ValueError:                                          # a field half typed
            return []
        board = vals.get('board')
        if not board:
            return []
        base = self.out_dir(vals)
        out = []
        pv = preview_dir(base, board)
        if os.path.isdir(pv):
            out.append(dict(folder=pv, kind='preview', label='preview'))
        out += [dict(folder=d, kind='rf', label=f"run {label}") for d, label in runs(base, board)]
        out += [dict(folder=d, kind=kind, label=label) for d, kind, label in tool_runs(base, board)]
        return out

    def refresh_runs(self, select=None):
        """The Results of choice: this board's preview and runs, then its Power integrity and Near field results,
        each kind's newest first; select: the folder to show as chosen. Returns the runs [(folder, label)]."""
        srcs = self.sources()
        keep = select or self.runs_box.currentData()
        self.runs_box.blockSignals(True)
        self.runs_box.clear()
        last = None
        for src in srcs:
            group = 'rf' if src['kind'] in ('preview', 'rf') else src['kind']
            if last is not None and group != last:
                self.runs_box.insertSeparator(self.runs_box.count())
            last = group
            self.runs_box.addItem(src['label'], src['folder'])
        i = self.runs_box.findData(keep) if keep else -1
        self.runs_box.setCurrentIndex(i if i >= 0 else 0)
        self.runs_box.blockSignals(False)
        return [(src['folder'], src['label'][4:]) for src in srcs if src['kind'] == 'rf']

    def tool_out(self, kind, board, name, preview=False):
        """Where a page's tool writes a run started here: a folder of its own under the output folder (the
        board's 'out', or the Output setting), so earlier runs stay to compare with; a preview: one per board."""
        from kicad2ems.api.frontend import default_out
        from .runfolders import tool_dir, tool_preview_dir
        try:
            base = self.setup.values().get('out')
        except ValueError:
            base = None
        base = base or default_out(board)
        return tool_preview_dir(base, board, kind) if preview else tool_dir(base, board, kind, name)

    def _pick_run(self, folder):
        """Results of: a run of kicad2ems's own brings its page forward, as it did; another analysis's results
        go into the pages as they stand (the one in front is usually the one being compared)."""
        from .runfolders import tool_kind
        if folder and os.path.isdir(folder):
            self.open_results(folder, quiet=True, front=tool_kind(folder) is None)

    def out_dir(self, vals=None):
        """The output folder: the form's, else 'out' next to the board (where a run writes), else in the working
        directory."""
        from kicad2ems.api.frontend import default_out
        vals = self.setup.values() if vals is None else vals
        if vals.get('out'):
            return vals['out']
        board = vals.get('board')
        return default_out(board) if board else os.path.join(os.getcwd(), 'out')

    def start(self, preview):
        """Start kicad2ems's own run (the S-parameters analysis) or its preview; None, or why it did not start
        (said in a dialog too when the user started it alone)."""
        def no(title, why):
            if self.job != 'rf' or not self.queue:                  # alone: a dialog; in a queue: the list says it
                (QMessageBox.information if title == 'Busy' else QMessageBox.warning)(self, title, why)
            return why
        if self.proc is not None:
            return no('Busy', 'A run is going: stop it first')
        vals = self.setup.values()
        if not vals.get('board'):
            return no('Setup', 'Choose a board first')
        if not preview and vals.get('solvers') == []:
            return no('Setup', 'Choose a solver under Solvers (or Preview)')
        from .runfolders import run_dir, preview_dir
        base = self.out_dir(vals)                                   # each run in a folder of its own
        self.current = Run(vals, preview_dir(base, vals['board']) if preview else run_dir(base, vals['board']), preview)
        self.files, self._traceback, self._stopping = [], False, False
        self.runtab.reset()
        self.tail = EventTail(self.current.events)
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        # in the output folder: started where the GUI was, the run could import a folder there named like one
        # of its packages (a mom25d/ of the user's) in place of the package
        self.proc.setWorkingDirectory(self.current.out)
        self.proc.readyReadStandardOutput.connect(self._stdout)
        self.proc.finished.connect(self._finished)
        argv = self.current.argv()
        self.proc.start(argv[0], argv[1:])
        self.meters.set_run(self.proc.processId() or None)
        self.runtab.stop_btn.setEnabled(True)
        self.acts['Stop'].setEnabled(True)
        self.runtab.stage.setText('starting…')
        self.runtab.show_log('rf')
        self.show_panel('Run', front=not preview)
        self.timer.start(300)
        return None

    def preview(self):
        self.run_study(preview=True)

    def run(self):
        self.run_study()

    def stop(self):
        """What is queued: not run. The analysis running: a page's tool ends at once; kicad2ems's own run is
        asked to stop at the first press (stop.py: mom25d after the frequency it is solving, openEMS at once
        with what it has, later solvers skipped) and its process ended at the second."""
        for k in self.queue:
            self._job_state(k, 'not run: stopped')
        self.queue = []
        if self.job in self.pages:
            self._queue_stopped = True
            self.pages[self.job].stop()
            return
        if not (self.current and self.proc):
            return
        self._queue_stopped = True
        if self._stopping:
            self.runtab.log.appendPlainText("stop: ending the process")
            self.proc.kill()
            return
        self._stopping = True
        stop_runs(self.current.out)
        self.runtab.log.appendPlainText("stop: requested - the run ends after its current step "
                                        "(press Stop again to end the process at once)")

    def _stdout(self):
        """The process's own output: the log already comes as events, so only errors - a traceback whole."""
        data = bytes(self.proc.readAllStandardOutput()).decode('utf-8', 'replace')
        for line in data.splitlines():
            self._traceback = self._traceback or line.startswith('Traceback')
            if self._traceback or 'error' in line.lower():
                self.runtab.log.appendPlainText(line)

    def poll(self):
        if not self.tail:
            return
        for ev in self.tail.read():
            k = ev.get('kind')
            if k == 'log':
                self.runtab.log.appendPlainText(ev.get('text', ''))
            elif k == 'stage':
                self.runtab.stage.setText(f"stage: {ev.get('name')}")
            elif k == 'status':
                self.runtab.status(ev)
            elif k == 'file':
                self.files.append((ev.get('label', ''), ev.get('path', '')))
            elif k == 'done':
                self.runtab.stage.setText('done' if ev.get('code') in (0, None) else f"ended with code {ev.get('code')}")
        self.ticks += 1
        if self.current and not self.current.preview and self.ticks % 3 == 0:   # field frames, ~1 s
            try:
                self.viewer.follow(self.current.out)
            except Exception as e:                                   # never stop following the run over a frame
                self.runtab.log.appendPlainText(f"field view: {e}")

    def _finished(self, code, _status):
        """The run is over: its results into the pages. A run: Results in front (S-parameters, antenna); a preview:
        the Viewer (the board, its meshes, the line model), and the estimates on the solver tick boxes."""
        self.poll()
        self.timer.stop()
        self.proc = None
        self.meters.set_run(None)
        self.runtab.stop_btn.setEnabled(False)
        self.acts['Stop'].setEnabled(False)
        out = self.current.out
        has_s = any(l.startswith('S-parameters') for l, _ in self.files)
        ant = self.results.load_antenna(out) if not self.current.preview else self.results.load_antenna(None)
        if has_s or not self.current.preview:
            self.results.show(self.files)                            # a preview: the solvers it runs (the line model)
        seen = self.viewer.load(out)
        self.refresh_runs(select=out)
        self.acts['Report'].setEnabled(bool(self.results.report))
        if self.current.preview and self.system.load_estimates(out):
            self.new_estimates(self.system.est)
            self.statusBar().showMessage('preview done: estimates beside the solvers (? for details)', 8000)
        if code:
            self.runtab.stage.setText(f"ended with code {code} - see the log")
            self.show_panel('Run')
        elif self.current.preview:
            self.show_panel('Viewer' if seen else 'Run')
        else:
            self.show_panel('Results' if (has_s or ant) else ('Viewer' if seen else 'Run'))
        self._job_done('rf', code)                                  # in a study run: the next analysis


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    from . import application
    app = application(sys.argv[:1])
    w = MainWindow(argv[0] if argv else None)
    w.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
