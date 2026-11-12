"""
The study: one board, the questions asked of it, who answers each, and the runs that takes.

    TREE                        what the list shows: kicad2ems's study_tree (the questions by group, each with the
                                engines installed that answer it)
    ANALYSES                    the runs the window can make on a board, in the order it makes them: kicad2ems's
                                own ('rf': the solvers together), then each analysis plugin
    with_needs(keys)            keys and the analyses they start from, in that order
    dependents(key)             the analyses that start from key's results
    run_order(ticked, preview)  what a Run (a Preview) of those runs starts, in order
    StudyTree                   the list in the Study dock: a row per question, with a tick (it is asked), who
                                answers it (a menu: one engine, or several to compare), a tick for its field
                                dumps where an engine can write them, and its state

A question is something to find out (kicad2ems.study: the ports' S-parameters, a rail's drop, the temperature);
an engine is a solver or an analysis plugin that answers it. The three RF questions are answered by the solvers,
together, as kicad2ems's one run; every other engine is a run of its own, in the registry's order, which is
also a run's: Thermal, which takes its losses from the latest circuit run unless they are typed, runs after
Circuit. `needs` is how one analysis follows another (none does now).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Analysis:
    key: str
    title: str
    tool: str               # what runs it, as the list shows it
    page: str = ''          # its own page (a name of app.PANELS: the circuit's editor); '': Viewer, Run and Results
    needs: tuple = ()       # the analyses whose results it starts from
    preview: bool = False   # it has a preview (the model and meshes, no solve)
    planned: bool = False   # no tool for it yet: listed, greyed
    note: str = ''          # the list's tooltip


RF = 'rf'                       # kicad2ems's own run: not a plugin's


def installed():
    """S-parameters, then the analyses of kicad2ems's registry in its order (none: only S-parameters)."""
    out = [Analysis(RF, 'S-parameters', 'the solvers ticked', preview=True,
                    note="kicad2ems's run: the solvers chosen on the RF rows, their S-parameters, fields and antenna "
                         "results")]
    from kicad2ems.api.frontend import analyses
    for a in analyses().values():
        out.append(Analysis(a.name, a.label, a.tool, page=a.label if a.page else '', needs=tuple(a.needs),
                            preview=bool(a.previewed), note=a.about))
    return tuple(out)


def tree():
    """What the list shows: kicad2ems's study_tree, [dict(group, questions=[dict(question, engines, missing)])]."""
    from kicad2ems.api.frontend import study_tree
    return study_tree()


ANALYSES = installed()
BY_KEY = {a.key: a for a in ANALYSES}
TREE = tree()
SOLVER_QUESTIONS = ('sparams', 'antenna', 'lines')      # what the solvers answer: together, kicad2ems's one run
AUTO = 'auto'                                           # the solvers' tick box of that name


def with_needs(keys):
    """keys and, for each, the analyses it starts from (and theirs), in ANALYSES' order."""
    want, todo = set(), list(keys)
    while todo:
        k = todo.pop()
        if k in BY_KEY and k not in want:
            want.add(k)
            todo += BY_KEY[k].needs
    return [a.key for a in ANALYSES if a.key in want]


def dependents(key):
    """The analyses that start from key's results (and from theirs), in ANALYSES' order."""
    out, grew = {key}, True
    while grew:
        grew = False
        for a in ANALYSES:
            if a.key not in out and out & set(a.needs):
                out.add(a.key)
                grew = True
    return [a.key for a in ANALYSES if a.key in out and a.key != key]


def run_order(ticked, preview=False, available=None):
    """What a Run of the ticked analyses starts, in order: each after what it starts from; planned ones and (with
    `available`, a set) those that cannot run here left out, with what follows them. preview: only the analyses
    that have one, each alone (a preview solves nothing, so nothing follows another)."""
    if preview:
        return [a.key for a in ANALYSES if a.key in ticked and a.preview and not a.planned
                and (available is None or a.key in available)]
    out = []
    for k in with_needs(ticked):
        a = BY_KEY[k]
        if a.planned or (available is not None and k not in available) or any(n not in out for n in a.needs):
            continue
        out.append(k)
    return out


