"""
kicad2ems GUI (PySide6 + pyqtgraph): set up a study, preview it, watch it, see the results. The window has the
study on the left (the board, the analyses made of it and the settings of the one selected: study.py) and its pages:

    Viewer   the board in 3D or from above, a solver's mesh, the line model coloured by Z0 (pick a section to read
             it), field dumps in place or as cuts (live while the run goes), the far field, the run's plots
    Run      the analyses of the run and where each is, openEMS's energy decay and mom25d's adaptive sweep, the
             log of each
    Results  S-parameters and antenna results as Cartesian, Smith and polar plots you add and remove; an analysis's
             result as its curves, its report to read, or its tables to sort and export
    Filter Synthesis
             design a microstrip filter with dfsynth, validate and tune it on the solvers, open its board here
    Circuit  the circuit analysis's model as a schematic to edit (pcbqs.circuit), when that analysis is installed

The analyses beside S-parameters are plugins kicad2ems's registry holds (kicad2ems.api.frontend.analyses: pcbqs's
power integrity, near field, circuit and thermal). The window knows none of them by name: each one's settings are
a panel in the study made from its options (analysispanel.py), the toolbar's Run starts its command with the rest,
its maps are field dumps the Viewer shows and its report and curves are on the Results page.

Run starts the analyses ticked in the study one after the other (run_study), each after the one it starts from.
Every run is the command-line tool started as a separate process with --events; the GUI follows its event
stream, so a closed window never kills a simulation's results and the GUI needs no openEMS of its own. The
window's size, its docks and splitters, and the Results plots are remembered between sessions.

    kicad2ems-gui [config.toml]
"""
import json, os, sys
import numpy as np
from PySide6.QtCore import Qt, QProcess, QTimer, QUrl, QSettings, Signal
from PySide6.QtGui import QDesktopServices, QAction, QKeySequence, QIcon
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
                               QLineEdit, QCheckBox, QComboBox, QPushButton, QLabel, QPlainTextEdit, QProgressBar,
                               QFileDialog, QScrollArea, QMessageBox, QDockWidget, QToolBar, QStyle, QToolButton,
                               QDialog, QTabWidget, QApplication, QTreeWidget, QTreeWidgetItem, QHeaderView,
                               QStackedWidget, QMenu, QSplitter)
import pyqtgraph as pg
from .runner import (FIELDS, SEMICOLON_LISTS, SECTION_SOLVERS, SECTION_TITLES, TICK, Run, EventTail, stop_runs, settings_values,
                     extra_values, find_results, save_config, solvers_from_form, solver_ticks, basic_keys)
from kicad2ems.api.frontend import G_DUMP
from .splot import SPlot, default_layout
from .curveplot import CurvePlot
from .curves import load_sets
from .reportview import ReportView
from .analysispanel import AnalysisPanel, config_values
from .panels import Section, FlowLayout, NeededList
from .systempanel import SystemPanel
from .viewer import Viewer, VIEWS
from .statusbar import MemoryMeters, EstimateButton
from .meters import duration
from .filtertab import FilterTab
from .study import StudyList, ANALYSES, BY_KEY, RF, run_order, dependents

pg.setConfigOptions(antialias=True, background='w', foreground='k')
DOCS = 'https://github.com/lowprocess/kicad2ems/blob/main/docs/index.md'
MAX_RECENT = 8
EDITORS = {a.page: a.key for a in ANALYSES if a.page and a.key in ('circuit',)}     # an analysis with a page of its
                                                            # own here (the circuit's schematic): {page: its key}
PANELS = ('Viewer', 'Run', 'Results', 'Filter', *EDITORS)
TITLES = {'Filter': 'Filter Synthesis'}                     # a page's tab title, when not its name
LOWER = ('Results', 'Run')                      # the pages under the board in a new window's layout
ON_DEMAND = ('Filter',)                         # pages closed when the window opens: the toolbar's Filter opens it
FOLLOWS_TICK = dict(EDITORS)                    # pages shown while their analysis is ticked (or opened by hand)


def editor_page(key, win):
    """The page of an analysis this window has an editor for: the circuit's schematic and model."""
    from .powercircuittab import PowerCircuitTab
    return {'circuit': PowerCircuitTab}[key](win)
