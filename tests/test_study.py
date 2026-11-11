"""The study: the analyses' order and what follows what (study.py), the Study dock (the board, the list, the
selected analysis's settings) and the window's Run of the ticked analyses, one after the other."""
import os
import pytest

from kicad2ems_gui import study


def test_order_and_needs():
    keys = [a.key for a in study.ANALYSES]
    assert keys[0] == 'rf' and keys.index('circuit') < keys.index('thermal')    # thermal: after the circuit run
    assert study.with_needs(['thermal']) == ['thermal']                     # its losses may be typed: no needs
    assert study.with_needs(['circuit', 'rf']) == ['rf', 'circuit']          # the list's order, not the caller's
    assert study.dependents('pdn') == [] and study.dependents('rf') == []
    assert study.run_order(['circuit', 'mqs', 'rf']) == ['rf', 'mqs', 'circuit']
    assert study.run_order(['thermal', 'circuit']) == ['circuit', 'thermal']
    assert not any(a.planned for a in study.ANALYSES)
    assert study.run_order(['rf', 'pdn', 'mqs'], preview=True) == ['rf', 'mqs']
    assert study.run_order(['rf', 'pdn'], available={'rf'}) == ['rf']       # pcbqs not installed
    assert study.run_order(['mqs'], preview=True, available={'rf'}) == []


def test_a_planned_analysis_runs_once_it_has_a_tool(monkeypatch):
    """An analysis that starts from another's results: planned, only what it needs runs; with a tool, after
    that, and not at all when that cannot run."""
    base = study.ANALYSES

    def with_later(planned):
        a = (*base, study.Analysis('later', 'Later', 'tool', needs=('pdn',), planned=planned))
        monkeypatch.setattr(study, 'ANALYSES', a)
        monkeypatch.setattr(study, 'BY_KEY', {x.key: x for x in a})
    with_later(True)
    assert study.run_order(['later']) == ['pdn'] and study.dependents('pdn') == ['later']
    with_later(False)
    assert study.run_order(['later']) == ['pdn', 'later']
    assert study.run_order(['later'], available={'later'}) == []


@pytest.fixture
def window(tmp_path, monkeypatch):
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    from PySide6.QtCore import QSettings
    from kicad2ems_gui import application
    from kicad2ems_gui.app import MainWindow
    app = application()
    QSettings('kicad2ems', 'gui').clear()
    w = MainWindow()
    for k in ('pdn', 'mqs', 'circuit'):                             # as on a machine with pcbqs, whatever is here
        w.study.set_available(k, True)
        w.study.set_state(k, '')
    yield w, app, MainWindow
    w.system.stop()
    w.meters.stop()
    QSettings('kicad2ems', 'gui').clear()


def test_study_dock(window):
    """The board above the list, each analysis's settings out of its page and shown when it is selected, the
    pages' own Run buttons gone, the ticks kept for the next window."""
    from PySide6.QtCore import Qt
    w, app, MainWindow = window
    if w.pdn.desc is None or w.mqs.desc is None:
        pytest.skip('pcbqs is not installed: its pages have no settings to move')
    st = w.setup
    assert w.settings_dock.windowTitle() == 'Study'
    assert [st.study.topLevelItem(i).text(0) for i in range(st.study.topLevelItemCount())] == \
        ['S-parameters', 'Power integrity', 'Near field', 'Circuit', 'Thermal']
    assert st.study.ticked() == ['rf'] and st.study.current() == 'rf'       # as Run always did
    assert set(st.panels) == {'rf', 'pdn', 'thermal', 'mqs', 'circuit'}
    assert not st.rf_box.isHidden() and st.panels['pdn'].isHidden()
    assert st.sections['Board'].parentWidget() is not st.rf_box              # the board: for every analysis
    assert st.sections['Frequency'].parentWidget() is st.rf_box
    w.study.select('pdn')
    assert st.rf_box.isHidden() and not st.panels['pdn'].isHidden()
    assert st.panel_title.text() == 'Power integrity settings'
    assert st.panels['pdn'].isAncestorOf(w.pdn.w['rail']) and not w.pdn.isAncestorOf(w.pdn.w['rail'])
    assert w.pdn.run_btn.isHidden() and w.mqs.preview_btn.isHidden() and w.circuit.run_btn.isHidden()
    assert not w.mqs.find_btn.isHidden()                                     # it fills the form: it stays
    assert st.panels['circuit'].isAncestorOf(w.circuit.frequencies)
    assert w.pdn.board.placeholderText() == "the study's board"
    # thermal: pcbqs's tool, its settings in the dock like the others
    if w.thermal.desc is not None:
        assert 'thermal' not in w.study.why and w.study.rows['thermal'].text(1) == 'pcbqs.thermal'
        assert st.panels['thermal'].isAncestorOf(w.thermal.w['loss']) and w.thermal.run_btn.isHidden()
    w.study.rows['pdn'].setCheckState(0, Qt.Checked)
    assert w.study.ticked() == ['rf', 'pdn'] and '2 of 5' in st.study_section.head.text()
    w.setup.set_values(dict(solvers=['mom25d']))
    assert w.study.rows['rf'].text(1) == 'mom25d'
    w.close()
    w2 = MainWindow()                                               # the next window: the same ticks
    assert w2.study.ticked() == [k for k in ('rf', 'pdn') if k not in w2.study.why]
    w2.system.stop()
    w2.meters.stop()


