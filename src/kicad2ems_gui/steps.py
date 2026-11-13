"""
The steps of a study, as a bar: Board, Questions, Set up, Run, Results, each saying where it stands.

    steps_of(win)       the five steps of a window's study as plain data: [dict(key, title, text, state)], state
                        'done', 'now' (the first that is not done: where to go next) or 'todo'
    StepsBar(win)       the bar that shows them; a click on a step goes to where it is done

The bar is guidance, not the place for actions: the toolbar stays. It is a toolbar of its own, under the main
one in a new window, and it can be dragged to the bottom of the window (or back) by its handle and hidden (View >
Steps, or the toolbars' own menu); where it is and whether it shows is kept with the window's layout.
"""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QToolBar, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame

KEYS = ('board', 'questions', 'setup', 'run', 'results')
ACCENT, DONE, TODO = '#2f7fd6', '#2e9d5b', '#8a8f98'


def _cut(text, n=46):
    text = ' '.join(str(text).split())
    return text if len(text) <= n else text[:n - 1].rstrip() + '…'


def steps_of(win):
    """Where a window's study stands, step by step (no Qt in what it returns)."""
    values = win.setup.values()
    board = str(values.get('board') or '').strip()
    drawn = getattr(win, 'drawn', None)
    if board:
        text = os.path.splitext(os.path.basename(board))[0]
        if drawn and drawn.get('layout_of') and os.path.abspath(board) == drawn['layout_of']:
            nets = {it.get('net') for items in drawn.get('copper', {}).values() for it in items if it.get('net')}
            text += f" · {len(drawn['stack']['copper'])} layers · {len(nets)} nets"
    else:
        text = 'choose a board, or an example'
    asked = list(win.study.asked())
    labels = [win.study.labels[q] for q in asked]
    needs = list(getattr(win, '_needs_all', []) or [])
    runs = win.study.jobs(False)
    states = [win.study.state(r) for r in runs]
    busy = win.busy()
    ran = bool(runs) and all(s.startswith('done') for s in states)
    failed = [s for s in states if s.startswith(('failed', 'not started', 'stopped'))]
    est = (win.est_btn.text().splitlines() or [''])[0] if hasattr(win, 'est_btn') else ''
    info = win.results.info.text() if getattr(win.results, 'out', None) or win.results.analysis else ''
    out = [
        dict(key='board', title='Board', text=text, done=bool(board)),
        dict(key='questions', title='Questions', done=bool(asked),
             text=f"{len(asked)} asked: {', '.join(l.lower() for l in labels)}" if asked else 'tick what to find out'),
        dict(key='setup', title='Set up', done=bool(asked) and bool(board) and not needs,
             text=(f"{len(needs)} still needed: {needs[0]['text']}" if needs else 'nothing still needed') if asked
             else 'the settings of what is asked'),
        dict(key='run', title='Run', done=ran and not busy,
             text='running' + (f": {win.runtab.stage.text()}" if win.runtab.stage.text() not in ('', 'idle') else '') if busy
             else failed[0] if failed else (states[-1] if ran else (est if est and not est.lower().startswith('no estimate')
                                                                    else 'not run yet'))),
        dict(key='results', title='Results', done=bool(info), text=info or 'none yet'),
    ]
    now = next((s['key'] for s in out if not s['done']), None)
    for s in out:
        s['state'] = 'done' if s.pop('done') else ('now' if s['key'] == now else 'todo')
        s['text'] = _cut(s['text'])
    return out


class _Step(QFrame):
    clicked = Signal(str)

    def __init__(self, key, number):
        super().__init__()
        self.key, self.number = key, number
        self.setObjectName('step')
        self.setCursor(Qt.PointingHandCursor)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 2, 12, 2)
        v.setSpacing(0)
        self.head, self.text = QLabel(), QLabel()
        self.text.setStyleSheet('color: gray; font-size: 11px;')
        v.addWidget(self.head)
        v.addWidget(self.text)

    def show_step(self, step):
        state = step['state']
        mark, colour = ('✓', DONE) if state == 'done' else (str(self.number), ACCENT if state == 'now' else TODO)
        self.head.setText(f"<span style='color:{colour}; font-weight:600'>{mark}</span>&nbsp;&nbsp;<b>{step['title']}</b>")
        self.text.setText(step['text'])
        self.setToolTip(step['text'])
        self.setStyleSheet("QFrame#step { border-bottom: 2px solid %s; background: %s; border-radius: 3px; }"
                           % ((ACCENT, 'rgba(47, 127, 214, 28)') if state == 'now' else ('transparent', 'transparent')))

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.position().toPoint()):
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(ev)


class StepsBar(QToolBar):
    """The five steps, in a row; go(key): a step was clicked."""
    go = Signal(str)

    def __init__(self, win=None):
        super().__init__('Steps')
        self.win = win
        self.setObjectName('Steps')
        self.setMovable(True)
        self.setFloatable(False)
        self.setAllowedAreas(Qt.TopToolBarArea | Qt.BottomToolBarArea)
        self.toggleViewAction().setText('Steps')
        self.toggleViewAction().setToolTip('The steps of the study, as a bar (drag its handle to move it under the '
                                           'toolbar or to the bottom of the window)')
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(4, 1, 4, 1)
        lay.setSpacing(0)
        self.steps, self.shown = {}, []
        for i, key in enumerate(KEYS):
            st = _Step(key, i + 1)
            st.clicked.connect(self.go)
            lay.addWidget(st)
            self.steps[key] = st
            if i < len(KEYS) - 1:
                arrow = QLabel('›')
                arrow.setStyleSheet('color: #b0b5bd; font-size: 20px; padding: 0 4px;')
                lay.addWidget(arrow)
        lay.addStretch(1)
        self.addWidget(box)

    def set_steps(self, steps):
        self.shown = list(steps)
        for s in steps:
            self.steps[s['key']].show_step(s)

    def refresh(self):
        if self.win is not None and not self.isHidden():
            self.set_steps(steps_of(self.win))

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.win is not None:
            self.set_steps(steps_of(self.win))
