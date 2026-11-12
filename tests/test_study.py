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
    w.setup.dirty = False
    w.system.stop()
    w.meters.stop()
    QSettings('kicad2ems', 'gui').clear()


def test_study_dock(window):
    """The board above the list, each analysis's settings a panel made from its plugin's options and shown when it
    is selected, no Run button of its own, the ticks kept for the next window."""
    from PySide6.QtCore import Qt
    from kicad2ems_gui.analysispanel import AnalysisPanel
    w, app, MainWindow = window
    st = w.setup
    assert w.settings_dock.windowTitle() == 'Study'
    assert [st.study.topLevelItem(i).text(0) for i in range(st.study.topLevelItemCount())] == \
        ['S-parameters', 'Power integrity', 'Near field', 'Circuit', 'Thermal']
    assert st.study.ticked() == ['rf'] and st.study.current() == 'rf'       # as Run always did
    assert set(st.panels) == {'rf', 'pdn', 'thermal', 'mqs', 'circuit'} and list(w.pages) == ['pdn', 'mqs', 'circuit', 'thermal']
    assert not st.rf_box.isHidden() and st.panels['pdn'].isHidden()
    assert st.sections['Board'].parentWidget() is not st.rf_box              # the board: for every analysis
    assert st.sections['Frequency'].parentWidget() is st.rf_box
    w.study.select('pdn')
    assert st.rf_box.isHidden() and not st.panels['pdn'].isHidden()
    assert st.panel_title.text() == 'Power integrity settings'
    pdn, mqs = w.pages['pdn'], w.pages['mqs']
    assert st.panels['pdn'] is pdn and isinstance(pdn, AnalysisPanel) and pdn.isAncestorOf(pdn.w['rail'])
    assert pdn.run_btn.isHidden() and mqs.run_btn.isHidden() and w.pages['circuit'].run_btn.isHidden()
    assert not mqs.find_btn.isHidden()                               # it fills the form: it stays
    assert st.panels['circuit'].isAncestorOf(w.pages['circuit'].frequencies)
    assert pdn.board.placeholderText() == "the study's board"
    assert w.study.rows['thermal'].text(1) == 'fake.thermal' and 'thermal' not in w.study.why
    assert list(w.docks) == ['Viewer', 'Run', 'Results', 'Filter', 'Circuit']    # no page per analysis: the
    w.study.rows['pdn'].setCheckState(0, Qt.Checked)                             # circuit's editor alone
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
    w.study.set_ticked(['rf', 'circuit'])                           # its editor comes with its tick
    w.show_panel('Circuit')
    app.processEvents()
    assert w.study.current() == 'circuit' and not w.setup.panels['circuit'].isHidden()
    w.show_panel('Viewer')                                          # a shared page: the settings stay
    app.processEvents()
    assert w.study.current() == 'circuit'
    w.show_analysis('pdn')                                          # one without a page of its own: its settings,
    app.processEvents()                                             # and where its results are
    assert w.study.current() == 'pdn' and not w.docks['Results'].visibleRegion().isEmpty()
    w.show_analysis('circuit')
    app.processEvents()
    assert w.study.current() == 'circuit' and not w.docks['Circuit'].visibleRegion().isEmpty()
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


def run_to_the_end(w, app, seconds=120):
    import time
    t0 = time.time()
    while w.busy() and time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.02)
    for _ in range(10):
        app.processEvents()
    assert not w.busy()