WAND = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wand.svg')
STATE_VERSION = 3                                                   # saved dock layouts of older windows: ignored
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
        # the few settings a run is set up with first (runner.basic_keys), the others under "More settings", in
        # their sections and found by name; the board's others in a section inside the board's
        basic = basic_keys()
        form = lambda box: (lambda f: (f.setContentsMargins(0, 0, 0, 0), f.setRowWrapPolicy(QFormLayout.WrapLongRows),
                                       f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow), f)[-1])(QFormLayout(box))
        basic_box, more_box, board_more = QWidget(), QWidget(), QWidget()
        self.basic_form, self.board_more_form = form(basic_box), form(board_more)
        self.basic_form.setContentsMargins(8, 4, 4, 6)
        more = QVBoxLayout(more_box)
        more.setContentsMargins(0, 0, 0, 0)
        more.setSpacing(2)
        self.find = QLineEdit()
        self.find.setPlaceholderText('Find a setting')
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self._find)
        more.addWidget(self.find)
        rf.addWidget(basic_box)
        self.more = Section('More settings', more_box)
        rf.addWidget(self.more)
        self.rows, self.row_text, self._found = {}, {}, set()      # key: (its form, its row's widget); its label
        top_of = lambda group: left if group == 'Board' else more   # the board: above the analyses, for all
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
                more.addWidget(self.parents[top][0])
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
            into = groups[group] if (key in basic) == (group == 'Board') else \
                self.basic_form if key in basic else self.board_more_form
            if into is self.basic_form and group.split('/')[0] in SECTION_SOLVERS:      # among the first few: whose
                label = f"{group.split('/')[0]}: {label[0].lower()}{label[1:]}"
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
                into.addRow(label, holder)
                self.rows[key], self.row_text[key] = (into, holder), label
            elif key.startswith(TICK):                              # a solver: ticked on the list's RF rows (the
                w.setText(label)                                    # box is its state: not in the form)
                self.solver_labels[key[len(TICK):]] = label
                w.setParent(self)
                w.hide()
            else:
                into.addRow(label, w)
                self.rows[key], self.row_text[key] = (into, w), label
            self.field_labels[key] = None if key.startswith(TICK) else into.labelForField(w)
            self.edits[key] = (w, kind)
            if key == 'mode':                                       # the list's Antenna row says it
                into.setRowVisible(w, False)
                del self.rows[key]
        if self.board_more_form.rowCount() and 'Board' in groups:
            self.board_more = Section('More about the board', board_more)
            groups['Board'].addRow(self.board_more)
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
        left.addStretch(1)
        # the selected question's settings: a dock of their own (self.inspector), under the study's on the left
        right = QVBoxLayout()
        right.setSpacing(2)
        self.panel_title = QLabel('')                               # whose settings follow
        self.panel_title.setStyleSheet('font-weight: bold; padding: 8px 4px 2px 4px;')
        self.panel_title.hide()
        right.addWidget(self.panel_title)
        self.rf_box = QWidget()
        self.rf_box.setLayout(rf)
        self.panels = {'rf': self.rf_box}                           # analysis: its settings (one shown)
        right.addWidget(self.rf_box)
        self.needed = NeededList()                                  # what the selected question's run still needs
        self.needed.hide()
        right.addWidget(self.needed)
        right.addStretch(1)
        self._left = right                                          # (where set_study puts the analyses' panels)

        def scrolled(layout):
            w = QWidget()
            w.setLayout(layout)
            sc = QScrollArea()
            sc.setWidget(w)
            sc.setWidgetResizable(True)
            # a form wraps its rows instead of scrolling sideways: as wide as its narrowest layout, plus room for
            # the vertical scroll bar (a long form shows it, and without that room a sideways one appeared too)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            return sc, w
        (self.scroll, self._lw), (self.inspector, self._rw) = scrolled(left), scrolled(right)
        self._fit_width()
        outer.addWidget(self.scroll)
        self._update_sections()                                     # before any config: nothing ticked, all greyed

    def _fit_width(self):
        """The dock at least as wide as its widest settings (the hidden analyses' too: selecting one must not
        cut its fields off, the form having no sideways scroll bar)."""
        bar = self.scroll.verticalScrollBar().sizeHint().width()
        pad = bar + 2 * self.scroll.frameWidth() + 2
        self.scroll.setMinimumWidth(max(250, min(self._lw.minimumSizeHint().width(), 380) + pad))
        need = max([self._rw.minimumSizeHint().width()] + [p.minimumSizeHint().width() for p in self.panels.values()])
        self.inspector.setMinimumWidth(max(270, min(need, 420) + pad))

    def set_study(self, study, panels):
        """The questions' list under the board, and each run's settings {key: widget} ('rf': the solvers' own
        sections; an analysis: its page's form, moved here): those of the selected question's engines are shown."""
        from .study import ANALYSES
        self.study = study
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(study)
        self.study_note = QLabel("ticked: Preview and Run include it · Answered by: click to choose the engine, "
                                 "or several to compare")
        self.study_note.setWordWrap(True)
        self.study_note.setEnabled(False)                           # greyed: a note, not a setting
        hl.addWidget(self.study_note)
        self.study_section = Section('Questions', holder, expanded=True)
        self.study_slot.addWidget(self.study_section)
        at = self._left.indexOf(self.rf_box) + 1
        self.engine_titles = {}                                     # an analysis: whose settings (several shown)
        for a in ANALYSES:
            w = panels.get(a.key)
            if w is None or a.key in self.panels:
                continue
            lab = QLabel(f"{a.tool}")
            lab.setStyleSheet('font-weight: bold; color: gray; padding: 6px 4px 0px 4px;')
            lab.hide()
            self.engine_titles[a.key] = lab
            self._left.insertWidget(at, lab)
            self.panels[a.key] = w
            self._left.insertWidget(at + 1, w)
            at += 2
        study.set_solver_boxes(self.solver_boxes)
        study.selected.connect(self.show_settings)
        study.ticks_changed.connect(self._ticks)
        study.fields_ticked.connect(self._fields_ticked)
        mode = self.edits.get('mode', (None,))[0]
        if mode is not None:                                        # a config's mode: the Antenna row's tick
            mode.currentIndexChanged.connect(lambda _i: self._antenna_from_mode())
        self._fit_width()
        self.show_settings(study.current_question())
        self._ticks()

    def show_settings(self, question):
        """The settings of a question's engines under the list (the solvers' own sections for an RF question),
        the others' hidden; with several engines, each under its name."""
        if self.study is None:
            return
        keys = self.study.panels_of(question) if question in self.study.rows else ['rf']
        for k, w in self.panels.items():
            w.setVisible(k in keys)
        labels = {e.name: e.label for e in self.study.engines.get(question, [])}
        for k, lab in self.engine_titles.items():
            lab.setText(f"{labels.get(k, k)}  ·  {BY_KEY[k].tool}" if k in BY_KEY else k)
            lab.setVisible(k in keys and len(keys) > 1)
        self.panel_title.setText(f"{self.study.labels.get(question, 'S-parameters')} settings")
        self.panel_title.setVisible(True)

    def _solvers_text(self):
        """The RF rows of the list: the solvers ticked."""
        if self.study is not None:
            self.study.refresh()

    def _ticks(self):
        asked = self.study.asked()
        self.study_section.head.setText(f"Questions  ({len(asked)} asked)" if asked else 'Questions')
        self._mode_from_antenna()
        if hasattr(self.win, 'ticks_changed'):
            self.win.ticks_changed()

    def _mode_from_antenna(self):
        """The Antenna row ticked is the run's antenna mode (the mode setting, which the form no longer shows)."""
        mode = self.edits.get('mode', (None,))[0]
        if mode is None or 'antenna' not in self.study.rows:
            return
        want = 'antenna' if 'antenna' in self.study.asked() else 'sparams'
        if mode.currentText() != want and mode.findText(want) >= 0:
            mode.setCurrentIndex(mode.findText(want))

    def _antenna_from_mode(self):
        """A config's mode = antenna (or a setting typed elsewhere): the Antenna row ticked with it."""
        from PySide6.QtCore import Qt as _Qt
        st = self.study
        mode = self.edits.get('mode', (None,))[0]
        if st is None or mode is None or 'antenna' not in st.rows or not st.can_ask('antenna'):
            return
        on = mode.currentText() == 'antenna'
        it = st.rows['antenna']
        if (it.checkState(0) == _Qt.Checked) != on:
            it.setCheckState(0, _Qt.Checked if on else _Qt.Unchecked)

    def dump_keys(self):
        """The settings of the form that ask a solver for field dumps: {key: its solvers}."""
        from kicad2ems.api.frontend import registry
        from kicad2ems.study import dump_options
        out = {}
        for name, sv in registry().items():
            for o in dump_options(sv):
                if o.key in self.edits:
                    out.setdefault(o.key, []).append(name)
        return out

    def _fields_ticked(self, question, on):
        """A row's Fields tick. Ticked with no dump set: a default for each of its engines that can write one
        (an FDTD solver: E on the first port's layer at the band's centre; mom25d: its currents there; an
        analysis: its fields switch), which the settings let you change. Unticked: the settings stay, the run
        leaves them out."""
        from kicad2ems.api.frontend import default_fields
        st = self.study
        if st.is_solver(question):
            if not on:
                return
            names, auto = st._solver_names(question)
            if auto or not names:
                names = [e.name for e in st.engines[question] if e.fields]
            vals = self.values()
            fmin = vals.get('fmin') or self.defaults.fmin
            fmax = vals.get('fmax') or self.defaults.fmax
            for name in names:
                for key, value in default_fields(name, float(fmin), float(fmax), self.port_layer(),
                                                 vals.get('sweep') or 'linear').items():
                    w = self.edits.get(key, (None,))[0]
                    if w is not None and not w.text().strip():
                        w.setText(('; ' if key in SEMICOLON_LISTS else ',').join(map(str, value)))
            return
        for name in st.engines_for(question):
            e = next(x for x in st.engines[question] if x.name == name)
            box = self.fields_box(name, e.fields) if e.fields else None
            if box is not None and box.isChecked() != bool(on):
                box.setChecked(bool(on))

    def fields_box(self, name, key):
        """The tick of an analysis's fields switch: its panel's field of that option, or its page's own box."""
        page = getattr(self.win, 'pages', {}).get(name)
        box = page.w.get(key) if isinstance(getattr(page, 'w', None), dict) else getattr(page, key, None)
        return box if isinstance(box, QCheckBox) else None

    def follow_fields(self):
        """An analysis's own fields switch, ticked in its settings: the list's Fields tick of its question."""
        st = self.study
        for q, es in st.engines.items():
            for e in es:
                box = self.fields_box(e.name, e.fields) if e.kind == 'analysis' and e.fields else None
                if box is not None:
                    box.toggled.connect(lambda on, q=q, n=e.name: n in st.engines_for(q) and st.set_fields(q, on))

    def port_layer(self):
        """The copper layer a default field dump is on: the window's board's first port's, else F.Cu."""
        import glob
        try:
            shown = getattr(self.win.viewer, 'out', None) or ''
            for path in sorted(glob.glob(os.path.join(glob.escape(shown), '*_board.json'))):
                with open(path, encoding='utf-8') as fh:
                    ports = json.load(fh).get('ports') or []
                if ports and ports[0].get('layer'):
                    return str(ports[0]['layer'])
        except (OSError, ValueError, AttributeError):               # no board shown yet, or not a board file
            pass
        return 'F.Cu'

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
            if self.rows.get(key, (None,))[0] is not self.basic_form:   # (the first few are in view as they are)
                counts[self.group_of[key]] += on
        for g, n in counts.items():
            self.sections[g].set_count(n)
        for top, (sec, _) in self.parents.items():                  # a solver's section: its sub-sections' sum
            sec.set_count(sum(n for g, n in counts.items() if g.split('/')[0] == top))
        self.more.set_count(sum(n for g, n in counts.items() if g != 'Board'))

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
            sec.setToolTip('' if on else f"for {names}: choose it on the S-parameters row of the list to use these "
                           "settings")
            for key, (frm, roww) in self.rows.items():              # its settings among the first few: shown with it
                if frm is self.basic_form and self.group_of[key].split('/')[0] == top:
                    frm.setRowVisible(roww, on)
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
            w.setToolTip('' if antenna else "antenna mode only (tick Antenna pattern in the list, with " +
                         " or ".join(self.solver_labels.get(n, n) for n in radiating) + ")")

    def focus(self, key):
        """A setting's field in view: its section open (under "More settings", or the board's), the cursor in it."""
        w = self.edits.get(key, (None,))[0]
        if w is None:
            return
        frm, g = self.rows.get(key, (None,))[0], self.group_of[key]
        if g == 'Board':
            self.sections['Board'].set_expanded(True)
            if frm is self.board_more_form:
                self.board_more.set_expanded(True)
        elif frm is not self.basic_form:
            self.more.set_expanded(True)
            if g.split('/')[0] in self.parents:
                self.parents[g.split('/')[0]][0].set_expanded(True)
            self.sections[g].set_expanded(True)
        w.setFocus()
        QTimer.singleShot(0, lambda: (self.scroll if g == 'Board' else self.inspector).ensureWidgetVisible(w))

    def _find(self, text):
        """The settings under "More settings" whose label or key holds the text: their rows alone, their sections
        open; without text, every row again and the sections it opened closed."""
        t = text.strip().lower()
        title = lambda g: ' '.join([SECTION_TITLES.get(g.split('/')[0], g.split('/')[0])] + g.split('/')[1:]).lower()
        hit = lambda key: not t or t in self.row_text.get(key, '').lower() or t in key.replace('_', ' ') \
            or t in title(self.group_of[key])
        found = {}
        for key, (frm, roww) in self.rows.items():
            g = self.group_of[key]
            if frm is self.basic_form or g == 'Board':
                continue
            frm.setRowVisible(roww, hit(key))
            found[g] = found.get(g, False) or hit(key)
        for g, sec in self.sections.items():
            if g == 'Board':
                continue
            sec.setVisible(found.get(g, not t))
            if t and found.get(g) and not sec.expanded:
                sec.set_expanded(True)
                self._found.add(sec)
        for top, (sec, _) in self.parents.items():
            on = any(v for g, v in found.items() if g.split('/')[0] == top)
            sec.setVisible(on or not t)
            if t and on and not sec.expanded:
                sec.set_expanded(True)
                self._found.add(sec)
        if not t:
            for sec in self._found:
                sec.set_expanded(False)
            self._found.clear()

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

    def touch(self, *_):
        """Something a config holds changed (a field here, an analysis's settings or its tick): unsaved now."""
        if not self._loading and not self.dirty:
            self.dirty = True
            self.win.update_title()

    def _changed(self, *_):
        self._count()
        self._update_sections()
        self.touch()
        if hasattr(self.win, 'needs_soon'):
            self.win.needs_soon()
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
        if hasattr(self.win, 'load_analyses'):
            self.win.load_analyses(None)                            # and no analysis's settings
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
        if hasattr(self.win, 'load_analyses'):
            self.win.load_analyses(path)                            # the analyses it runs, and their settings
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
            if hasattr(self.win, 'save_analyses'):
                self.win.save_analyses(path)
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
    S-parameters, one for antennas. An analysis's result (a rail's drop and impedance, a near field, a circuit, a
    board's temperature: whatever kicad2ems's registry holds) takes the page instead, in one of three views:
    Plots, its curves (curveplot.CurvePlot; a result with several sets: one at a time); Report, what it found, to
    read; Tables, the report's tables to sort, copy and export (reportview.ReportView). Compare with lays other
    runs of the same kind over the plots."""
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
        self.mode_btns = {}                                         # an analysis's result: how it is shown
        for m, tip in zip(self.MODES, ("the result's curves", 'what the analysis found, to read',
                                       "the report's tables: sort, copy, export")):
            b = QToolButton()
            b.setText(m)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, m=m: self.set_mode(m))
            b.hide()
            top.addWidget(b)
            self.mode_btns[m] = b
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
        self.reportview = ReportView()
        self.views = QStackedWidget()                               # the S-parameter plots, or an analysis's
        self.views.addWidget(self.splot)                            # curves, report or tables
        self.views.addWidget(self.curveplot)
        self.views.addWidget(self.reportview)
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
        self.show(self._files)
        return True

    def remove_folder(self, d=None):
        """One compared run off the page (None: all of the kind shown)."""
        if self.analysis is not None:
            self.added_sets = [sets for sets in self.added_sets
                               if sets[0].kind != self.analysis or (d and sets[0].folder != d)]
            self._show_analysis()
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
        """An analysis's result as its Plots, its Report or its Tables (one the result has; else its first)."""
        has = self.modes()
        if not has:
            return
        self.mode = mode if mode in has else has[0]
        for m, b in self.mode_btns.items():
            b.setChecked(m == self.mode)
        self.set_box.setVisible(self.mode == 'Plots' and len(self.curve_sets) > 1)
        self.cmp_btn.setEnabled(self.mode == 'Plots')
        if self.mode == 'Plots':
            self.views.setCurrentWidget(self.curveplot)
        else:
            self.reportview.set_mode(self.mode)
            self.views.setCurrentWidget(self.reportview)

    def _show_analysis(self):
        """The result of an analysis in the page's views; none: the S-parameter plots."""
        has = self.modes()
        for m, b in self.mode_btns.items():
            b.setVisible(bool(has))
            b.setEnabled(m in has)
        if not has:
            self.curves = None
            self.set_box.hide()
            self.cmp_btn.setEnabled(True)
            self.views.setCurrentWidget(self.splot)
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
        self.reportview.set_report(self.analysis_report)
        self.which.hide()
        self.steer.hide()
        self.report = None
        rep = self.analysis_report or {}
        self.set_notes([], [])                                      # the report has its own
        head = rep.get('summary') or (self.curves.info if self.curves is not None else '')
        self.info.setText(head + (f"  ·  with {', '.join(o.label for o in others if o is not None)}" if others else ''))
        self.set_mode(self.mode if self.mode in has else has[0])

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


