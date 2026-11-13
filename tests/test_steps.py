"""The steps bar (steps.py): where a study stands, step by step, and where a click on a step goes."""
import os

import pytest

pytest.importorskip('PySide6')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from k2e_fixtures import ROOT                                          # noqa: E402
from kicad2ems_gui import steps as ST                                  # noqa: E402


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    from PySide6.QtCore import QSettings
    from kicad2ems_gui import application, startpage
    from kicad2ems_gui.app import MainWindow
    monkeypatch.setattr(startpage.StartPage, 'start_pictures', lambda self: None)
    app = application()
    QSettings('kicad2ems', 'gui').clear()
    w = MainWindow()
    w.system.stop()
    w.meters.stop()
    w.show()
    app.processEvents()
    yield w, app
    w.setup.dirty = False
    w.close()
    QSettings('kicad2ems', 'gui').clear()


def test_the_steps_say_where_the_study_stands(window, tmp_path):
    from PySide6.QtCore import Qt
    w, app = window
    w.study.set_ticked([])
    w.update_needed()
    s = {x['key']: x for x in ST.steps_of(w)}
    assert list(s) == list(ST.KEYS) and [x['title'] for x in s.values()] == ['Board', 'Questions', 'Set up', 'Run', 'Results']
    assert s['board']['state'] == 'now' and 'choose a board' in s['board']['text']            # nothing yet: begin here
    assert all(s[k]['state'] == 'todo' for k in ST.KEYS[1:]) and s['results']['text'] == 'none yet'
    w.setup.set_values(dict(board=os.path.join(ROOT, 'examples', 'rf_bus.kicad_pcb'), out=str(tmp_path / 'out')))
    w.study.set_ticked(['rf'])
    w.update_needed()
    s = {x['key']: x for x in ST.steps_of(w)}
    assert s['board']['state'] == 'done' and s['board']['text'].startswith('rf_bus')
    assert s['questions']['state'] == 'done' and s['questions']['text'] == '1 asked: s-parameters'
    assert s['setup']['state'] == 'now' and 'still needed' in s['setup']['text']              # (the board has no ports)
    assert s['run']['state'] == 'todo'
    # the bar shows them, and is a toolbar of its own under the main one: it moves to the bottom, and hides
    bar = w.steps
    assert bar.shown and bar.steps['setup'].text.text() == s['setup']['text'] and '✓' in bar.steps['board'].head.text()
    assert w.toolBarArea(bar) == Qt.TopToolBarArea and bar.isMovable() and not bar.isFloatable()
    assert bar.geometry().top() >= w.findChild(type(bar).__mro__[1], 'Main toolbar').geometry().bottom() - 1
    assert bar.toggleViewAction().text() == 'Steps' and bar.toggleViewAction() in w.menuBar().actions()[1].menu().actions()
    w.addToolBar(Qt.BottomToolBarArea, bar)                             # along the bottom: kept with the layout
    app.processEvents()
    assert w.toolBarArea(bar) == Qt.BottomToolBarArea
    bar.toggleViewAction().trigger()                                    # and switched off
    assert bar.isHidden()
    state = w.saveState()
    bar.toggleViewAction().trigger()
    w.addToolBar(Qt.TopToolBarArea, bar)
    assert w.restoreState(state) and bar.isHidden() and w.toolBarArea(bar) == Qt.BottomToolBarArea
    bar.show()


def test_a_click_on_a_step_goes_where_it_is_done(window, tmp_path):
    w, app = window
    w.setup.set_values(dict(board=os.path.join(ROOT, 'examples', 'rf_bus.kicad_pcb'), out=str(tmp_path / 'out')))
    w.study.set_ticked(['rf'])
    w.update_needed()
    w.study_dock.hide()
    w.steps.go.emit('questions')
    assert not w.study_dock.isHidden()
    w.settings_dock.hide()
    w.steps.steps['setup'].clicked.emit('setup')                        # what is still needed: said, and shown
    assert not w.settings_dock.isHidden() and 'still needs' in w.statusBar().currentMessage()
    w.steps.go.emit('run')
    app.processEvents()
    assert w.docks['Run'].in_front()
    w.steps.go.emit('results')
    app.processEvents()
    assert w.docks['Results'].in_front()