def test_an_analysis_page_in_front_selects_its_settings(window):
    w, app, _ = window
    w.show()
    app.processEvents()
    assert w.study.current() == 'rf'                                # the window opening selects nothing else
    w.show_panel('Near field')
    app.processEvents()
    assert w.study.current() == 'mqs' and not w.setup.panels['mqs'].isHidden()
    w.show_panel('Viewer')                                          # a shared page: the settings stay
    app.processEvents()
    assert w.study.current() == 'mqs'
    w.show_analysis('pdn')
    app.processEvents()
    assert w.study.current() == 'pdn' and not w.docks['PDN'].visibleRegion().isEmpty()
    w.close()


def test_run_starts_the_ticked_analyses_in_turn(window, monkeypatch):
    """Run: each ticked analysis after the one before ended; one that cannot start says why and the rest go on;
    Stop ends the one running and leaves the queued ones; a tool going on a page keeps a second Run away."""
    from PySide6.QtWidgets import QMessageBox
    w, app, _ = window
    started, said = [], []
    monkeypatch.setattr(QMessageBox, 'information', lambda *a: said.append(a[2]))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: said.append(a[2]))
    why = {}

    def start(key, preview):
        started.append((key, preview))
        return why.get(key)
    monkeypatch.setattr(w, '_start_job', start)
    pump = lambda: [app.processEvents() for _ in range(5)]
    w.study.set_ticked(['rf', 'mqs', 'circuit'])
    w.run()
    assert started == [('rf', False)] and w.job == 'rf' and w.queue == ['mqs', 'circuit']
    assert w.study.state('rf') == 'running' and w.study.state('circuit') == 'queued'
    assert not w.runtab.jobs.isHidden() and w.runtab.jobs.topLevelItemCount() == 3
    assert w.acts['Stop'].isEnabled()
    w.run()                                                         # a run is going
    assert said and 'stop it first' in said[-1] and len(started) == 1
    w._job_done('mqs', 0)                                           # not the one running: nothing
    assert w.job == 'rf'
    w._job_done('rf', 0)
    pump()
    assert started[-1] == ('mqs', False) and w.study.state('rf').startswith('done ')
    w._job_done('mqs', 3)                                           # failed: the next still runs
    pump()
    assert w.study.state('mqs') == 'failed (exit 3)' and started[-1] == ('circuit', False)
    w._job_done('circuit', 0)
    pump()
    assert w.job is None and not w.queue and not w.acts['Stop'].isEnabled()
    assert w.runtab.job_rows['circuit'].text(2) == '0:00'
    # one that cannot start: why, in the list; the others run
    started.clear()
    why['rf'] = 'Choose a board first'
    w.study.set_ticked(['rf', 'pdn'])
    w.run()
    assert started == [('rf', False), ('pdn', False)] and w.job == 'pdn'
    assert w.study.state('rf') == 'not started: Choose a board first'
    assert w.study.rows['rf'].text(2) == 'not started'               # the column: short, the tooltip whole
    # Stop: the queued ones are not run
    w._job_done('pdn', 0)
    pump()
    why.clear()
    started.clear()
    stopped = []
    monkeypatch.setattr(w.pages['pdn'], 'stop', lambda: stopped.append('pdn'))
    w.study.set_ticked(['pdn', 'circuit'])
    w.run()
    assert w.job == 'pdn'
    w.stop()
    assert stopped == ['pdn'] and w.queue == [] and w.study.state('circuit') == 'not run: stopped'
    w._job_done('pdn', 9)                                           # its process, killed
    pump()
    assert w.study.state('pdn') == 'stopped' and w.job is None and started == [('pdn', False)]
    # Preview: the analyses that have one; one alone: whatever is ticked
    started.clear()
    w.study.set_ticked(['rf', 'pdn', 'mqs'])
    w.preview()
    assert started == [('rf', True)] and w.queue == ['mqs']
    w._job_done('rf', 0)
    pump()
    w._job_done('mqs', 0)
    pump()
    started.clear()
    w.run_study(only='circuit')
    assert started == [('circuit', False)] and w.runtab.jobs.isHidden()     # one job: the page as it was
    w._job_done('circuit', 0)
    pump()
    w.study.set_ticked([])
    w.run()
    assert 'Tick an analysis' in said[-1] and w.job is None
    w.close()


