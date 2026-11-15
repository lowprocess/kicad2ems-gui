"""The study and the settings of what is selected in it (the window's left side): the board, the analyses
made of it, and each one's settings as a form (SetupTab); editor_page, an analysis's own page (the circuit's
schematic). Moved out of app.py (R-F2)."""
import json
import os
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLineEdit, QCheckBox,
                               QComboBox, QPushButton, QLabel, QFileDialog, QScrollArea, QMessageBox, QToolButton)
from .runner import (FIELDS, SEMICOLON_LISTS, SECTION_SOLVERS, SECTION_TITLES, TICK, settings_values, extra_values,
                     save_config, solvers_from_form, solver_ticks, basic_keys)
from kicad2ems.api.frontend import G_DUMP
from .panels import Section, NeededList
from .meters import duration
from .study import BY_KEY


def _helps():
    """{field key: its tooltip}: each option's help (its {default} filled in), wrapped; a solver's tick box its
    solver's description."""
    import textwrap
    from kicad2ems.api.frontend import all_options, registry
    out = {}
    for _, o in all_options():
        if o.gui and o.help:
            text = o.help.replace('{default}', str(o.default)) if '{default}' in o.help else o.help
            out[o.key] = '\n'.join(textwrap.wrap(text, 80))
    for n, sv in registry().items():
        about = getattr(sv, 'description', None) or getattr(sv, '__doc__', None) or sv.label
        out[TICK + n] = '\n'.join(textwrap.wrap(' '.join(str(about).split()), 80))
    return out


def editor_page(key, win):
    """The page of an analysis this window has an editor for: the circuit's schematic and model."""
    from .powercircuittab import PowerCircuitTab
    return {'circuit': PowerCircuitTab}[key](win)


