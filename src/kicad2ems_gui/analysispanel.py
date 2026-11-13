"""
An analysis's settings and its run, for any analysis kicad2ems's registry holds (kicad2ems.api.frontend.analyses:
pcbqs's power integrity, near field and thermal): the form made from its options, in sections by their groups; its
command started as a child process; its output followed (the Run page shows the log, the status line its progress).

The panel is the analysis's part of the Study dock. It has no page: what a run leaves is shown where every
result is, its maps in the Viewer (it writes them as field dumps), its report and curves on the Results page.
Nothing here knows one analysis from another; what an analysis does differently it says through its plugin
(Analysis.command, status, discover and choices, suggest).

    panel = AnalysisPanel(analysis, win)     # win: the window (its board, its output folder), or None alone
    panel.values(), panel.set_values({...}), panel.reset()
    panel.start(preview=False), panel.stop(), panel.proc, panel.out
    config_values(panel)                     # what a config's [analysis.<name>] table holds of it
    panel.set_runs([{...}, ...]), panel.runs()   # an analysis a study may hold several of (Analysis.several: a
                                             # board's rails): a table of what differs, a run each, in order
"""
import os
import re

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QFormLayout, QLineEdit, QPushButton,
                               QPlainTextEdit, QCheckBox, QComboBox, QFileDialog, QProgressBar, QLabel, QInputDialog,
                               QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)

UNSET = '(default)'                         # a choice left to the tool's default
CELL = '(the selected cell)'                # a pick's key for the runs table's selected cell (pick_kind, take_pick)

from .panels import Section, FlowLayout
from .toolprocess import run_tool

OWN = ('board', 'out')                      # a config table's keys that are the panel's own: its board, its folder


def typed(option, value):
    """A form's value as a config holds it: a number where the option is one, a list for a repeatable one, None
    when it is not set (empty, or the option's default)."""
    kind = option['kind']
    if kind == 'bool':
        return True if value else None
    text = '' if value is None else str(value).strip()
    if kind == 'list':
        items = [s.strip() for s in re.split(r'\n|,(?=\s*[^\s,=]+\s*=)', text) if s.strip()]
        return items or None
    if not text or text == str(option['default']):
        return None
    if kind in ('float', 'int'):
        try:
            v = float(text)
            return int(v) if kind == 'int' and v == int(v) else v
        except ValueError:
            return text
    return text


def config_values(panel, base=None, vals=None):
    """What a config's [analysis.<name>] table holds of a panel: the options set (of vals, a run of its table,
    when given), and its own board and folder; paths (the analysis's, and those two) relative to `base`."""
    out = {}
    rel = lambda p: os.path.relpath(os.path.abspath(p), base).replace(os.sep, '/') if base else p
    for key, edit in (('board', panel.board), ('out', panel.outdir)):
        if edit.text().strip():
            out[key] = rel(edit.text().strip())
    vals = panel.values() if vals is None else vals
    for o in panel.options:
        v = typed(o, vals.get(o['key']))
        if v is not None:
            out[o['key']] = rel(v) if o['key'] in panel.a.paths and isinstance(v, str) else v
    return out