def test_a_page_tool_runs_from_the_window(window, monkeypatch, tmp_path):
    """Power integrity from the toolbar's Run: the page's own start, its process followed to the next analysis,
    its log on the Run page; a missing setting is why it did not start."""
    from kicad2ems_gui import pdntab
    w, app, _ = window
    if w.pdn.desc is None:
        pytest.skip('pcbqs is not installed')
    w.study.set_ticked(['pdn'])
    w.run()                                                         # no board, no rail
    assert w.job is None and w.study.state('pdn').startswith('not started: choose a board')
    board = tmp_path / 'board.json'
    board.write_text('{}')
    w.setup.set_values(dict(board=str(board)))                      # the study's board: the page's too
    w.pdn.set_values(dict(rail='+3V3'))

    class Sig:
        def __init__(self):
            self.slots = []

        def connect(self, f):
            self.slots.append(f)

        def emit(self, *a):
            for f in list(self.slots):
                f(*a)

    class Proc:
        def __init__(self):
            self.finished, self.errorOccurred = Sig(), Sig()

    def run_tool(page, argv, on_output, on_finished, **kw):
        page.proc = Proc()
        page.proc.finished.connect(on_finished)
        page.say('pdn: meshing')
        return page.proc
    monkeypatch.setattr(pdntab, 'run_tool', run_tool)
    w.run()
    assert w.job == 'pdn' and w.study.state('pdn') == 'running' and w.busy()
    assert w.runtab.stage.text() == 'Power integrity: running' and w.runtab.plot.isHidden()
    assert w.runtab.log_of.currentData() == 'pdn'
    assert 'pdn: meshing' in w.runtab.logs.currentWidget().toPlainText()    # the page's log, on the Run page
    proc = w.pdn.proc
    proc.finished.emit(1, None)                                     # the tool failed: the page first, then the queue
    for _ in range(5):
        app.processEvents()
    assert w.pdn.proc is None and w.job is None and w.study.state('pdn') == 'failed (exit 1)'
    assert 'failed' in w.pdn.status.text()
    w.close()


def test_the_study_comes_back_after_a_layout_that_hid_it(window):
    """A layout saved with the Study dock closed opened with it hidden and its View action disabled: no way to
    choose a board. It is closable now (View toggles it) and shown when the window opens."""
    w, app, MainWindow = window
    d = w.settings_dock
    assert d.toggleViewAction().isEnabled()
    d.hide()
    w.close()                                                       # the layout is saved with the dock hidden
    again = MainWindow()
    try:
        assert not again.settings_dock.isHidden() and again.settings_dock.toggleViewAction().isEnabled()
        again.show()
        app.processEvents()
        again.settings_dock.toggleViewAction().trigger()            # View > Study closes it and opens it again
        assert again.settings_dock.isHidden()
        again.settings_dock.toggleViewAction().trigger()
        assert not again.settings_dock.isHidden()
    finally:
        again.system.stop()
        again.meters.stop()
        again.close()