class SetupTab(QWidget):
    """The study's settings, in a scroll area: the board (one for every analysis), the analyses (study.StudyList,
    once the window gave its pages: set_study) and the settings of the analysis selected there. Each group is a
    collapsible section (collapsed when the window opens; the header counts the settings set). Open / Save /
    Preview / Run are the window's toolbar. Edit > Undo / Redo step back and forth through the changes to its
    fields and ticks (undo, redo: a field's typing is one step, once it rests for UNDO_REST ms)."""
    undo_changed = Signal()                                         # what undo / redo can do now changed
    UNDO_REST = 700

    def __init__(self, win):
        super().__init__()
        from kicad2ems.api.frontend import Settings
        self.win, self.edits, self.extra = win, {}, {}
        self.path, self.dirty, self._loading, self.est = None, False, False, None
        self._undo, self._redo, self._base, self._restoring, self._typed = [], [], None, False, None
        self._rest = QTimer(self)                                   # a field's typing: one step when it rests
        self._rest.setSingleShot(True)
        self._rest.setInterval(self.UNDO_REST)
        self._rest.timeout.connect(self._commit)
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
        self.helps = _helps()                                       # each field's tooltip: its option's help (R-E23)
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
            if self.helps.get(key):
                w.setToolTip(self.helps[key])
                if self.field_labels[key] is not None:
                    self.field_labels[key].setToolTip(self.helps[key])
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
        """The RF rows of the list read the solvers' ticks: refreshed when they change."""
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
            names, auto = st.solver_names(question)
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
                w.setToolTip(self.helps.get(TICK + s['name'], '') if s['ok'] else
                             f"not available here: {s['what']} (? for the Solvers window)")
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
        self.bad = {}                                                # fields that are not what they say: left out,
        for key, (w, kind) in self.edits.items():                    # marked, and listed as still needed
            if kind == 'bool':
                out[key] = w.isChecked()
                continue
            if isinstance(kind, tuple):
                t = w.currentText()
                out[key] = '' if t == '(none)' else t
                continue
            t = w.text().strip()
            if hasattr(w, 'setStyleSheet') and key in getattr(self, '_marked', set()):
                w.setStyleSheet('')
                self._marked.discard(key)
            if not t:
                continue
            if kind in ('float', 'int'):
                try:
                    x = float(t)
                except ValueError:                                   # (a half-typed number had raised from a timer:
                    self.bad[key] = t                                # the list and Run froze, saying nothing)
                    w.setStyleSheet('border: 1px solid #c0392b')
                    self.__dict__.setdefault('_marked', set()).add(key)
                    continue
                out[key] = x if kind == 'float' else int(x)
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
        """Fill the form (a loaded config): not an edit, so the settings stay unchanged, and undo starts here."""
        loading, self._loading = self._loading, True
        try:
            self._set_values(vals)
        finally:
            self._loading = loading
        self._count()
        self._update_sections()
        self._rest.stop()
        self._undo, self._redo, self._base = [], [], self._state()
        self.undo_changed.emit()

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
        if not self._loading and not self._restoring:              # a step for undo: a tick or a choice at once,
            if isinstance(self.sender(), QLineEdit):                # typing when it rests (and before a tick)
                self._typed = self._state()
                self._rest.start()
            else:
                if self._rest.isActive():
                    self._commit(self._typed)
                self._commit()
        self._count()
        self._update_sections()
        self.touch()
        if hasattr(self.win, 'needs_soon'):
            self.win.needs_soon()
        if hasattr(self.win, 'update_estimate'):                    # the toolbar's: the solvers ticked now
            self.win.update_estimate()

    # ---- undo (R-E25) ----
    def _state(self):
        """The form as it stands: each field's text, tick or choice, as typed (what undo puts back)."""
        out = {}
        for key, (w, kind) in self.edits.items():
            out[key] = w.isChecked() if kind == 'bool' else w.currentText() if isinstance(kind, tuple) else w.text()
        return out

    def _commit(self, st=None):
        """The form's changes since the last step (or up to the state st), as a step (none: nothing)."""
        self._rest.stop()
        st = self._state() if st is None else st
        if self._base is None:
            self._base = st
        elif st != self._base:
            self._undo.append(self._base)
            self._redo.clear()
            self._base = st
            self.undo_changed.emit()

    def _put(self, st):
        """Put a state back into the form: an edit (unsaved), not a step of its own."""
        restoring, self._restoring = self._restoring, True
        try:
            for key, v in st.items():
                if key not in self.edits:
                    continue
                w, kind = self.edits[key]
                if kind == 'bool':
                    w.setChecked(bool(v))
                elif isinstance(kind, tuple):
                    w.setCurrentIndex(max(w.findText(v), 0))
                elif w.text() != v:
                    w.setText(v)
        finally:
            self._restoring = restoring
        self._changed()
        self.undo_changed.emit()

    def _differs(self, a, b):
        """The fields that differ between two states (for the menu's text)."""
        return [k for k in self.edits if a.get(k) != b.get(k)]

    def can_undo(self):
        return bool(self._undo) or (self._rest.isActive() and self._state() != self._base)

    def can_redo(self):
        return bool(self._redo) and not (self._rest.isActive() and self._state() != self._base)

    def undo_text(self, redo=False):
        """'Undo fmax', 'Redo 3 settings', or plain 'Undo' / 'Redo': what the step would change."""
        now, typing = self._state(), self._rest.isActive()
        if redo:
            keys = self._differs(self._redo[-1], now) if self._redo else []
        elif typing and now != self._base:
            keys = self._differs(now, self._base)
        else:
            keys = self._differs(self._base, self._undo[-1]) if self._undo else []
        what = keys[0] if len(keys) == 1 else f"{len(keys)} settings" if keys else ''
        return ('Redo' if redo else 'Undo') + (f" {what}" if what else '')

    def undo(self):
        """Back one step: the form as it was before the last change. False when there is none."""
        self._commit()
        if not self._undo:
            return False
        self._redo.append(self._base)
        self._base = self._undo.pop()
        self._put(self._base)
        return True

    def redo(self):
        """Forward one step again, after an undo. False when there is none."""
        self._commit()
        if not self._redo:
            return False
        self._undo.append(self._base)
        self._base = self._redo.pop()
        self._put(self._base)
        return True

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