def test_an_analysis_runs_from_the_window(window, tmp_path):
    """The toolbar's Run starts a ticked analysis's own command (the stand-in's child process): a missing setting
    is why it did not start; its log is on the Run page; a failure is its state. Done, its result is the one
    shown: listed under Results of, its report on the Results page, its map in the Viewer where its report says."""
    w, app, _ = window
    w.show()
    pdn, th = w.pages['pdn'], w.pages['thermal']
    w.study.set_ticked(['pdn'])
    w.run()                                                         # no board, no rail
    assert w.job is None and w.study.state('pdn').startswith('not started: choose a board')
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    w.setup.set_values(dict(board=str(board), out=str(tmp_path / 'out')))      # the study's board: the panel's too
    pdn.set_values(dict(rail='FAIL'))
    w.run()
    assert w.job == 'pdn' and w.study.state('pdn') == 'running' and w.busy()
    assert w.runtab.stage.text() == 'Power integrity: running' and w.runtab.plot.isHidden()
    assert w.runtab.log_of.currentData() == 'pdn'
    run_to_the_end(w, app)
    assert pdn.proc is None and w.job is None and w.study.state('pdn') == 'failed (exit 3)'
    assert 'failed' in pdn.status.text() and 'the rail has no copper' in pdn.status.text()
    assert 'pdn: reading the board' in w.runtab.logs.currentWidget().toPlainText()      # its log, on the Run page
    pdn.set_values(dict(rail='+3V3'))
    th.set_values(dict(loss='Q1=0.5\nL1=0.2'))
    w.study.set_ticked(['pdn', 'thermal'])
    w.run()
    run_to_the_end(w, app)
    assert w.study.state('pdn').startswith('done ') and w.study.state('thermal').startswith('done ')
    labels = [w.runs_box.itemText(i) for i in range(w.runs_box.count()) if w.runs_box.itemText(i)]
    assert sorted(l.split(',')[0] for l in labels) == ['Power integrity: 3V3', 'Thermal: losses']
    assert w.runs_box.currentData() == th.out and os.path.basename(th.out).startswith('b_thermal_losses_')
    r = w.results
    assert r.kind() == 'thermal' and r.mode == 'Report' and not w.docks['Results'].visibleRegion().isEmpty()
    assert r.info.text() == 'Thermal: hottest copper 75.0 °C' and th.status.text() == 'done: ' + r.info.text()
    cuts = w.viewer.cuts                                            # its map: a temperature, shown as one
    assert [s.label for s in cuts.srcs] == ['thermal board: T F.Cu (static)'] and cuts.src.unit == '°C'
    assert not cuts.log.isChecked() and cuts.lim == pytest.approx((40.0, 75.0), abs=0.6)    # its own range: not from 0
    assert cuts.cbar.axis.labelText == 'T (°C)' and 'steady' in cuts.frame_lab.text()
    assert w.latest_results() == dict(pdn=pdn.out, thermal=th.out)
    w.close()


def test_one_analysis_starts_from_another_s_result(window, tmp_path):
    """What a plugin is given of the others' results (the temperature, a circuit's losses): the one shown, else
    the newest; and what a result proposes for another analysis (a converter's input rail), with what it could not
    say to be set before a run."""
    from kicad2ems_gui import runfolders
    import fake_analyses as FA
    w, app, _ = window
    pdn, mqs, th = w.pages['pdn'], w.pages['mqs'], w.pages['thermal']
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    w.setup.set_values(dict(board=str(board), out=str(tmp_path / 'out')))
    w.run_study(only='thermal')                                     # no losses, no circuit run
    assert w.job is None and 'run the Circuit analysis first' in w.study.state('thermal')
    t = __import__('datetime').datetime(2026, 11, 11, 1, 0, 0)
    old = FA.write('circuit', runfolders.tool_dir(str(tmp_path / 'out'), str(board), 'circuit', 'buck', now=t))
    new = FA.write('circuit', runfolders.tool_dir(str(tmp_path / 'out'), str(board), 'circuit', 'buck', now=t.replace(minute=5)))
    assert w.latest_results() == dict(circuit=new)
    w.run_study(only='thermal')
    run_to_the_end(w, app)
    assert os.path.basename(th.out).startswith('b_thermal_circuit_')
    assert f"losses of {os.path.basename(new)}" in w.results.reportview.page.toPlainText()
    w.refresh_runs()
    w._pick_run(old)                                                # the one shown: that one
    assert w.latest_results()['circuit'] == old
    # a near field's rail for the power integrity: its voltage unknown, so asked for
    mqs.set_values(dict(converter='U7', vin='VBUS'))
    mqs.set_own(str(board), None)                                   # a board of its own: the rail's too
    w.run_study(only='mqs')
    run_to_the_end(w, app)
    (b,) = mqs.suggest_btns
    assert b.text() == 'Copy the input rail to Power integrity'
    pdn.set_values(dict(load='U1=2', scale=3))
    b.click()
    assert pdn.values()['rail'] == 'VBUS' and pdn.values()['load'] == '' and pdn.values()['scale'] == ''
    assert pdn.board.text() == str(board) and pdn.required == {'volts'} and w.study.current() == 'pdn'
    assert pdn.status.text() == 'The input rail is copied.' and w.setup.dirty
    w.run_study(only='pdn')
    assert w.job is None and w.study.state('pdn').startswith('not started: Set volts before Run')
    pdn.set_values(dict(volts=12))
    w.run_study(only='pdn')
    run_to_the_end(w, app)
    assert w.study.state('pdn').startswith('done ')
    w.run_study(only='mqs', preview=True)                           # a preview: its mesh, in the plan
    run_to_the_end(w, app)
    assert w.viewer.view() == 'Plan' and mqs.status.text() == 'preview ready'
    assert len(mqs.suggest_btns) == 1                               # a preview knows the rail too
    w.setup.dirty = False
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