class AnalysisPanel(QWidget):
    """One analysis's settings (the sections of its options, its own board and folder), the buttons its plugin
    gives it (Find, what its result proposes for another analysis) and its status line."""
    changed = Signal()                                      # a setting was edited by hand (not set_values: a
                                                            # config loaded, a test)
    ended = Signal(int)                                     # a run ended, all of its rows: 0, or the first failure

    def __init__(self, analysis, win=None):
        super().__init__()
        self.a, self.win = analysis, win
        self.proc, self.out, self.result, self._preview, self._found, self._setting = None, None, None, False, None, 0
        self.required = set()                               # options a run needs set (proposed without a value)
        self.options = list(analysis.options())
        self.w, self.sections, self.forms = {}, {}, {}      # an option's field; a group's section, and its form
        v = QVBoxLayout(self)
        self._layout = v
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        files = QWidget()
        f = QFormLayout(files)
        f.setContentsMargins(0, 0, 0, 0)
        self.board = QLineEdit()
        self.board.setPlaceholderText("the study's board" if win is not None else 'a .kicad_pcb, or a board.json')
        self.board.setToolTip('.kicad_pcb (or a run\'s <name>_board.json); empty: the board under Board, above')
        b = QPushButton('…')
        b.setFixedWidth(28)
        b.clicked.connect(self._browse)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.board, 1)
        rl.addWidget(b)
        f.addRow('Board', row)
        self.outdir = QLineEdit()
        self.outdir.setPlaceholderText('a folder per run, in the output folder')
        f.addRow('Output folder', self.outdir)
        for edit in (self.board, self.outdir):
            edit.textChanged.connect(self._edited)
        self.sections['Files'] = Section('Files', files)
        v.addWidget(self.sections['Files'])
        self.pick_btns = {}                                         # {option key: its pick button}
        groups = {}
        for o in self.options:
            groups.setdefault(o.get('group') or 'Settings', []).append(o)
        for i, (g, opts) in enumerate(groups.items()):
            inner = QWidget()
            fl = QFormLayout(inner)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setRowWrapPolicy(QFormLayout.WrapLongRows)
            for o in opts:
                if o['kind'] == 'bool':                             # named as the other options are, what it does
                    wid = QCheckBox(o['key'].replace('_', ' '))     # in its tooltip: a long line beside the box made
                    wid.setChecked(bool(o['default']))              # the panel wider than its column
                elif o['kind'] == 'list':
                    wid = QPlainTextEdit()
                    wid.setPlaceholderText('one a line')
                    wid.setFixedHeight(70)
                elif o.get('choices'):                              # one of a few: a drop-down, the default first
                    wid = QComboBox()
                    wid.addItems([UNSET if o['default'] in ('', None) else f"{o['default']} (default)",
                                  *[str(c) for c in o['choices'] if c != o['default']]])
                else:
                    wid = QLineEdit()
                    wid.setPlaceholderText(str(o['default']) if o['default'] not in ('', None) else '')
                wid.setToolTip(f"{o['flag']}: {o['help']}")
                (wid.toggled if o['kind'] == 'bool' else wid.currentIndexChanged if isinstance(wid, QComboBox)
                 else wid.textChanged).connect(self._edited)
                self.w[o['key']] = wid
                label = o['key'].replace('_', ' ').capitalize() if o['kind'] != 'bool' else ''
                if o.get('pick') and self.win is not None and hasattr(self.win, 'start_pick'):
                    fl.addRow(self._pick_label(label, o), wid)      # the setting, picked on the board (planview)
                else:
                    fl.addRow(label, wid)
            self.forms[g] = fl
            self.sections[g] = Section(g, inner, i == 0)            # the first group open: what a run is of
            v.addWidget(self.sections[g])
        self._after_sections = v.count()                            # where a page's own section goes (add_section)
        # what a study may hold several of (Analysis.several, its several_keys): those settings as a table, a
        # row a run (a board's rails), the rest of the form shared by them all
        self.run_keys = [k for k in getattr(analysis, 'several_keys', ()) or () if k in self.w] \
            if getattr(analysis, 'several', '') else []
        self.table = None
        if self.run_keys:
            self._run_table(v)
        self.buttons = FlowLayout()
        self.find_btn = None
        if getattr(analysis, 'finds', ''):                          # the board proposes settings
            self.find_btn = QPushButton(f"Find {analysis.finds}")
            self.find_btn.setToolTip(f"List the board's {analysis.finds}, and pick one: its settings into the form")
            self.find_btn.clicked.connect(self.find)
            self.buttons.addWidget(self.find_btn)
        self.suggest_btns = []
        self.run_btn = QPushButton('Run')
        self.run_btn.clicked.connect(lambda: self.start())
        self.stop_btn = QPushButton('Stop')
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        for b in (self.run_btn, self.stop_btn):
            self.buttons.addWidget(b)
            b.setVisible(win is None)                               # in the window: its toolbar's Run and Stop
        holder = QWidget()
        holder.setLayout(self.buttons)
        v.addWidget(holder)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.hide()
        v.addWidget(self.busy)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status.setContentsMargins(6, 2, 6, 4)
        v.addWidget(self.status)
        self.log = QPlainTextEdit()                                 # the Run page shows it (Log of)
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        ok, why = analysis.check()
        if not ok:
            self.setEnabled(False)
            self.status.setText(why)

    # ---- several runs: a table of what differs between them ----
    def _run_table(self, v):
        what = self.a.several
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        t = QTableWidget(0, len(self.run_keys))
        t.setHorizontalHeaderLabels([k.replace('_', ' ').capitalize() for k in self.run_keys])
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)     # each heading whole; the
        t.horizontalHeader().setStretchLastSection(True)                            # dock scrolls sideways if
        t.verticalHeader().hide()                                                   # it must
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for c, k in enumerate(self.run_keys):
            o = next(o for o in self.options if o['key'] == k)
            t.horizontalHeaderItem(c).setToolTip(f"{o['flag']}: {o['help']}" + (' (several: comma-separated)'
                                                                                if o['kind'] == 'list' else ''))
        t.itemChanged.connect(lambda *_: self._edited())
        lay.addWidget(t)
        row = QHBoxLayout()
        for text, slot in ((f"Add a {what}", self.add_run), (f"Remove the {what}", self.remove_run)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        if self.win is not None and hasattr(self.win, 'start_pick') and any(self.pick_kind(k) for k in self.run_keys):
            b = QPushButton('Pick')                                 # the selected cell, picked on the board
            b.setCheckable(True)
            b.setToolTip("Pick the selected cell on the board (a net, or a part: by its column): click in the "
                         "Viewer's plan; this button again ends it")
            b.toggled.connect(lambda on: self.win.start_pick(self, CELL) if on else self.win.end_pick(self, CELL))
            row.addWidget(b)
            self.pick_btns[CELL] = b
            t.currentCellChanged.connect(lambda *_: b.isChecked() and self.win.start_pick(self, CELL))   # its column's
        row.addStretch(1)
        lay.addLayout(row)
        self.table = t
        title = what.capitalize() + 's'
        self.sections[title] = Section(title, holder, True)
        v.insertWidget(1, self.sections[title])                     # after Files: what the runs are of
        self._after_sections += 1
        for k in self.run_keys:                                     # in the table, not the form
            for fl in self.forms.values():
                if fl.indexOf(self.w[k]) >= 0:
                    fl.setRowVisible(self.w[k], False)
        self.add_run()

    # ---- a setting picked on the board ----
    def _pick_label(self, label, o):
        """A form row's label with a button that picks the setting on the board: clicks in the Viewer's plan
        name a net or a part into it (the option's `pick`), until the button is let go."""
        from PySide6.QtWidgets import QToolButton
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(QLabel(label))
        b = QToolButton()
        b.setText('Pick')
        b.setCheckable(True)
        many = o['pick'].endswith('s')
        b.setToolTip(f"Pick {'them' if many else 'it'} on the board: click "
                     + ("traces" if o['pick'].startswith('net') else "parts")
                     + f" in the Viewer's plan ({'again takes one out; ' if many else ''}this button again ends it)")
        b.toggled.connect(lambda on, key=o['key']: self.win.start_pick(self, key) if on else self.win.end_pick(self, key))
        lay.addWidget(b)
        self.pick_btns[o['key']] = b
        return box

    def _cell(self):
        """(row, column key) of the table's selected cell, or None."""
        t = self.table
        if t is None or t.currentRow() < 0 or t.currentColumn() < 0:
            return None
        return t.currentRow(), self.run_keys[t.currentColumn()]

    def pick_kind(self, key):
        if key == CELL:                                             # the table's selected cell: its column's
            cell = self._cell()
            return self.pick_kind(cell[1]) if cell else None
        return next((o.get('pick') for o in self.options if o['key'] == key), None)

    def picked_names(self, key):
        """The names a picked setting holds now."""
        if key == CELL:
            cell = self._cell()
            it = self.table.item(cell[0], self.run_keys.index(cell[1])) if cell else None
            text = it.text() if it is not None else ''
        else:
            w = self.w[key]
            text = w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text()
        return [x.strip() for x in re.split(r'[\n,]', text) if x.strip()]

    def take_pick(self, key, name):
        """A name picked on the board into setting `key`: one that holds several takes it in, or out when it is
        there already; one that holds one is set. Returns the names it now holds."""
        kind = self.pick_kind(key) or ''
        if key == CELL:
            cell = self._cell()
            if cell is None or not kind:
                return []
            names = self.picked_names(key)
            names = ([n for n in names if n != name] if name in names else names + [name]) if kind.endswith('s') else [name]
            self.table.item(cell[0], self.run_keys.index(cell[1])).setText(', '.join(names))
            return names
        w = self.w[key]
        if kind.endswith('s'):
            names = self.picked_names(key)
            names = [n for n in names if n != name] if name in names else names + [name]
            (w.setPlainText('\n'.join(names)) if isinstance(w, QPlainTextEdit) else w.setText(', '.join(names)))
        else:
            names = [name]
            w.setPlainText(name) if isinstance(w, QPlainTextEdit) else w.setText(name)
        return names

    def add_run(self, values=None):
        """A row of the table (a run): from values, else empty (its fields' defaults)."""
        t = self.table
        self._setting += 1
        try:
            r = t.rowCount()
            t.insertRow(r)
            for c, k in enumerate(self.run_keys):
                v = (values or {}).get(k)
                text = ', '.join(map(str, v)) if isinstance(v, (list, tuple)) else ('' if v is None else
                                                                                    f"{v:g}" if isinstance(v, float) else str(v))
                t.setItem(r, c, QTableWidgetItem(text))
        finally:
            self._setting -= 1
        self._fit_table()
        if values is None:
            self._edited()

    def _fit_table(self):
        """The table as tall as its rows (two at least), not a box of empty space."""
        t = self.table
        rows = max(t.rowCount(), 2)
        h = t.horizontalHeader().height() + rows * t.verticalHeader().defaultSectionSize() + 2 * t.frameWidth()
        bar = t.horizontalScrollBar().sizeHint().height()
        t.setFixedHeight(h + bar)

    def remove_run(self):
        """The selected row out (the last one stays: a run is of one at least)."""
        t = self.table
        r = t.currentRow() if t.currentRow() >= 0 else t.rowCount() - 1
        if t.rowCount() > 1:
            t.removeRow(r)
            self._fit_table()
            self._edited()

    def _row(self, r):
        out = {}
        for c, k in enumerate(self.run_keys):
            it = self.table.item(r, c)
            out[k] = it.text().strip() if it is not None else ''
            o = next(o for o in self.options if o['key'] == k)
            if o['kind'] == 'list':                                 # a list: its items, comma- or line-separated
                out[k] = '\n'.join(x.strip() for x in re.split(r'\n|,(?=\s*[^\s,=]+\s*=)', out[k]) if x.strip())
        return out

    def runs(self):
        """The runs the table asks, [values]: the shared settings with each row's (one row: values()). A row with
        nothing in it is left out, unless it is the only one."""
        if not self.table:
            return [self.values()]
        shared = self._shared()
        rows = [self._row(r) for r in range(self.table.rowCount())]
        filled = [r for r in rows if any(r.values())] or rows[:1]
        return [dict(shared, **r) for r in filled]

    def set_runs(self, runs):
        """The table from several runs' settings ([{key: value}]): each its row, the shared settings the first's."""
        runs = [dict(r) for r in runs] or [{}]
        self.set_values(runs[0])
        if not self.table:
            return
        self._setting += 1
        try:
            self.table.setRowCount(0)
        finally:
            self._setting -= 1
        for r in runs:
            self.add_run(r)

    def _shared(self):
        return {k: v for k, v in self._form_values().items() if k not in self.run_keys}

    # ---- the settings ----
    def _edited(self, *_):
        if not self._setting:
            self.changed.emit()

    def needs(self, asked=(), to_come=()):
        """What a run of these settings still needs, [dict(text, key)]: the options a proposal left without a value,
        and what the analysis says (Analysis.missing: kicad2ems API 2.9; before it, nothing more). to_come: the
        analyses asked with it that run before it and have no result yet: what they will give is not missing."""
        out = []
        runs = self.runs()
        for i, vals in enumerate(runs):                             # each run's (a table's rows: said by which)
            said = f"{self._label(vals) or f'{self.a.several} {i + 1}'}: " if len(runs) > 1 else ''
            if asked:
                vals = self.a.for_questions(vals, tuple(asked))
            out += [dict(text=said + f"set {k.replace('_', ' ')}", key=k) for k in sorted(self.required)
                    if not str(vals.get(k, '')).strip()]
            if hasattr(self.a, 'missing'):
                latest = self.win.latest_results() if self.win is not None and hasattr(self.win, 'latest_results') else {}
                latest = {**{k: None for k in to_come}, **latest}
                try:
                    out += [dict(text=said + str(m['text']), key=m.get('key'))
                            for m in self.a.missing(vals, self.board_path() or None, latest)]
                except Exception:                                   # noqa: BLE001 (a plugin's check: never the window's end)
                    pass
        return out

    def focus(self, key):
        """The field of an option in view, its section open; no such option: the first section."""
        wid = self.w.get(key)
        for g, fl in self.forms.items():
            if wid is not None and fl.indexOf(wid) >= 0 and g in self.sections:
                self.sections[g].set_expanded(True)
        if wid is not None:
            wid.setFocus()

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, 'Board', '', 'KiCad board (*.kicad_pcb);;kicad2ems board (*.json)')
        if p:
            self.board.setText(p)

    def add_section(self, title, widget, form=None, expanded=False):
        """A section of the page's own under the options' (the circuit's model values): its widget, and the form
        its rows are in."""
        self.sections[title] = Section(title, widget, expanded)
        if form is not None:
            self.forms[title] = form
        self._layout.insertWidget(self._after_sections, self.sections[title])
        self._after_sections += 1
        return self.sections[title]

    def values(self):
        """The settings: the form's, and with a table of runs the first run's (runs(): all of them)."""
        out = self._form_values()
        if self.table:
            out.update(self._row(0) if self.table.rowCount() else {})
        return out

    def _form_values(self):
        out = {}
        for k, wid in self.w.items():
            if isinstance(wid, QCheckBox):
                out[k] = wid.isChecked()
            elif isinstance(wid, QPlainTextEdit):
                out[k] = wid.toPlainText()
            elif isinstance(wid, QComboBox):
                out[k] = '' if wid.currentIndex() <= 0 else wid.currentText()
            else:
                out[k] = wid.text()
        return out

    def set_values(self, vals):
        """Some of the form's fields (the others stay): a list as lines, None as empty. With a table of runs, its
        keys into the first row."""
        if self.table and any(k in vals for k in self.run_keys):
            if not self.table.rowCount():
                self.add_run({})
            self._setting += 1
            try:
                for c, k in enumerate(self.run_keys):
                    if k in vals:
                        v = vals[k]
                        text = ', '.join(map(str, v)) if isinstance(v, (list, tuple)) else (
                            '' if v is None else f"{v:g}" if isinstance(v, float) else str(v))
                        self.table.setItem(0, c, QTableWidgetItem(text))
            finally:
                self._setting -= 1
        self._setting += 1
        try:
            for k, v in vals.items():
                wid = self.w.get(k)
                if wid is None:
                    continue
                if isinstance(wid, QCheckBox):
                    wid.setChecked(v is True or str(v).strip().lower() in ('1', 'true', 'yes', 'on'))
                elif isinstance(wid, QPlainTextEdit):
                    wid.setPlainText('\n'.join(map(str, v)) if isinstance(v, (list, tuple)) else ('' if v is None else str(v)))
                elif isinstance(wid, QComboBox):
                    wid.setCurrentIndex(max(wid.findText(str(v)), 0) if v not in (None, '') else 0)
                else:
                    wid.setText('' if v is None else (f"{v:g}" if isinstance(v, float) else str(v)))
        finally:
            self._setting -= 1
        self.required -= {k for k, v in vals.items() if str(v if v is not None else '').strip()}

    def set_own(self, board, out):
        """The panel's own board and output folder (None or '': the study's)."""
        self._setting += 1
        self.board.setText(str(board or ''))
        self.outdir.setText(str(out or ''))
        self._setting -= 1

    def reset(self):
        """The form as it is made: every field empty (its default), no board or folder of its own."""
        self.set_values({o['key']: (bool(o['default']) if o['kind'] == 'bool' else '') for o in self.options})
        self._setting += 1
        self.board.clear()
        self.outdir.clear()
        self._setting -= 1
        self.required = set()
        self.result = None
        self._suggestions([])
        if self.table:
            self._setting += 1
            self.table.setRowCount(0)
            self._setting -= 1
            self.add_run({})
        if self.isEnabled():
            self.status.setText('')

    def board_path(self):
        """The board named here, else the study's (the window's settings)."""
        p = self.board.text().strip()
        if not p and self.win is not None:
            try:
                p = self.win.setup.values().get('board') or ''
            except Exception:                                       # a field half typed
                p = ''
        return p

    def default_out(self, board, tag, preview=False):
        """Where a run goes when no folder is named: in the window a folder per run under its output folder
        (MainWindow.tool_out); alone, <name>_<tag> beside the board."""
        if self.win is not None and hasattr(self.win, 'tool_out'):
            return self.win.tool_out(self.a.name, board, tag, preview)
        base = os.path.join(os.path.dirname(os.path.abspath(board)) if board else os.getcwd(),
                            f"{self.a.name}_" + ''.join(c if c.isalnum() else '_' for c in tag))
        return os.path.join(base, 'preview') if preview else base

    def say(self, text):
        self.log.appendPlainText(text)

    def _running(self, on):
        self.run_btn.setEnabled(not on)
        self.stop_btn.setEnabled(on)
        if self.find_btn is not None:
            self.find_btn.setEnabled(not on)
        self.busy.setVisible(on)

    # ---- a run ----
    def start(self, preview=False):
        """Start the analysis (its preview): with a table of runs, each row's after the other (a preview: the
        first's alone). The status line says why when it cannot start; ended(code) when it all ends."""
        if self.proc is not None or (preview and not self.a.previewed):
            return
        runs = self.runs()
        self._queue = runs[1:] if self.table and not preview else []
        self._count, self._failed = len(self._queue) + 1, 0
        self.log.clear()                                            # one log for the rows' runs together
        while not self._start_one(runs[0], preview):                # (one that cannot start: said, the next tried)
            if not self._queue:
                return
            self._failed = 1
            runs = [self._queue.pop(0)]

    def _start_one(self, vals, preview):
        asked = tuple(getattr(self, 'asked', None) or ())           # the questions this run is asked (the study's)
        if asked:
            vals = self.a.for_questions(vals, asked)
        unset = sorted(k for k in self.required if not str(vals.get(k, '')).strip())
        if unset:
            self.status.setText(f"Set {', '.join(k.replace('_', ' ') for k in unset)} before Run: "
                                f"{'it was' if len(unset) == 1 else 'they were'} not known where these settings came from")
            return False
        board = self.board_path() or None
        try:
            named = self.outdir.text().strip()
            tag = self.a.tag(vals)
            if named and self._count > 1:                           # several runs: a folder each under the named one
                named = os.path.join(named, ''.join(c if c.isalnum() else '_' for c in tag))
            out = (os.path.join(named, 'preview') if preview else named) if named else \
                self.default_out(board, tag, preview)
            latest = self.win.latest_results() if self.win is not None and hasattr(self.win, 'latest_results') else {}
            argv = self.a.command(vals, board, os.path.abspath(out), preview=preview, results=latest)
        except ValueError as e:
            self.status.setText((f"{self._label(vals) or self.a.several}: " if self._count > 1 else '') + str(e))
            return False
        self.out, self._preview, self._vals = os.path.abspath(out), preview, vals
        from kicad2ems.api.frontend import mark_run
        from kicad2ems.study import provided
        mark_run(self.out, self.a.name, asked or provided(self.a), preview)     # whose run this folder is
        self.say('$ ' + ' '.join(['python', *argv[1:]] if os.path.basename(argv[0]).startswith('python') else argv))
        self._running(True)
        self.status.setText(self._progress('running…'))
        run_tool(self, argv, self._stdout, self._finished, env=dict(self.a.env or {}))
        return True

    def _label(self, vals):
        """A run of the table by its first column (the rail's net), or ''."""
        return str(vals.get(self.run_keys[0]) or '') if self.run_keys else ''

    def _progress(self, text):
        """A status line that says which run of how many, when there are several."""
        if getattr(self, '_count', 1) <= 1:
            return text
        k = self._count - len(self._queue)
        return f"{self.a.several} {k} of {self._count} ({self._label(self._vals)}): {text}"

    def stop(self):
        if self.proc is not None:
            self.proc.kill()

    def _read(self):
        return bytes(self.proc.readAllStandardOutput()).decode(errors='replace') if self.proc is not None else ''

    def _stdout(self):
        for line in self._read().splitlines():
            if re.search(r'\.py:\d+: \w*Warning', line):            # a library's warning: not the tool's word
                continue
            self.say(line)
            st = self.a.status(line)
            if st:
                self.status.setText(st)

    def _finished(self, code, _status=None):
        if self.proc is not None:
            self._stdout()
            self.proc.deleteLater()
            self.proc = None
        self._running(False)
        from kicad2ems.api.frontend import analysis_of
        made = analysis_of(self.out) if code == 0 else None
        if made is None or made[0] != self.a.name:
            lines = [l for l in self.log.toPlainText().splitlines() if l.strip()]
            errs = [l for l in lines if 'error' in l.lower() or l.startswith(('RuntimeError', 'ValueError'))]
            last = (errs or lines or [''])[-1].strip()
            self.status.setText(self._progress(f"the run failed (exit {code})" + (f": {last[:200]}" if last else '')
                                               + ' (the whole log: the Run page)'))
            self.status.setToolTip('\n'.join((errs or lines)[-8:]))
            self._failed = self._failed or (code or 1)
        else:
            self.status.setToolTip('')
            rep = self.a.report(self.out) or {}
            self.status.setText(self._progress('preview ready' if self._preview else
                                               ('done: ' + rep['summary'] if rep.get('summary') else 'done')))
            self.show_result(self.out)
        queue = getattr(self, '_queue', [])
        while queue:                                                # the next row's run (one that cannot start: said,
            nxt = queue.pop(0)                                      # the others go on)
            if self._start_one(nxt, False):
                return
            self._failed = self._failed or 1
        self.ended.emit(getattr(self, '_failed', 0) if code == 0 else (code or 1))

    # ---- what a result proposes, what the board proposes ----
    def show_result(self, folder):
        """A result of this analysis is the one shown: what it proposes for other analyses, as buttons."""
        self.result = folder
        try:
            self._suggestions(self.a.suggest(folder) if self.win is not None else [])
        except Exception:                                           # a plugin's fault never stops the window
            self._suggestions([])

    def _suggestions(self, items):
        for b in self.suggest_btns:
            self.buttons.removeWidget(b)
            b.deleteLater()
        self.suggest_btns = []
        for s in items:
            if s.get('to') not in getattr(self.win, 'pages', {}):
                continue
            b = QPushButton(s.get('label') or f"Copy to {s['to']}")
            b.setToolTip(s.get('note', ''))
            b.clicked.connect(lambda _=False, s=s: self.win.apply_suggestion(self, s))
            self.buttons.addWidget(b)
            self.suggest_btns.append(b)

    def find(self):
        """The analysis's discover command on the board; what it finds to pick from, the pick into the form."""
        if self.proc is not None:
            return
        try:
            argv = self.a.discover(self.values(), self.board_path() or None)
        except ValueError as e:
            self.status.setText(str(e))
            return
        if not argv:
            return
        self._found = []
        self.say('$ ' + ' '.join(['python', *argv[1:]]))
        self.status.setText(f"finding {self.a.finds}…")
        self._running(True)

        def output():
            self._found.append(self._read())

        def finished(code, _status=None):
            if self.proc is not None:
                output()
                self.proc.deleteLater()
                self.proc = None
            self._running(False)
            text = ''.join(self._found)
            picks = self.a.choices(text) if code == 0 else None
            if picks is None:
                self.say(text)
                self.status.setText(f"finding {self.a.finds} failed (exit {code}): the Run page has the log")
                return
            self.pick(picks)
        run_tool(self, argv, output, finished)

    def pick(self, choices):
        """One of [(label, values)] into the form: the only one, else the one chosen in a dialog."""
        if not choices:
            self.status.setText(f"no {self.a.finds} found on this board")
            return
        labels = [label for label, _ in choices]
        if len(choices) == 1:
            label = labels[0]
        else:
            label, ok = QInputDialog.getItem(self, f"Find {self.a.finds}", 'Use:', labels, 0, False)
            if not ok:
                return
        self.set_values(dict(choices)[label])
        self.changed.emit()
        self.status.setText(f"{label.split(' (')[0]}: set; Run" + (' or Preview' if self.a.previewed else ''))
