"""
The study: one board, the analyses made of it, and which of them a Run includes.

    ANALYSES                    what the window can run on a board, in the order it runs them
    with_needs(keys)            keys and the analyses they start from, in that order
    dependents(key)             the analyses that start from key's results
    run_order(ticked, preview)  what a Run (a Preview) of the ticked analyses starts, in order
    StudyList                   the list in the Study dock: a tick, what runs it and its state per analysis

An analysis is a tool of its own behind one of the window's pages (kicad2ems itself for S-parameters, pcbqs's
tools for the power ones): the list only says which to run and shows which settings; the pages still start their
tools and read their results. `needs` is how one analysis follows another: Thermal starts from Power integrity's DC
solve (the copper's loss is its heat source), so ticking it ticks Power integrity and it runs after it.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Analysis:
    key: str
    title: str
    tool: str               # what runs it, as the list shows it
    page: str = ''          # its page (a name of app.PANELS); '': the shared Viewer, Run and Results
    needs: tuple = ()       # the analyses whose results it starts from
    preview: bool = False   # it has a preview (the model and meshes, no solve)
    planned: bool = False   # no tool for it yet: listed, greyed
    note: str = ''          # the list's tooltip


ANALYSES = (
    Analysis('rf', 'S-parameters', 'the solvers ticked', preview=True,
             note="kicad2ems's run: the solvers ticked under Solvers, their S-parameters, fields and antenna results"),
    Analysis('pdn', 'Power integrity', 'pcbqs.pdn', page='PDN',
             note="a rail's DC drop and the impedance its loads see"),
    Analysis('thermal', 'Thermal', '', needs=('pdn',), planned=True,
             note="starts from Power integrity's DC solve: the copper's loss is its heat source (the parts' own "
                  "dissipation later). No thermal solver yet"),
    Analysis('mqs', 'Near field', 'pcbqs.mqs', page='Near field', preview=True,
             note="a converter's input loop and its magnetic near field"),
    Analysis('circuit', 'Circuit', 'pcbqs.power_circuit', page='Circuit',
             note='ngspice operating points of the circuit model, with the copper it extracts when asked'),
)
BY_KEY = {a.key: a for a in ANALYSES}


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
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView, QMenu

TONES = {'': None, 'gray': 'gray', 'bad': '#c62828'}


class StudyList(QTreeWidget):
    """The analyses: a tick (Run and Preview include it), what runs it, its state. The selected one's settings
    are the ones the dock shows."""
    selected = Signal(str)              # the analysis whose settings to show
    ticks_changed = Signal()
    opened = Signal(str)                # double-clicked: its page
    run_one = Signal(str)               # the context menu: run this one alone

    def __init__(self):
        super().__init__()
        self.setHeaderLabels(['Analysis', 'With', 'State'])
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)    # every row shown, a long State cut short
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.ElideRight)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.rows, self.why, self._setting = {}, {}, False
        for a in ANALYSES:
            it = QTreeWidgetItem([a.title, a.tool, ''])
            it.setData(0, Qt.UserRole, a.key)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Unchecked)
            it.setToolTip(0, a.note)
            self.addTopLevelItem(it)
            self.rows[a.key] = it
            if a.planned:
                self.set_available(a.key, False, a.note)
        hd = self.header()
        hd.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hd.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hd.setStretchLastSection(True)
        self.setFixedHeight(self.sizeHintForRow(0) * len(ANALYSES) + hd.sizeHint().height() + 2 * self.frameWidth() + 4)
        self.itemChanged.connect(self._ticked)
        self.currentItemChanged.connect(lambda cur, _old: cur is not None and self.selected.emit(cur.data(0, Qt.UserRole)))
        self.itemDoubleClicked.connect(lambda it, _col: self.opened.emit(it.data(0, Qt.UserRole)))
        self.setCurrentItem(self.rows[ANALYSES[0].key])

    # ---- which run ----
    def available(self):
        return {k for k in self.rows if k not in self.why}

    def ticked(self):
        return [k for k, it in self.rows.items() if it.checkState(0) == Qt.Checked and k not in self.why]

    def set_ticked(self, keys):
        self._setting = True
        try:
            want = set(with_needs(keys)) & self.available()
            for k, it in self.rows.items():
                it.setCheckState(0, Qt.Checked if k in want else Qt.Unchecked)
        finally:
            self._setting = False
        self.ticks_changed.emit()

    def _ticked(self, it, col):
        """A tick: what the analysis starts from ticked with it; unticked, what starts from it unticked too."""
        if col != 0 or self._setting:
            return
        key, on = it.data(0, Qt.UserRole), it.checkState(0) == Qt.Checked
        self._setting = True
        try:
            if on and key in self.why:                              # cannot run here: stays unticked
                it.setCheckState(0, Qt.Unchecked)
                return
            for k in (with_needs([key]) if on else dependents(key)):
                if k != key and k not in self.why:
                    self.rows[k].setCheckState(0, Qt.Checked if on else Qt.Unchecked)
        finally:
            self._setting = False
        self.ticks_changed.emit()

    def set_available(self, key, ok, why=''):
        """An analysis that cannot run here: greyed, unticked, its State and tooltip saying why."""
        it = self.rows[key]
        if ok:
            self.why.pop(key, None)
            it.setToolTip(2, '')
        else:
            self.why[key] = why
            self._setting = True
            it.setCheckState(0, Qt.Unchecked)
            self._setting = False
            it.setText(2, 'planned' if BY_KEY[key].planned else 'not installed')
            it.setToolTip(2, why)
        gray = None if ok else QBrush(QColor('gray'))
        for col in range(3):
            it.setForeground(col, gray if gray is not None else QBrush())
        flags = it.flags()
        it.setFlags(flags | Qt.ItemIsUserCheckable if ok else flags & ~Qt.ItemIsUserCheckable)

    # ---- what the list shows ----
    def set_tool(self, key, text):
        """What runs an analysis, when it changes (the solvers ticked for S-parameters)."""
        if key in self.rows:
            self.rows[key].setText(1, text)
            self.rows[key].setToolTip(1, text)

    def set_state(self, key, text, tone=''):
        """An analysis's state ('running', 'done 21:42', 'failed (exit 2)', 'not started: no rail'): the column
        shows it up to its detail ('failed', 'not started'), the tooltip whole; tone: '', 'gray' or 'bad'."""
        it = self.rows.get(key)
        if it is None or key in self.why:
            return
        it.setText(2, text.split(' (')[0].split(': ')[0])
        it.setToolTip(2, text)
        c = TONES.get(tone)
        it.setForeground(2, QBrush(QColor(c)) if c else QBrush())
        f = it.font(2)
        f.setBold(text.startswith('running'))
        it.setFont(2, f)

    def state(self, key):
        """The state as it was set (the tooltip's: with its detail)."""
        return self.rows[key].toolTip(2) or self.rows[key].text(2)

    def current(self):
        it = self.currentItem()
        return it.data(0, Qt.UserRole) if it is not None else ANALYSES[0].key

    def select(self, key):
        if key in self.rows and self.current() != key:
            self.setCurrentItem(self.rows[key])

    def _menu(self, pos):
        it = self.itemAt(pos)
        if it is None:
            return
        key = it.data(0, Qt.UserRole)
        m = QMenu(self)
        a = m.addAction(f"Run {BY_KEY[key].title} alone")
        a.setEnabled(key not in self.why)
        a.triggered.connect(lambda: self.run_one.emit(key))
        b = m.addAction('Show its page')
        b.triggered.connect(lambda: self.opened.emit(key))
        m.exec(self.viewport().mapToGlobal(pos))