from PySide6.QtCore import Qt, Signal              # the list itself (the helpers above need no Qt)
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView, QMenu

TONES = {'': None, 'gray': 'gray', 'bad': '#c62828'}
C_Q, C_BY, C_FIELDS, C_STATE = range(4)             # the columns
short = lambda label: label.split(' (')[0]          # 'mom25d (MoM)' -> 'mom25d'


class StudyTree(QTreeWidget):
    """The questions, by group: a tick (Run and Preview include it), who answers it (click the cell: a menu of
    its engines, several ticked are compared), a tick for its field dumps where an engine can write them, its
    state. The selected question's settings are the ones the dock shows.

    A run is an engine's, so availability, state and the queue go by run ('rf', or an analysis's name), and a
    row shows those of its engines."""
    selected = Signal(str)              # the question whose settings to show
    ticks_changed = Signal()            # a tick, an engine or a Fields tick changed
    opened = Signal(str)                # double-clicked: the run whose page to show ('rf' or an analysis)
    run_one = Signal(str)               # the context menu: run this question alone
    fields_ticked = Signal(str, bool)   # the user ticked or unticked a row's Fields

    def __init__(self):
        super().__init__()
        self.setHeaderLabels(['Question', 'Answered by', 'Fields', 'State'])
        self.headerItem().setToolTip(C_BY, 'click a cell: the engine that answers, or several to compare')
        self.headerItem().setToolTip(C_FIELDS, "its field dumps too, where the engine can write them (ticked with "
                                               "none set: a default, which its settings let you change)")
        self.setRootIsDecorated(False)
        self.setIndentation(12)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)    # every row shown, a long State cut short
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.ElideRight)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context)
        self.rows, self.engines, self.missing, self.labels = {}, {}, {}, {}
        self.choice, self.fields = {}, {}           # {question: [engine names]} ([]: its default); {question: bool}
        self.why, self.states = {}, {}              # per run: why it cannot run here; (state text, tone)
        self.boxes = {}                             # the solvers' tick boxes (set_solver_boxes)
        self._setting = False
        bold = QFont(self.font())
        bold.setBold(True)
        n = 0
        for g in TREE:
            head = QTreeWidgetItem([g['group']])
            head.setFont(C_Q, bold)
            head.setFlags(Qt.ItemIsEnabled)
            self.addTopLevelItem(head)
            head.setFirstColumnSpanned(True)
            for row in g['questions']:
                q = row['question']
                it = QTreeWidgetItem([q.label, '', '', ''])
                it.setData(C_Q, Qt.UserRole, q.name)
                it.setToolTip(C_Q, q.about)
                head.addChild(it)
                self.rows[q.name], self.labels[q.name] = it, q.label
                self.engines[q.name] = [e for e in row['engines'] if q.name in SOLVER_QUESTIONS or e.name in BY_KEY]
                self.missing[q.name] = row['missing'] or 'no engine for it is installed'
                self.choice[q.name], self.fields[q.name] = [], False
                it.setCheckState(C_Q, Qt.Unchecked)
            head.setExpanded(True)
            n += 1 + len(g['questions'])
        for q in self.rows:
            self._row(q)
        hd = self.header()
        for c in (C_Q, C_BY, C_FIELDS):
            hd.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hd.setStretchLastSection(True)
        first = next(iter(self.rows.values()), None)
        self.setFixedHeight((self.sizeHintForRow(0) if first is None else self.rowHeight(self.indexFromItem(first)) or 20)
                            * max(n, 1) + hd.sizeHint().height() + 2 * self.frameWidth() + 6)
        self.itemChanged.connect(self._changed)
        self.itemClicked.connect(self._clicked)
        self.currentItemChanged.connect(self._current)
        self.itemDoubleClicked.connect(lambda it, _col: self._is_row(it) and self.opened.emit(self.run_of(self._q(it))))
        if 'sparams' in self.rows:
            self.setCurrentItem(self.rows['sparams'])
        elif first is not None:
            self.setCurrentItem(first)

    # ---- the rows ----
    @staticmethod
    def _q(it):
        return it.data(C_Q, Qt.UserRole) if it is not None else None

    def _is_row(self, it):
        return self._q(it) in self.rows

    def is_solver(self, q):
        return q in SOLVER_QUESTIONS

    def usable(self, q):
        """The engines of a question that can run here, in their order."""
        return [e.name for e in self.engines.get(q, []) if e.name not in self.why]

    def can_ask(self, q):
        return bool(self.engines.get(q)) if self.is_solver(q) else bool(self.usable(q))

    def engines_for(self, q):
        """The analyses that answer a question as it stands: those chosen that can run here, else its first that
        can. A solver question: none (the solvers ticked answer it, in kicad2ems's own run)."""
        if self.is_solver(q):
            return []
        ok = self.usable(q)
        chosen = [n for n in self.choice.get(q, []) if n in ok]
        return chosen or ok[:1]

    def run_of(self, q):
        """The run a question's settings and page belong to: 'rf', or its first engine."""
        if self.is_solver(q) or not self.engines.get(q):
            return RF
        return (self.engines_for(q) or [self.engines[q][0].name])[0]

    def panels_of(self, q):
        """The runs whose settings a question shows: 'rf' for the solvers', else its engines' (those chosen, or
        its default; all of them where none can run, so that their settings can still be read)."""
        if self.is_solver(q):
            return [RF]
        return self.engines_for(q) or [e.name for e in self.engines.get(q, [])]

    def _solver_names(self, q):
        """The solvers ticked that answer a solver question, and whether auto is."""
        on = [e.name for e in self.engines.get(q, []) if e.name in self.boxes and self.boxes[e.name].isChecked()]
        return on, bool(self.boxes.get(AUTO) is not None and self.boxes[AUTO].isChecked())

    def can_dump(self, q):
        """Whether a question's engines, as chosen, can write field dumps."""
        es = {e.name: e for e in self.engines.get(q, [])}
        if q == 'lines':
            return False
        if self.is_solver(q):
            on, auto = self._solver_names(q)
            return any(es[n].fields for n in on) or (auto or not self.boxes) and any(e.fields for e in es.values())
        return any(es[n].fields for n in self.engines_for(q))

    def _row(self, q):
        """A row's cells from what is chosen for it."""
        it, es = self.rows[q], self.engines[q]
        self._setting = True
        try:
            ok = self.can_ask(q)
            gray = None if ok else QBrush(QColor('gray'))
            for col in range(4):
                it.setForeground(col, gray if gray is not None else QBrush())
            flags = it.flags() | Qt.ItemIsUserCheckable if ok else it.flags() & ~Qt.ItemIsUserCheckable
            it.setFlags(flags)
            if not ok:
                it.setCheckState(C_Q, Qt.Unchecked)
            by = {e.name: e for e in es}
            if not es:
                text, tip = '', self.missing[q]
            elif self.is_solver(q):
                on, auto = self._solver_names(q)
                if q == 'lines':
                    text = ' + '.join(short(by[n].label) for n in on) or ('auto' if auto or not self.boxes else 'line model')
                else:
                    text = ' + '.join((['auto'] if auto else []) + [short(by[n].label) for n in on]) or \
                           ('auto' if not self.boxes else 'no solver')
                tip = 'the solvers that answer it, in one run with the other RF questions: click to choose'
            else:
                names = self.engines_for(q)
                text = ' + '.join(by[n].label for n in names) or ' / '.join(e.label for e in es)
                tip = ('click to choose: ' + ', '.join(e.label for e in es)) if len(es) > 1 else by[es[0].name].plugin.tool
            more = len(es) > 1 or (self.is_solver(q) and bool(es))
            it.setText(C_BY, text + ('  ▾' if more and ok else ''))
            it.setToolTip(C_BY, tip)
            if ok and self.can_dump(q):
                it.setCheckState(C_FIELDS, Qt.Checked if self.fields.get(q) else Qt.Unchecked)
            else:
                it.setData(C_FIELDS, Qt.CheckStateRole, None)
            self._state(q)
        finally:
            self._setting = False

    def refresh(self):
        """Every row anew (the solvers ticked changed, an engine became available)."""
        for q in self.rows:
            self._row(q)

    def set_solver_boxes(self, boxes):
        """The solvers' tick boxes ({name: QCheckBox}, 'auto' among them): the RF rows show and set them."""
        self.boxes = dict(boxes)
        for w in self.boxes.values():
            w.toggled.connect(lambda _on: self.refresh())
        self.refresh()

    # ---- what is asked ----
    def asked(self):
        """{question: [engine names]} of the rows ticked, in the list's order: the engines chosen, [] for its
        default (a solver question: the solvers ticked, which the settings hold)."""
        return {q: ([] if self.is_solver(q) else list(self.choice[q])) for q, it in self.rows.items()
                if it.checkState(C_Q) == Qt.Checked and self.can_ask(q)}

    def asked_fields(self):
        """{question: its Fields tick} of the rows asked that have one."""
        return {q: bool(self.fields.get(q)) for q in self.asked() if self.can_dump(q)}

    def study(self):
        """The list as kicad2ems holds a study (a config's [study] tables)."""
        from kicad2ems.api.frontend import Study
        return Study(self.asked(), self.asked_fields(), 'study')

    def set_study(self, study):
        """The ticks, the engines and the Fields ticks of a Study (a config's): a question it does not ask
        unticked. An engine not installed here is left out; a solver question's solvers are the settings'."""
        self._setting = True
        try:
            for q, it in self.rows.items():
                on = q in study.asked and self.can_ask(q)
                it.setCheckState(C_Q, Qt.Checked if on else Qt.Unchecked)
                names = {e.name for e in self.engines[q]}
                self.choice[q] = [] if self.is_solver(q) else [n for n in study.asked.get(q, []) if n in names]
                self.fields[q] = bool(study.fields.get(q, False))
        finally:
            self._setting = False
        self.refresh()
        self.ticks_changed.emit()

    def jobs(self, preview=False, only=None):
        """The runs the questions asked take, in order: 'rf' when a solver question is asked, then the analyses
        of the others in the registry's order (run_order). preview: those that have one. only: a question (or a
        run) alone, ticked or not."""
        if only is not None:
            qs = [only] if only in self.rows else [q for q in self.rows if only == self.run_of(q)
                                                   or (only == RF and self.is_solver(q))][:1]
            qs = [q for q in qs if self.can_ask(q)]
        else:
            qs = list(self.asked())
        keys = set()
        for q in qs:
            keys |= {RF} if self.is_solver(q) else set(self.engines_for(q))
        return run_order(keys, preview, self.available())

    def asked_of(self, key, only=None):
        """The questions asked of a run ('rf' or an analysis), in the list's order."""
        qs = [only] if only in self.rows else list(self.asked())
        return tuple(q for q in qs if (self.is_solver(q) if key == RF else key in self.engines_for(q)))

    def set_fields(self, q, on):
        """A row's Fields tick, as its settings say (no default filled in: they hold what is asked)."""
        if q in self.rows and bool(self.fields.get(q)) != bool(on):
            self.fields[q] = bool(on)
            self._row(q)
            self.ticks_changed.emit()

    def fields_on(self, key):
        """Whether a run's field dumps are asked for: a Fields tick on one of its questions."""
        return any(self.fields.get(q) and self.can_dump(q) for q in self.asked_of(key))

    # ---- as the runs see it ----
    def available(self):
        return {a.key for a in ANALYSES if a.key not in self.why}

    def ticked(self):
        """The runs of the questions asked, in order."""
        return self.jobs()

    def set_ticked(self, keys):
        """The questions these runs answer ticked, each by that engine: 'rf' is S-parameters."""
        asked = {}
        for k in keys:
            for q in self.rows:
                if (k == RF and q == 'sparams') or (k != RF and any(e.name == k for e in self.engines[q])):
                    first = (self.usable(q) or [None])[0]
                    asked.setdefault(q, [])
                    if k != RF and k != first and k not in asked[q]:
                        asked[q].append(k)
        from kicad2ems.api.frontend import Study
        self.set_study(Study(asked, {q: self.fields.get(q, False) for q in asked}))

    def ask(self, key):
        """The questions a run answers asked too (those that can be, by that run where it is one of several
        engines: the others stay as they are): what a result proposed for it is to be run."""
        for q, it in self.rows.items():
            if key != RF and key in self.engines_for(q) and self.can_ask(q) and it.checkState(C_Q) != Qt.Checked:
                it.setCheckState(C_Q, Qt.Checked)

    def set_available(self, key, ok, why=''):
        """A run that cannot be made here: its engine is not offered, and a question nobody else answers is
        greyed, unticked, its State and tooltip saying why."""
        if ok:
            self.why.pop(key, None)
        else:
            self.why[key] = why or 'not installed'
            self.states.pop(key, None)
        self.refresh()
        q = self.current_question()
        if q is not None and any(e.name == key for e in self.engines.get(q, [])):
            self.selected.emit(q)                                   # its settings: the engines that can run now

    def set_tool(self, key, text):                                 # the rows read the solvers' boxes themselves
        self.refresh()

    def set_state(self, key, text, tone=''):
        """A run's state ('running', 'done 21:42', 'failed (exit 2)', 'not started: no rail'): on the rows of the
        questions it answers, up to its detail, the tooltip whole; tone: '', 'gray' or 'bad'."""
        if key in self.why:
            return
        self.states[key] = (text, tone)
        for q in self.rows:
            self._state(q)

    def state(self, key):
        """A run's state as it was set."""
        return self.states.get(key, ('', ''))[0]

    def clear_states(self):
        """Another board: the last one's runs say nothing of it."""
        self.states.clear()
        for q in self.rows:
            self._state(q)

    def _state(self, q):
        it = self.rows[q]
        if not self.engines[q]:
            text, tip, tone = 'not installed', self.missing[q], 'gray'
        elif not self.can_ask(q):
            why = '; '.join(f"{e.label}: {self.why[e.name]}" for e in self.engines[q] if e.name in self.why)
            text, tip, tone = 'not available', why, 'gray'
        else:
            keys = [RF] if self.is_solver(q) else self.engines_for(q)
            by = {e.name: e.label for e in self.engines[q]}
            got = [(k, *self.states[k]) for k in keys if self.states.get(k, ('', ''))[0]]
            cut = lambda t: t.split(' (')[0].split(': ')[0]
            if len(keys) > 1:
                same = len(got) == len(keys) and len({cut(t) for _, t, _ in got}) == 1
                text = cut(got[0][1]) if same else ' · '.join(f"{by.get(k, k)} {cut(t)}" for k, t, _ in got)
                tip = '\n'.join(f"{by.get(k, k)}: {t}" for k, t, _ in got)
            else:
                text, tip = (cut(got[0][1]), got[0][1]) if got else ('', '')
            tone = 'bad' if any(tn == 'bad' for _, _, tn in got) else 'gray' if got and all(tn == 'gray' for _, _, tn in got) else ''
        it.setText(C_STATE, text)
        it.setToolTip(C_STATE, tip)
        c = TONES.get(tone)
        it.setForeground(C_STATE, QBrush(QColor(c)) if c else QBrush())
        f = it.font(C_STATE)
        f.setBold('running' in text)
        it.setFont(C_STATE, f)

    # ---- the selection ----
    def current_question(self):
        q = self._q(self.currentItem())
        return q if q in self.rows else next(iter(self.rows), None)

    def current(self):
        """The run of the selected question: 'rf' or an analysis."""
        q = self.current_question()
        return self.run_of(q) if q else RF

    def select(self, key):
        """A question, or the first question (an asked one first) a run answers."""
        if key in self.rows:
            q = key
        else:
            qs = [q for q in self.rows if (self.is_solver(q) if key == RF else any(e.name == key for e in self.engines[q]))]
            if key != RF and self.current_question() in qs:
                return
            if key == RF and self.is_solver(self.current_question()):
                return
            asked = [q for q in qs if q in self.asked() and (key == RF or key in self.engines_for(q))]
            q = (asked or qs or [None])[0]
        if q is not None and self.current_question() != q:
            self.setCurrentItem(self.rows[q])

    def _current(self, cur, _old):
        if cur is not None and not self._is_row(cur):               # a group's heading: not a selection
            return
        if cur is not None:
            self.selected.emit(self._q(cur))

    # ---- the user's hand ----
    def _changed(self, it, col):
        if self._setting or not self._is_row(it):
            return
        q = self._q(it)
        if col == C_Q:
            self._row(q)
            self.ticks_changed.emit()
        elif col == C_FIELDS:
            self.fields[q] = it.checkState(C_FIELDS) == Qt.Checked
            self.fields_ticked.emit(q, self.fields[q])
            self.ticks_changed.emit()

    def _clicked(self, it, col):
        if col == C_BY and self._is_row(it) and self.can_ask(self._q(it)):
            q = self._q(it)
            if self.is_solver(q) or len(self.engines[q]) > 1:
                from PySide6.QtCore import QPoint
                at = QPoint(self.header().sectionViewportPosition(C_BY), self.visualItemRect(it).bottom() + 1)
                self.engine_menu(q).exec(self.viewport().mapToGlobal(at))       # under the cell

    def choose(self, q, name, on):
        """Tick or untick an engine of a question ('auto': its default alone). A solver question: the solver's
        tick box."""
        if self.is_solver(q):
            if name in self.boxes:
                self.boxes[name].setChecked(bool(on))
            return
        names = [e.name for e in self.engines[q]]
        if name == AUTO:
            self.choice[q] = []
        elif name in names:
            cur = set(self.choice[q] or self.engines_for(q)) if on else set(self.choice[q])
            cur = (cur | {name}) if on else (cur - {name})
            self.choice[q] = [n for n in names if n in cur]
        self._row(q)
        self.ticks_changed.emit()
        if self.current_question() == q:
            self.selected.emit(q)                                   # its settings: the engines' now

    def engine_menu(self, q, menu=None):
        """The menu of a question's engines: 'auto', then a tick each."""
        m = menu or QMenu(self)
        m.setToolTipsVisible(True)
        es = self.engines[q]
        if self.is_solver(q):
            for name in [AUTO] + [e.name for e in es]:
                box = self.boxes.get(name)
                if box is None:
                    continue
                a = m.addAction(box.text() or name)
                a.setCheckable(True)
                a.setChecked(box.isChecked())
                a.setToolTip(box.toolTip())
                a.toggled.connect(lambda on, n=name: self.choose(q, n, on))
            return m
        first = (self.usable(q) or [None])[0]
        label = next((e.label for e in es if e.name == first), '')
        a = m.addAction(f"auto ({label})" if label else 'auto')
        a.setCheckable(True)
        a.setChecked(not [n for n in self.choice[q] if n in self.usable(q)])
        a.triggered.connect(lambda _=False: self.choose(q, AUTO, True))
        m.addSeparator()
        for e in es:
            a = m.addAction(f"{e.label}  ({e.plugin.tool})")
            a.setCheckable(True)
            a.setChecked(e.name in self.choice[q])
            if e.name in self.why:
                a.setEnabled(False)
                a.setToolTip(self.why[e.name])
            a.toggled.connect(lambda on, n=e.name: self.choose(q, n, on))
        return m

    def _context(self, pos):
        it = self.itemAt(pos)
        if not self._is_row(it):
            return
        q = self._q(it)
        m = QMenu(self)
        a = m.addAction(f"Run {self.labels[q]} alone")
        a.setEnabled(self.can_ask(q))
        a.triggered.connect(lambda: self.run_one.emit(q))
        b = m.addAction('Show its page')
        b.triggered.connect(lambda: self.opened.emit(self.run_of(q)))
        if self.can_ask(q) and (self.is_solver(q) or len(self.engines[q]) > 1):
            self.engine_menu(q, m.addMenu('Answered by'))
        m.exec(self.viewport().mapToGlobal(pos))


StudyList = StudyTree                                   # its name before the questions
