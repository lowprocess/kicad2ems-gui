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
"""
import os
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QFormLayout, QLineEdit, QPushButton,
                               QPlainTextEdit, QCheckBox, QComboBox, QFileDialog, QProgressBar, QLabel, QInputDialog)

UNSET = '(default)'                         # a choice left to the tool's default

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


def config_values(panel, base=None):
    """What a config's [analysis.<name>] table holds of a panel: the options set, and its own board and folder;
    paths (the analysis's, and those two) relative to `base` when given."""
    out = {}
    rel = lambda p: os.path.relpath(os.path.abspath(p), base).replace(os.sep, '/') if base else p
    for key, edit in (('board', panel.board), ('out', panel.outdir)):
        if edit.text().strip():
            out[key] = rel(edit.text().strip())
    vals = panel.values()
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
        groups = {}
        for o in self.options:
            groups.setdefault(o.get('group') or 'Settings', []).append(o)
        for i, (g, opts) in enumerate(groups.items()):
            inner = QWidget()
            fl = QFormLayout(inner)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setRowWrapPolicy(QFormLayout.WrapLongRows)
            for o in opts:
                if o['kind'] == 'bool':
                    wid = QCheckBox(o['help'])
                    wid.setChecked(bool(o['default']))
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
                fl.addRow(o['key'].replace('_', ' ').capitalize() if o['kind'] != 'bool' else '', wid)
            self.forms[g] = fl
            self.sections[g] = Section(g, inner, i == 0)            # the first group open: what a run is of
            v.addWidget(self.sections[g])
        self._after_sections = v.count()                            # where a page's own section goes (add_section)
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

    # ---- the settings ----
    def _edited(self, *_):
        if not self._setting:
            self.changed.emit()

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
        """Some of the form's fields (the others stay): a list as lines, None as empty."""
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
        """Start the analysis (its preview); the status line says why when it cannot start."""
        if self.proc is not None or (preview and not self.a.previewed):
            return
        vals = self.values()
        asked = tuple(getattr(self, 'asked', None) or ())           # the questions this run is asked (the study's)
        if asked:
            vals = self.a.for_questions(vals, asked)
        unset = sorted(k for k in self.required if not str(vals.get(k, '')).strip())
        if unset:
            self.status.setText(f"Set {', '.join(k.replace('_', ' ') for k in unset)} before Run: "
                                f"{'it was' if len(unset) == 1 else 'they were'} not known where these settings came from")
            return
        board = self.board_path() or None
        try:
            named = self.outdir.text().strip()
            out = (os.path.join(named, 'preview') if preview else named) if named else \
                self.default_out(board, self.a.tag(vals), preview)
            latest = self.win.latest_results() if self.win is not None and hasattr(self.win, 'latest_results') else {}
            argv = self.a.command(vals, board, os.path.abspath(out), preview=preview, results=latest)
        except ValueError as e:
            self.status.setText(str(e))
            return
        self.out, self._preview = os.path.abspath(out), preview
        from kicad2ems.api.frontend import mark_run
        from kicad2ems.study import provided
        mark_run(self.out, self.a.name, asked or provided(self.a), preview)     # whose run this folder is
        self.log.clear()
        self.say('$ ' + ' '.join(['python', *argv[1:]] if os.path.basename(argv[0]).startswith('python') else argv))
        self._running(True)
        self.status.setText('running…')
        run_tool(self, argv, self._stdout, self._finished, env=dict(self.a.env or {}))

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
            self.status.setText(f"the run failed (exit {code})" + (f": {last[:200]}" if last else '')
                                + ' (the whole log: the Run page)')
            self.status.setToolTip('\n'.join((errs or lines)[-8:]))
            return
        self.status.setToolTip('')
        rep = self.a.report(self.out) or {}
        self.status.setText('preview ready' if self._preview else ('done: ' + rep['summary'] if rep.get('summary') else 'done'))
        self.show_result(self.out)

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