class PageDock(QDockWidget):
    """A dock of the window: a page (the board's Viewer, an editor, Results, Run, Filter Synthesis) or one of the
    study's two panels. It moves, tabs with others, floats and closes; View brings it back."""
    def __init__(self, title, name, widget, parent):
        super().__init__(title, parent)
        self.setObjectName(name)                                    # its name in saved layouts
        self.setWidget(widget)
        # closable: not closable, its View action is disabled, and a layout saved with it hidden (or a floated
        # dock the window manager closed) left no way to open it again
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable)

    def in_front(self):
        """In view: shown, and not behind another tab of its group."""
        return not self.visibleRegion().isEmpty()


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
        self._analyses()
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
        # docks, as a studio's: the study (the board and the questions) and the selected question's settings on the
        # left, one over the other; the pages in a workspace of their own: the board's Viewer with the editors
        # tabbed beside it, the Results and Run pages under it. Each moves, tabs, floats and closes (View).
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks | QMainWindow.AllowNestedDocks)
        self.study_dock = PageDock('Study', 'Study', self.setup, self)
        self.settings_dock = PageDock('Settings', 'Inspector', self.setup.inspector, self)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.study_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.settings_dock)
        self.work = QMainWindow()
        self.work.setObjectName('work')
        self.work.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks | QMainWindow.AllowNestedDocks)
        self.work.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)
        hidden = QWidget()
        hidden.hide()
        self.work.setCentralWidget(hidden)                          # the pages take the whole workspace
        widgets = {'Viewer': self.viewer, 'Run': self.runtab, 'Results': self.results, 'Filter': self.filter,
                   **{BY_KEY[k].page: p for k, p in self.editors.items()}}
        self.docks = {}
        for name in PANELS:
            if name not in widgets:                                 # an analysis's page this window has no editor for
                continue
            d = PageDock(TITLES.get(name, name), name, widgets[name], self.work)
            d.topLevelChanged.connect(lambda floating, d=d: floating and QTimer.singleShot(100, lambda: self._fit_floating(d)))
            self.docks[name] = d
            key = EDITORS.get(name)
            if key:                                                 # an analysis's page in front: its settings
                d.visibilityChanged.connect(lambda on, k=key: on and self._study_ready and self.study.select(k))
        self.places = self.docks                                    # (a page by its name: where it is)
        self._place_docks()
        self.setCentralWidget(self.work)
        self._toolbar()
        self._menus()
        self.statusBar().addPermanentWidget(self.meters)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self._needs_timer = QTimer(self)
        self._needs_timer.setSingleShot(True)
        self._needs_timer.timeout.connect(self.update_needed)
        self.setup.needed.picked.connect(self.go_to_need)
        self.study.selected.connect(lambda _q: self.update_needed())
        for page in self.pages.values():
            getattr(page, 'panel', page).changed.connect(self.needs_soon)
        self.update_needed()
        self._restore_shape()
        self.update_title()
        self._study_ready = True
        if config:
            self.setup.load(config)
        else:                                                       # no config: the solvers as kicad2ems's default
            self.setup.set_values({})                               # (auto), which the S-parameters row shows

    # ---- the study: the analyses, which a Run includes, their settings in the dock ----
    def _analyses(self):
        """What runs each analysis of the registry: a settings panel made from its options (analysispanel.py), or,
        for the one this window has an editor for (the circuit's schematic), that page."""
        from kicad2ems.api.frontend import analyses
        self.registry = analyses()
        self.panels, self.editors = {}, {}
        for a in ANALYSES:
            plugin = self.registry.get(a.key)
            if plugin is None:
                continue
            if a.page and a.key in EDITORS.values():
                self.editors[a.key] = editor_page(a.key, self)
                if hasattr(self.editors[a.key], 'panel'):           # its settings: a config holds them too
                    self.editors[a.key].panel.changed.connect(lambda: self.setup.touch())
            else:
                self.panels[a.key] = AnalysisPanel(plugin, self)
                self.panels[a.key].changed.connect(lambda: self.setup.touch())     # a config holds its settings
        self.pages = {a.key: (self.panels.get(a.key) or self.editors.get(a.key)) for a in ANALYSES
                      if a.key in self.panels or a.key in self.editors}

    def _study(self):
        """The analyses' list into the settings dock, with each one's settings under it; the ticks of the last
        session (the first time: S-parameters, as Run always did)."""
        self._study_ready = False
        self.queue, self.job, self._job_t0, self._queue_preview, self._queue_stopped = [], None, 0.0, False, False
        self.study = StudyList()
        panels = dict(self.panels)
        panels.update({k: p.settings_panel() for k, p in self.editors.items()})
        for a in ANALYSES:
            if a.planned:                                           # no tool, so no settings: what it will be
                note = QLabel(a.note)
                note.setWordWrap(True)
                note.setEnabled(False)
                note.setContentsMargins(6, 0, 6, 0)
                panels[a.key] = note
        self.setup.set_study(self.study, panels)
        for key, page in self.pages.items():
            ok, why = self.registry[key].check()
            if not ok:
                self.study.set_available(key, False, why)
            elif key in self.editors and not page.run_btn.isEnabled():     # its model could not be made: why
                self.study.set_available(key, False, page.status.text())
            self.runtab.add_log(key, BY_KEY[key].title, page.log)
        for a in ANALYSES:                                          # listed without a plugin here (a test's)
            if a.key != RF and a.key not in self.pages and not a.planned:
                self.study.set_available(a.key, False, 'not installed')
        self.study.set_study(self._saved_study())
        self.setup.follow_fields()
        self.study.opened.connect(self.show_analysis)
        self.study.run_one.connect(lambda q: self.run_study(only=q))

    def _saved_study(self):
        """The study of the last session: its questions, their engines and Fields ticks (the first time:
        S-parameters, as Run always did; a session of before the questions: the runs it had ticked)."""
        from kicad2ems.api.frontend import Study
        raw = self.qsettings.value('study/asked')
        if isinstance(raw, str) and raw:
            try:
                d = json.loads(raw)
                return Study({str(q): [str(n) for n in names] for q, names in d.get('asked', {}).items()},
                             {str(q): bool(v) for q, v in d.get('fields', {}).items()})
            except (ValueError, AttributeError, TypeError):
                pass
        old = self.qsettings.value('study/ticked')
        if old is None:
            return Study({'sparams': []})
        keys = [k for k in ([old] if isinstance(old, str) else list(old)) if k in BY_KEY]
        asked = {}
        for k in keys:
            for q in self.study.rows:
                if (k == RF and q == 'sparams') or (k != RF and any(e.name == k for e in self.study.engines[q])):
                    asked.setdefault(q, [])
        return Study(asked)

    # ---- what a run still needs: the list under the selected question's settings, the Run button's wording ----
    def needs(self, runs):
        """{run: [dict(text, key, run)]} of the runs `runs` ('rf', or an analysis): what each still needs before
        it can start (kicad2ems's rf_needs and the solvers chosen; an analysis's own check)."""
        out, before = {}, []                                # before: the analyses of this Run that come first
        for run in runs:
            if run == 'rf':
                from kicad2ems.api.frontend import rf_needs
                try:
                    got = rf_needs(self.setup.values())
                except Exception:                                   # noqa: BLE001 (a field half typed)
                    got = []
                if not any(w.isChecked() for w in self.setup.solver_boxes.values()):
                    got.append(dict(text='no solver chosen: pick one on the S-parameters row', key=None))
            elif run in self.pages:
                page = self.pages[run]
                got = getattr(page, 'panel', page).needs(self.study.asked_of(run, None), before)
                before.append(run)
            else:
                got = []
            out[run] = [dict(m, run=run) for m in got]
        return out

    def needs_soon(self):
        """The list and the Run button brought up to date shortly (a change, typed: not at every key)."""
        if getattr(self, '_study_ready', False):
            self._needs_timer.start(250)

    def update_needed(self):
        if not getattr(self, '_study_ready', False) or not hasattr(self, 'acts'):
            return
        q = self.study.current_question()
        mine = self.study.panels_of(q) if q in self.study.rows else ['rf']
        asked = self.study.jobs(False)
        needs = self.needs(asked)                           # in the Run's order: each knows what comes before it
        needs.update(self.needs([r for r in mine if r not in needs]))
        self.setup.needed.show_items([m for r in mine for m in needs.get(r, [])], q in self.study.asked())
        first = next((m for r in asked for m in needs.get(r, [])), None)
        self._need = first
        run = self.acts['Run']
        if first is not None:
            text = first['text'][0].upper() + first['text'][1:]
            run.setText(text if len(text) <= 30 else text[:29].rstrip() + '…')
            run.setToolTip(f"{BY_KEY[first['run']].title} still needs: {first['text']}\n(click: go to where it is "
                           f"set; Run > Run the selected question alone runs one whatever the others need)")
        else:
            titles = [BY_KEY[k].title for k in asked]
            run.setText(f"Run {len(titles)}" if len(titles) > 1 else 'Run')
            run.setToolTip(('Run ' + ', then '.join(titles) if titles else 'Tick a question in the list first')
                           + ' (Ctrl+R)')

    def go_to_need(self, item):
        """Where a thing a run still needs is set: its question selected, its field in view."""
        run, key = item.get('run'), item.get('key')
        if run and self.study.current() != run and run not in self.study.panels_of(self.study.current_question()):
            self.study.select(run)
        if run == 'rf' and key:
            self.setup.focus(key)
        elif run in self.pages and key:
            page = self.pages[run]
            getattr(page, 'panel', page).focus(key)
        self.statusBar().showMessage(f"{BY_KEY[run].title if run in BY_KEY else 'The run'} still needs: {item['text']}", 8000)

    def ticks_changed(self):
        self.needs_soon()
        if getattr(self, '_study_ready', False):
            st = self.study.study()
            self.qsettings.setValue('study/asked', json.dumps(dict(asked=st.asked, fields=st.fields)))
            self._page_visibility()
            if self.setup.path:                                     # an open config says what its study asks
                self.setup.touch()                                  # (without one, the next window remembers)

    def show_analysis(self, key):
        """A run's page in front (S-parameters: Results), the settings of a question it answers in the dock. key:
        'rf' or an analysis; a question: its run."""
        self.study.select(key)
        if key in self.study.rows:
            key = self.study.run_of(key)
        if key in BY_KEY and not BY_KEY[key].planned:
            self.show_panel(BY_KEY[key].page or 'Results')

    def busy(self):
        """A run of the window's or a tool of a page's is going."""
        return (self.proc is not None or self.job is not None or bool(self.queue)
                or any(p.proc is not None for p in self.pages.values()))

    def run_study(self, preview=False, only=None):
        """Run (preview) the questions asked: the runs they take, one after the other (the solvers' first, then
        each analysis after what it starts from); only: that question (or run) alone. One that cannot start (a
        setting missing) says why in the list, and the rest go on, except those that start from it."""
        if self.busy():
            QMessageBox.information(self, 'Busy', 'A run is going: stop it first')
            return
        keys = self.study.jobs(preview, only=only)
        if not keys:
            QMessageBox.warning(self, 'Study', 'None of the questions asked has a preview: tick S-parameters or '
                                'Converter near field in the list' if preview else 'Tick a question in the list first')
            return
        self._only = only if only in self.study.rows else None      # the question a run of one alone answers
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
        page.asked = self.study.asked_of(key, getattr(self, '_only', None))     # what this run is asked
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
            if key != RF and out and os.path.isdir(str(out)):       # its maps, its report and its curves
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
            if self._queue_preview:                                 # a mesh preview: the mesh, in the plan
                self.viewer.set_view('Plan')
                self.show_panel('Viewer')
            else:                                                   # its report
                self.show_panel('Results')                          # (an editor's page is its model: not its result)

    # ---- the window's shape: remembered between sessions ----
    def _splitters(self):
        return {'viewer': self.viewer.split, 'results': self.results.splot.split, 'filter': self.filter.split,
                **{k: p.split for k, p in self.editors.items()},
                **({'viewer3d': self.volume.split} if getattr(self.volume, 'split', None) is not None else {})}

    def _place_docks(self):
        """The docks where a new window has them: the study over the settings on the left; the Viewer on top with
        the editors and Filter Synthesis tabbed behind it, Results and Run tabbed under it."""
        for d in (self.study_dock, self.settings_dock):
            if d.isFloating():
                d.setFloating(False)
            self.addDockWidget(Qt.LeftDockWidgetArea, d)
            if d.isHidden():
                d.show()
        self.splitDockWidget(self.study_dock, self.settings_dock, Qt.Vertical)
        for area, group in ((Qt.TopDockWidgetArea, [n for n in self.docks if n not in LOWER]),
                            (Qt.BottomDockWidgetArea, [n for n in LOWER if n in self.docks])):
            for name in group:                                      # (only one that was closed is shown: show()
                d = self.docks[name]                                # on a dock of a window not yet laid out leaves
                if d.isFloating():                                  # a second tab bar behind, drawn over the page)
                    d.setFloating(False)
                if d.isHidden():
                    d.show()
            first = self.docks[group[0]]
            self.work.addDockWidget(area, first)
            for name in group[1:]:
                self.work.tabifyDockWidget(first, self.docks[name])
        self.docks['Viewer'].raise_()
        self.docks['Results'].raise_()

    def _restore_shape(self):
        """The size, position, docks and splitters of the last session; the first time, the whole screen."""
        q = self.qsettings
        geo = q.value('window/geometry')
        self._first_time = geo is None or not self.restoreGeometry(geo)
        if self._first_time:
            scr = self.screen().availableGeometry() if self.screen() else None
            if scr is not None and scr.width() > 0:
                self.setGeometry(scr)                               # (showMaximized on the first show: showEvent)
            else:
                self.resize(1500, 950)
        self._page_visibility(opening=True)
        self._first_sizes()
        for key, obj in (('window/state', self), ('work/state', self.work)):
            st = q.value(key)
            if st is not None:
                obj.restoreState(st, STATE_VERSION)                 # (an older window's layout: another version)
        for name, sp in self._splitters().items():
            st = q.value(f"splitter/{name}")
            if st is not None:
                sp.restoreState(st)
        for d in self.docks.values():
            if d.isHidden():
                d.show()                                            # a page closed last time: back
        self._page_visibility(opening=True)
        for d in (self.study_dock, self.settings_dock):             # the study: always there when the window opens
            if d.isHidden():
                d.setFloating(False)
                d.show()

    def showEvent(self, ev):
        super().showEvent(ev)
        if getattr(self, '_first_time', False):                     # no session before this one: the whole screen
            self._first_time = False
            self.setWindowState(self.windowState() | Qt.WindowMaximized)
        if not getattr(self, '_tidied', False):
            self._tidied = True
            QTimer.singleShot(0, self._tidy_tabs)

    def _page_visibility(self, opening=False):
        """The pages that come and go: Filter Synthesis closed when the window opens (the toolbar's Filter, or
        View, opens it); Circuit there while Circuit is asked, and gone when it is not."""
        if opening:
            for name in ON_DEMAND:
                self.docks[name].hide()
        ticked = set(self.study.ticked())
        for name, key in FOLLOWS_TICK.items():
            d = self.docks[name]
            if key in ticked and d.isHidden():
                self.show_panel(name, front=False)
            elif key not in ticked and not d.isHidden() and not (self.job == key or self.queue and key in self.queue):
                d.hide()

    def _save_shape(self):
        q = self.qsettings
        q.setValue('window/geometry', self.saveGeometry())
        q.setValue('window/state', self.saveState(STATE_VERSION))
        q.setValue('work/state', self.work.saveState(STATE_VERSION))
        for name, sp in self._splitters().items():
            q.setValue(f"splitter/{name}", sp.saveState())

    def reset_layout(self):
        """The docks where a new window has them, at their first sizes."""
        self._place_docks()
        self._page_visibility(opening=True)
        self._first_sizes()
        QTimer.singleShot(0, self._tidy_tabs)

    def _tidy_tabs(self):
        """Qt keeps the tab bars it no longer uses, shown where an earlier layout had them (two tab groups put
        down before the window had its size: a second 'Results | Run' drawn over the board). All hidden, and the
        layout made again: it shows those it uses."""
        from PySide6.QtWidgets import QTabBar
        for win in (self, self.work):
            for bar in win.findChildren(QTabBar, options=Qt.FindDirectChildrenOnly):
                bar.hide()
            win.layout().invalidate()
            win.layout().activate()
        h = self.work.height()
        top, low = self.docks['Viewer'], self.docks['Results']
        if not top.isHidden() and not low.isHidden() and not top.isFloating() and not low.isFloating():
            self.work.resizeDocks([top, low], [top.height() + 1, max(low.height() - 1, 1)], Qt.Vertical)

    def _first_sizes(self):
        w, h = max(self.width(), 900), max(self.height(), 600)
        left = max(self.setup.minimumWidth() + 40, self.setup.inspector.minimumWidth() + 40, 420)
        self.resizeDocks([self.study_dock, self.settings_dock], [left, left], Qt.Horizontal)
        self.resizeDocks([self.study_dock, self.settings_dock], [int(0.42 * h), int(0.58 * h)], Qt.Vertical)
        self.work.resizeDocks([self.docks['Viewer'], self.docks['Results']], [int(0.58 * h), int(0.42 * h)], Qt.Vertical)
        self.viewer.split.setSizes([880, 380])
        self.results.splot.split.setSizes([220, 1000])

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
        before = [x for x in self.docks.values() if x is not d and x.in_front()]
        d.show()
        home = self.docks['Results' if name in LOWER else 'Viewer']
        if closed and not d.isFloating() and d is not home and d not in self.work.tabifiedDockWidgets(home):
            self.work.tabifyDockWidget(home, d)                     # a page that starts closed: tabbed with its own
        if front:
            d.raise_()
        else:                                                       # only there: what was in front stays
            for x in before:
                x.raise_()

    def hide_panel(self, name):
        self.docks[name].hide()

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
        self.fold_acts = {}                                         # the study's two docks, by key
        for name, key, d in (('Questions', 'Ctrl+1', self.study_dock), ('Settings', 'Ctrl+2', self.settings_dock)):
            a = d.toggleViewAction()
            a.setText(name)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(lambda on, d=d: on and d.isFloating() and d.setFloating(False))    # back, docked
            vm.addAction(a)
            self.fold_acts[name] = a
        vm.addSeparator()
        for name in PANELS:
            if name not in self.docks:
                continue
            a = self.docks[name].toggleViewAction()
            a.triggered.connect(lambda on, d=self.docks[name]: on and d.isFloating() and d.setFloating(False))
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
                                ('Run the selected &question alone', 'Ctrl+Shift+R',
                                 lambda: self.run_study(only=self.study.current_question())),
                                ('&Stop', 'Ctrl+.', self.stop)):
            a = QAction(text, self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(slot)
            rm.addAction(a)
        tm = self.menuBar().addMenu('&Tools')                    # what is not about the open board's run
        a = QAction('&Impedance calculator…', self)
        a.setToolTip("A line's impedance in a stack-up, and the width of a target: the field solver without a board")
        a.triggered.connect(self.show_impedance)
        tm.addAction(a)
        hm = self.menuBar().addMenu('&Help')
        a = QAction('&Solvers and hardware…', self)
        a.triggered.connect(self.show_solvers)
        hm.addAction(a)
        a = QAction('&Documentation', self)
        a.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(DOCS)))
        hm.addAction(a)
        self._fill_recent()
        self._fill_examples()

    def show_impedance(self):
        """Tools > Impedance calculator: one window, kept; the open board's layers offered as its stack."""
        from .impedance import ImpedanceCalculator
        board = self.setup.values().get('board') or None
        if getattr(self, 'impedance', None) is None:
            self.impedance = ImpedanceCalculator(self, board)
        elif board != self.impedance.board:
            self.impedance.set_board(board)
        self.impedance.show()
        self.impedance.raise_()
        self.impedance.activateWindow()
        return self.impedance

    def _fill_examples(self):
        """The examples, kicad2ems's own and those the installed analyses ship (pcbqs's circuits), as a menu of
        their groups; one opens from a folder of the user's, where it is copied, its board made if it is generated."""
        from kicad2ems.api.frontend import example_index
        self.examples_menu.clear()
        try:
            entries = example_index()
        except Exception:                                           # a plugin's fault: no examples, not no window
            entries = []
        menus, self.example_sources = {}, {}                        # {group path: its menu}, {top group: whose}
        for e in entries:
            m, path = self.examples_menu, ''
            for part in [p.strip() for p in (e.get('group') or '').split('/') if p.strip()]:
                path += '/' + part
                if path not in menus:                               # kept here: QAction.menu() must not be asked
                    menus[path] = m.addMenu(part)                   # for them (PySide deletes the menu with the
                    menus[path].setToolTipsVisible(True)            # wrapper it hands back)
                m = menus[path]
            top = '/' + (e.get('group') or '').split('/')[0].strip()
            self.example_sources.setdefault(top, set()).add(e.get('source'))
            a = QAction(e['name'], self)
            a.setToolTip(e.get('title') or '')
            a.setStatusTip(e.get('title') or '')
            a.triggered.connect(lambda _=False, n=e['name']: self.open_example(n))
            m.addAction(a)
        self.example_menus = menus
        self.examples_menu.setEnabled(bool(entries))

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
        """A preview's estimates: beside the solvers in the S-parameters row's menu and in the toolbar, for the
        settings as they are now."""
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
            for page in self.pages.values():                         # a tool still running: stopped with the window
                if page.proc is not None:
                    page.stop()
                    if page.proc is not None:
                        page.proc.waitForFinished(3000)
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
        dumps, far field) and the results page (S-parameters and antenna, or an analysis's report and curves);
        front: the page with something new in front."""
        from kicad2ems.api.frontend import analysis_of
        files = find_results(out_dir)
        ant = self.results.load_antenna(out_dir)                    # first: it decides the page's plots
        shown = self.results.load_analysis(out_dir)                 # an analysis's result: the page is its
        if files:
            self.results.show(files)
        seen = self.viewer.load(out_dir)
        made = analysis_of(out_dir)
        if made is not None and made[0] in self.pages:
            self._show_tool_result(made[0], out_dir, preview=made[1])
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
        elif front and shown:
            self.show_panel('Results')
        if not quiet and not (files or seen or ant or shown):
            QMessageBox.information(self, 'Results', f"No results in {out_dir}")

    def _show_tool_result(self, kind, out_dir, preview=False):
        """An analysis's folder is the one shown: its panel (or page) takes it as its result, and the viewer starts
        where its report says (the dump of a field with the largest values: the layer that drops most, the hottest;
        a mesh in the plan)."""
        page = self.pages[kind]
        if kind in self.editors:
            if not preview and os.path.abspath(str(page.out or '')) != os.path.abspath(out_dir):
                page.open_run(out_dir)                              # not its own run just finished: shown there too
        else:
            if not preview:
                page.out = out_dir
            page.show_result(out_dir)
        rep = self.results.analysis_report or {}
        show, mesh = rep.get('show') or {}, rep.get('mesh')
        if show.get('field'):
            srcs = [s for s in self.viewer.cuts.srcs if s.field == show['field'] and show.get('run') in (None, s.run)]

            def top(src):
                try:
                    return float(np.nanmax(np.abs(src.load(0)[1])))
                except Exception:                                   # a dump half written
                    return -1.0
            if srcs:
                self.viewer.show_dump(max(srcs, key=top).label)
        if mesh and self.viewer.plan.mesh.findData(mesh) >= 0:
            self.viewer.plan.mesh.setCurrentIndex(self.viewer.plan.mesh.findData(mesh))

    def latest_results(self):
        """{analysis: the folder of its latest result on this board}: the one its panel shows (its last run here,
        or the one picked under Results of), else the newest listed. An analysis that starts from another's result
        (the temperature, from a circuit's losses) is given these."""
        from .runfolders import tool_kind
        out = {}
        for src in self.sources():                                  # each kind's newest first
            if src['kind'] in self.pages:
                out.setdefault(src['kind'], src['folder'])
        for key, page in self.pages.items():
            d = getattr(page, 'out', None)
            if d and tool_kind(str(d)) == key:
                out[key] = str(d)
        return out

    def load_analyses(self, path=None):
        """A config's study into the list (kicad2ems.api.frontend.read_study: its [study] tables, else the
        analyses [analysis] run names; neither: S-parameters) and each analysis's settings from its [analysis.
        <name>] table, the others' cleared. path None: a new study, nothing set. A table of an analysis not
        installed here is kept, and saved back, as is a question or an engine of the study this window lacks."""
        from kicad2ems.api.frontend import read_analyses, read_study, Study
        run, tables, study, more = None, {}, Study({'sparams': []}), {}
        if not self.busy():
            self.study.clear_states()                               # another study: the last one's states are not its
        if path:
            try:
                run, tables = read_analyses(path)
                study = read_study(path, strict=False)
                more = self._more_sets(path)
            except Exception as e:
                self.statusBar().showMessage(f"{path}: its study could not be read ({e})", 8000)
        self.more_sets = more
        base = os.path.dirname(os.path.abspath(path)) if path else os.getcwd()
        loading, self.setup._loading = self.setup._loading, True
        try:
            for key, page in self.pages.items():
                tab = dict(tables.get(key) or {})
                for k in ('board', 'out'):                          # its own board and folder: beside the config
                    if tab.get(k) and not os.path.isabs(str(tab[k])):
                        tab[k] = os.path.normpath(os.path.join(base, str(tab[k])))
                if key in self.editors:
                    page.load_settings(tab)
                    continue
                page.reset()
                page.set_own(tab.pop('board', None), tab.pop('out', None))
                page.set_values(tab)
            self.extra_analyses = {k: ([v, *more[k]] if more.get(k) else v) for k, v in tables.items()
                                   if k not in self.pages}
            for key, rest in more.items():                          # an analysis given several tables (a board's
                page = self.pages.get(key)                          # rails): the first is shown and run here
                if page is not None and hasattr(page, 'status'):
                    tags = ', '.join(self.registry[key].tag(dict(v)) for v in rest)
                    page.status.setText(f"This config has {len(rest)} more of these ({tags}): the first is shown and "
                                        f"run here, and all of them by `kicad2ems study`; saving keeps them.")
            self.extra_study = Study({q: n for q, n in study.asked.items() if q not in self.study.rows
                                      or not self.study.engines[q]},
                                     {q: v for q, v in study.fields.items() if q not in self.study.rows})
            fields = dict(study.fields)
            for q in study.asked:                                   # a config of before the Fields ticks: what
                if q not in fields and q in self.study.rows:        # its settings ask for
                    fields[q] = self._fields_set(q, study)
            self.study.set_study(Study(study.asked, fields, study.said))
            self.setup._antenna_from_mode()                         # mode = "antenna" in the settings
        finally:
            self.setup._loading = loading
        asked = list(self.study.asked())
        first = asked[0] if asked else 'sparams'                    # the study's first question: its settings
        self.study.select(first)                                    # shown, its editor (a circuit's) in front
        run = self.study.run_of(first) if first in self.study.rows else RF
        if path and run in self.editors:
            self.show_panel(BY_KEY[run].page)

    @staticmethod
    def _more_sets(path):
        """{analysis: its tables after the first} for the analyses a config gives several tables ([[analysis.
        <name>]]: a run each, kicad2ems 2.10), their paths whole; {} with an older kicad2ems, which reads one."""
        try:
            from kicad2ems.api.frontend import read_analysis_sets
        except ImportError:
            return {}
        base, out = os.path.dirname(os.path.abspath(path)), {}
        for name, sets in read_analysis_sets(path).items():
            rest = [dict(t) for t in sets[1:]]
            for t in rest:
                for k in ('board', 'out'):                          # its own board and folder: beside the config
                    if t.get(k) and not os.path.isabs(str(t[k])):
                        t[k] = os.path.normpath(os.path.join(base, str(t[k])))
            if rest:
                out[name] = rest
        return out

    def _fields_set(self, question, study):
        """Whether a question's settings ask for field dumps, for a study that does not say (a config written
        before the list had the tick): a solver's dump setting filled in, an analysis's fields switch on."""
        st = self.study
        if st.is_solver(question):
            if question == 'lines':
                return False
            vals = self.setup.values()
            return any(vals.get(k) for k in self.setup.dump_keys())
        for name in (study.asked.get(question) or st.engines_for(question)):
            e = next((x for x in st.engines.get(question, []) if x.name == name), None)
            box = self.setup.fields_box(name, e.fields) if e is not None and e.fields else None
            if box is not None and box.isChecked():
                return True
        return False

    def save_analyses(self, path):
        """The study into a config: what it asks and who answers as its [study] tables (kicad2ems.api.frontend.
        write_study), each analysis's settings that are set as its [analysis.<name>] table. A study of
        S-parameters alone with nothing else set writes neither."""
        from kicad2ems.api.frontend import write_study, Study
        from .runner import write_analyses
        base = os.path.dirname(os.path.abspath(path))
        tables = dict(getattr(self, 'extra_analyses', {}))
        for key, page in self.pages.items():
            tab = page.save_settings(path) if key in self.editors else config_values(page, base)
            if tab:
                rest = getattr(self, 'more_sets', {}).get(key)      # the config's other tables of it: kept,
                if rest:                                            # their paths relative to where it is saved
                    paths = (*getattr(self.registry.get(key), 'paths', ()), 'board', 'out')
                    rel = lambda v: (os.path.relpath(v, base).replace(os.sep, '/')
                                     if isinstance(v, str) and os.path.isabs(v) else v)
                    tab = [tab, *[{k: (rel(v) if k in paths else v) for k, v in t.items()} for t in rest]]
                tables[key] = tab
        write_analyses(path, None, tables)                          # [study] says which run: no [analysis] run
        st = self.study.study()
        extra = getattr(self, 'extra_study', None)
        if extra is not None and extra.asked:                       # what this window could not show: kept
            st = Study({**st.asked, **extra.asked}, {**st.fields, **extra.fields}, 'study')
        plain = list(st.asked) == ['sparams'] and not st.fields.get('sparams') and not tables
        write_study(path, None if plain else st)

    def apply_suggestion(self, source, s):
        """What one analysis's result proposes for another (Analysis.suggest): those settings into the other's
        panel, on the same board, and its questions asked; the options it had no value for must be set before a
        run. For the analysis
        with an editor of its own (the circuit), a model the proposal names is opened there, as the study's own
        (a config then writes it beside itself, not into the result it came from)."""
        target = self.pages.get(s.get('to'))
        if target is None:
            return
        values = dict(s.get('values') or {})
        own = source.board.text().strip()                           # a board of its own: the same one there
        if hasattr(target, 'set_values'):
            panel = target
            panel.reset()
            if own:
                panel.set_own(own, None)
            panel.set_values(values)
        elif hasattr(target, 'load_settings'):
            target.load_settings(dict(values, **({'board': own} if own else {})))
            target.model_path = None
            panel = target.settings_panel()
        else:
            return
        panel.required = {k for k in s.get('need') or [] if not str(values.get(k) or '').strip()}
        panel.status.setText(s.get('note', ''))
        panel.changed.emit()
        self.study.ask(s['to'])                                     # proposed for it: asked, so Run includes it
        self.show_analysis(s['to'])                                 # its settings, and its page (the schematic)

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
        """The preview a newly opened config gets: only in a window on the screen (not a test's), when idle, and
        only of a study that runs S-parameters (the preview is that run's: a circuit's board has no ports for it)."""
        board = self.setup.values().get('board')
        if self.isVisible() and board and os.path.exists(board) and not self.busy() and RF in self.study.ticked():
            self.start(True)                                        # kicad2ems's own: the board

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
        base = base or (default_out(board) if board else os.path.join(os.getcwd(), 'out'))
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
            return no('Setup', "Choose a solver on the list's S-parameters row (or Preview)")
        from kicad2ems.api.frontend import mark_run
        from .runfolders import run_dir, preview_dir
        if not preview and not self.study.fields_on(RF):            # no Fields tick on an RF row: the run leaves
            for k in self.setup.dump_keys():                        # the dumps out (the settings keep them)
                vals.pop(k, None)
        base = self.out_dir(vals)                                   # each run in a folder of its own
        self.current = Run(vals, preview_dir(base, vals['board']) if preview else run_dir(base, vals['board']), preview)
        mark_run(self.current.out, RF, self.study.asked_of(RF, getattr(self, '_only', None)) or ('sparams',), preview)
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
        """Run what is asked; something it still needs: there instead (the button says which)."""
        self.update_needed()
        if getattr(self, '_need', None) is not None:
            self.go_to_need(self._need)
            return
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
            self.statusBar().showMessage("preview done: estimates beside the solvers in the S-parameters row's menu "
                                         "(? under Solvers for details)", 8000)
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
