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
    """The board above the list; the list: the questions by group, who answers each, its state; the settings of
    the selected question's engines under it (a panel made from each plugin's options), no Run button of its
    own; what is asked kept for the next window."""
    from PySide6.QtCore import Qt
    from kicad2ems_gui.analysispanel import AnalysisPanel
    w, app, MainWindow = window
    st, tree = w.setup, w.study
    assert st.study is tree and st.isAncestorOf(tree)               # the list: the window's left column
    groups = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    assert [g.text(0) for g in groups] == ['RF', 'Signal integrity', 'Power', 'Thermal']
    assert [[g.child(k).text(0) for k in range(g.childCount())] for g in groups] == [
        ['S-parameters', 'Antenna pattern', 'Trace impedances'], ['Crosstalk'],
        ['Rail drop', 'Rail impedance', 'Converter near field', 'Circuit', 'Coils and ferrite', 'Capacitance'],
        ['Temperature']]
    assert tree.headerItem().text(1) == 'Answered by' and tree.headerItem().text(2) == 'Fields'
    by = lambda q: tree.rows[q].text(1).replace('  ▾', '')
    assert [by(q) for q in ('dc', 'pdn', 'nearfield', 'circuit', 'thermal')] == ['fake'] * 5
    assert tree.rows['thermal'].text(1).endswith('▾') and not tree.rows['dc'].text(1).endswith('▾')    # two engines
    assert tree.rows['capacitance'].text(3) == 'not installed' and 'kicad2ems[fem]' in tree.rows['capacitance'].toolTip(3)
    assert not tree.rows['capacitance'].flags() & Qt.ItemIsUserCheckable
    assert tree.asked() == dict(sparams=[]) and tree.ticked() == ['rf'] and tree.current() == 'rf'     # as Run always did
    assert tree.current_question() == 'sparams' and '1 asked' in st.study_section.head.text()
    assert set(st.panels) == {'rf', 'pdn', 'thermal', 'elmer_thermal', 'mqs', 'circuit'}
    assert list(w.pages) == ['pdn', 'mqs', 'circuit', 'thermal', 'elmer_thermal']
    assert not st.rf_box.isHidden() and st.panels['pdn'].isHidden() and st.panel_title.text() == 'S-parameters settings'
    assert st.sections['Board'].parentWidget() is not st.rf_box              # the board: for every question
    assert st.rf_box.isAncestorOf(st.more) and st.more.isAncestorOf(st.sections['Frequency'])   # under More settings
    assert w.setup.inspector.isAncestorOf(st.rf_box) and w.settings_dock.widget() is w.setup.inspector   # its own dock
    tree.select('dc')
    assert st.rf_box.isHidden() and not st.panels['pdn'].isHidden() and tree.current() == 'pdn'
    assert st.panel_title.text() == 'Rail drop settings' and st.engine_titles['pdn'].isHidden()        # one engine
    pdn, mqs = w.pages['pdn'], w.pages['mqs']
    assert st.panels['pdn'] is pdn and isinstance(pdn, AnalysisPanel) and pdn.isAncestorOf(pdn.w['rail'])
    assert pdn.run_btn.isHidden() and mqs.run_btn.isHidden() and w.pages['circuit'].run_btn.isHidden()
    assert not mqs.find_btn.isHidden()                               # it fills the form: it stays
    assert st.panels['circuit'] is w.pages['circuit'].panel and st.panels['circuit'].isAncestorOf(w.pages['circuit'].params)
    assert pdn.board.placeholderText() == "the study's board"
    assert list(w.places) == ['Viewer', 'Start', 'Results', 'Report', 'Tables', 'Run', 'Section', 'Filter', 'Circuit']   # no page per analysis: the
    tree.rows['dc'].setCheckState(0, Qt.Checked)                                 # circuit's editor alone
    assert tree.asked() == dict(sparams=[], dc=[]) and tree.ticked() == ['rf', 'pdn'] and '2 asked' in st.study_section.head.text()
    assert tree.asked_of('pdn') == ('dc',) and tree.asked_of('rf') == ('sparams',)
    tree.rows['pdn'].setCheckState(0, Qt.Checked)                    # the rail's impedance too: the same run
    assert tree.ticked() == ['rf', 'pdn'] and tree.asked_of('pdn') == ('dc', 'pdn')
    w.close()
    w2 = MainWindow()                                               # the next window: the same questions
    assert list(w2.study.asked()) == ['sparams', 'dc', 'pdn'] and w2.study.ticked() == ['rf', 'pdn']
    w2.system.stop()
    w2.meters.stop()


def test_who_answers_is_chosen_on_the_row(window):
    """Answered by: a menu of the question's engines, 'auto' first; several ticked run and are compared. The
    settings shown are those of the engines chosen, each under its name; an engine that cannot run here is not
    offered, and a question nobody can answer is greyed."""
    from PySide6.QtCore import Qt
    w, app, _ = window
    st, tree = w.setup, w.study
    w.show()
    app.processEvents()
    assert [e.name for e in tree.engines['thermal']] == ['thermal', 'elmer_thermal'] and tree.engines_for('thermal') == ['thermal']
    texts = lambda q: [(a.text(), a.isChecked(), a.isEnabled()) for a in tree.engine_menu(q).actions() if not a.isSeparator()]
    assert texts('thermal') == [('auto (fake)', True, True), ('fake  (fake.thermal)', False, True), ('Elmer  (fake.elmer)', False, True)]
    tree.select('thermal')
    assert not st.panels['thermal'].isHidden() and st.panels['elmer_thermal'].isHidden()
    tree.rows['thermal'].setCheckState(0, Qt.Checked)
    tree.choose('thermal', 'elmer_thermal', True)                   # with the default: both, compared
    assert tree.choice['thermal'] == ['thermal', 'elmer_thermal'] and tree.rows['thermal'].text(1) == 'fake + Elmer  ▾'
    assert tree.ticked() == ['rf', 'thermal', 'elmer_thermal'] and tree.asked()['thermal'] == ['thermal', 'elmer_thermal']
    assert not st.panels['thermal'].isHidden() and not st.panels['elmer_thermal'].isHidden()
    assert not st.engine_titles['thermal'].isHidden() and st.engine_titles['elmer_thermal'].text() == 'Elmer  ·  fake.elmer'
    assert texts('thermal')[0][1] is False and [t[1] for t in texts('thermal')[1:]] == [True, True]
    tree.choose('thermal', 'thermal', False)                        # Elmer alone
    assert tree.ticked() == ['rf', 'elmer_thermal'] and tree.current() == 'elmer_thermal' and st.panels['thermal'].isHidden()
    tree.set_state('elmer_thermal', 'running')
    tree.set_state('thermal', 'done 10:00')                         # not this question's engine now: not shown
    assert tree.rows['thermal'].text(3) == 'running' and tree.rows['thermal'].font(3).bold()
    tree.choose('thermal', 'thermal', True)
    tree.set_state('elmer_thermal', 'failed (exit 2)', 'bad')
    assert tree.rows['thermal'].text(3) == 'fake done 10:00 · Elmer failed'
    assert tree.rows['thermal'].toolTip(3) == 'fake: done 10:00\nElmer: failed (exit 2)'
    tree.choose('thermal', 'auto', True)                            # back to its default
    assert tree.choice['thermal'] == [] and tree.ticked() == ['rf', 'thermal'] and tree.rows['thermal'].text(1) == 'fake  ▾'
    # an engine that cannot run here: the other answers; neither: the question is greyed, unticked
    tree.set_available('thermal', False, 'no ngspice')
    assert tree.engines_for('thermal') == ['elmer_thermal'] and tree.ticked() == ['rf', 'elmer_thermal']
    assert texts('thermal')[0][0] == 'auto (Elmer)' and texts('thermal')[1][2] is False
    tree.set_available('elmer_thermal', False, 'no Elmer')
    it = tree.rows['thermal']
    assert it.checkState(0) == Qt.Unchecked and it.text(3) == 'not available' and tree.ticked() == ['rf']
    assert it.toolTip(3) == 'fake: no ngspice; Elmer: no Elmer' and not it.flags() & Qt.ItemIsUserCheckable
    assert not st.panels['thermal'].isHidden() and not st.panels['elmer_thermal'].isHidden()     # still to read
    tree.set_available('thermal', True)
    assert it.flags() & Qt.ItemIsUserCheckable and it.text(3) == ''
    w.close()


def test_the_solvers_are_ticked_on_the_rf_rows(window):
    """The solvers' tick boxes are off the form: the S-parameters row's menu sets them ('auto' among them), the
    Antenna row is the run's antenna mode, the Trace impedances row the line model; the three are one run."""
    from PySide6.QtCore import Qt
    w, app, _ = window
    st, tree = w.setup, w.study
    assert all(b.isHidden() and b.parentWidget() is st for b in st.solver_boxes.values())
    assert st.edits['mode'][0].isHidden() and 'Solvers' in st.sections      # the section keeps the driven ports
    names = [a.text() for a in tree.engine_menu('sparams').actions()]
    assert names[0].startswith('auto') and names[1:4] == ['openEMS (FDTD)', 'mom25d (MoM)', 'gfdtd (GPU FDTD)']
    assert tree.rows['sparams'].text(1) == 'auto  ▾' and st.values().get('solvers') is None
    tree.choose('sparams', 'auto', False)
    tree.choose('sparams', 'mom25d', True)
    tree.choose('sparams', 'qucs', True)
    assert tree.rows['sparams'].text(1) == 'mom25d + line model  ▾' and tree.rows['lines'].text(1) == 'line model  ▾'
    assert st.values()['solvers'] == ['mom25d', 'qucs'] and st.dirty             # a setting of the form, as any
    assert st.sections['mom25d'].isEnabled() and not st.parents['FDTD'][0].isEnabled()      # a solver's section: its tick
    w.setup.set_values(dict(solvers=['openems']))                   # a config's solvers: the rows show them
    assert tree.rows['sparams'].text(1) == 'openEMS  ▾' and tree.rows['antenna'].text(1) == 'openEMS  ▾'
    # the antenna: a row of its own, the run's mode
    assert st.values().get('mode') in (None, '', 'sparams')
    tree.rows['antenna'].setCheckState(0, Qt.Checked)
    assert st.values()['mode'] == 'antenna' and tree.ticked() == ['rf'] and tree.asked_of('rf') == ('sparams', 'antenna')
    assert [a.text() for a in tree.engine_menu('antenna').actions()][0].startswith('auto')
    assert not any(a.text().startswith('line model') for a in tree.engine_menu('antenna').actions())
    assert any(a.text().startswith('line model') for a in tree.engine_menu('sparams').actions())
    tree.rows['antenna'].setCheckState(0, Qt.Unchecked)
    assert st.values().get('mode') in (None, '', 'sparams')
    w.setup.set_values(dict(solvers=['openems'], mode='antenna'))   # a config in antenna mode: the row ticked
    assert 'antenna' in tree.asked()
    tree.rows['sparams'].setCheckState(0, Qt.Unchecked)
    tree.rows['antenna'].setCheckState(0, Qt.Unchecked)
    assert tree.ticked() == [] and tree.asked() == {}
    tree.rows['lines'].setCheckState(0, Qt.Checked)                 # the line model alone: still kicad2ems's run
    assert tree.ticked() == ['rf'] and tree.asked_of('rf') == ('lines',)
    w.setup.dirty = False
    w.close()


def test_the_fields_tick(window):
    """Fields: a tick on the rows whose engines can write field dumps. Ticked with none set, a default goes into
    the settings (an FDTD solver's dump, mom25d's current maps, an analysis's switch); unticked, the settings
    stay and the run leaves the dumps out."""
    from PySide6.QtCore import Qt
    w, app, _ = window
    st, tree = w.setup, w.study
    box = lambda q: None if tree.rows[q].data(2, Qt.CheckStateRole) is None else tree.rows[q].checkState(2)
    assert box('sparams') == Qt.Unchecked and box('lines') is None and box('thermal') is None and box('dc') is None
    assert box('circuit') == Qt.Unchecked                           # its plugin has a fields switch
    w.setup.set_values(dict(solvers=['openems', 'mom25d'], fmin=2.0, fmax=6.0))
    assert st.edits['dump'][0].text() == '' and tree.fields_on('rf') is False
    tree.rows['sparams'].setCheckState(2, Qt.Checked)
    assert st.edits['dump'][0].text() == 'E@F.Cu@4' and st.edits['mom_dump'][0].text() == '4.0' and tree.fields_on('rf')
    st.edits['dump'][0].setText('H@In1.Cu@3')                       # changed in the settings: kept
    tree.rows['sparams'].setCheckState(2, Qt.Unchecked)
    tree.rows['sparams'].setCheckState(2, Qt.Checked)
    assert st.edits['dump'][0].text() == 'H@In1.Cu@3' and tree.study().fields == dict(sparams=True)
    w.setup.set_values(dict(solvers=['qucs']))                      # the line model alone: nothing to dump
    assert box('sparams') is None and not tree.fields_on('rf')
    tree.rows['circuit'].setCheckState(0, Qt.Checked)
    tree.rows['circuit'].setCheckState(2, Qt.Checked)
    page = w.pages['circuit']                                       # its editor's own switch: the same tick
    assert page.fields.isChecked() and tree.fields_on('circuit') and tree.study().fields['circuit'] is True
    tree.rows['circuit'].setCheckState(2, Qt.Unchecked)
    assert not page.fields.isChecked() and tree.study().fields['circuit'] is False
    page.fields.setChecked(True)                                    # ticked in its settings: the row follows
    assert box('circuit') == Qt.Checked and tree.fields['circuit'] is True
    w.setup.dirty = False
    w.close()


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
    assert w.study.current() == 'pdn' and not w.places['Results'].isHidden()
    w.show_analysis('circuit')
    app.processEvents()
    assert w.study.current() == 'circuit' and w.places['Circuit'].in_front()
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
    w.run_study()
    assert started == [('rf', False)] and w.job == 'rf' and w.queue == ['mqs', 'circuit']
    assert w.study.state('rf') == 'running' and w.study.state('circuit') == 'queued'
    assert not w.runtab.jobs.isHidden() and w.runtab.jobs.topLevelItemCount() == 3
    assert w.acts['Stop'].isEnabled()
    w.run_study()                                                         # a run is going
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
    w.run_study()
    assert started == [('rf', False), ('pdn', False)] and w.job == 'pdn'
    assert w.study.state('rf') == 'not started: Choose a board first'
    assert w.study.rows['sparams'].text(3) == 'not started'          # the column: short, the tooltip whole
    # Stop: the queued ones are not run
    w._job_done('pdn', 0)
    pump()
    why.clear()
    started.clear()
    stopped = []
    monkeypatch.setattr(w.pages['pdn'], 'stop', lambda: stopped.append('pdn'))
    w.study.set_ticked(['pdn', 'circuit'])
    w.run_study()
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
    w.run_study()
    assert 'Tick a question' in said[-1] and w.job is None
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
    w.run()                                                         # no board, no rail: Run says so, and starts nothing
    assert w.job is None and w.study.state('pdn') == '' and w.acts['Run'].text() == 'Choose a board first'
    w.run_study()                                                   # started all the same (one question alone is):
    assert w.job is None and w.study.state('pdn').startswith('not started: choose a board')      # its row says why
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
    assert r.kind() == 'thermal' and r.mode == 'Report' and w.places['Report'].in_front()      # what it found: in front
    assert r.info.text().startswith('Thermal: hottest copper 75.0 °C') and th.status.text() == 'done: Thermal: hottest copper 75.0 °C'
    cuts = w.viewer.cuts                                            # its map: a temperature, shown as one
    assert [s.label for s in cuts.srcs] == ['thermal board: T F.Cu (static)'] and cuts.src.unit == '°C'
    assert not cuts.log.isChecked() and cuts.lim == pytest.approx((40.0, 75.0), abs=0.6)    # its own range: not from 0
    assert cuts.cbar.axis.labelText == 'T (°C)' and 'steady' in cuts.frame_lab.text()
    assert w.latest_results() == dict(pdn=pdn.out, thermal=th.out)
    w.close()


def test_two_engines_of_one_question_run_and_are_compared(window, tmp_path):
    """The temperature asked of both its engines: each runs with its own settings into a folder that says whose it
    is; the Results page lays the figures they name alike side by side, with the difference; the config keeps who
    was asked."""
    from PySide6.QtCore import Qt
    from kicad2ems.api.frontend import analysis_of, read_study, run_mark
    w, app, _ = window
    w.show()
    tree = w.study
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    cfg = tmp_path / 'b.toml'
    cfg.write_text('board = "b.kicad_pcb"\n\n[study]\nrun = ["dc", "thermal"]\n[study.thermal]\nengine = ["fake", "Elmer"]\n\n'
                   '[analysis.pdn]\nrail = "+3V3"\n\n[analysis.thermal]\nloss = ["Q1=0.5", "L1=0.2"]\n\n'
                   '[analysis.elmer_thermal]\nloss = ["Q1=0.5", "L1=0.2"]\n')
    assert w.setup.load(str(cfg))
    assert tree.asked() == dict(dc=[], thermal=['thermal', 'elmer_thermal']) and tree.ticked() == ['pdn', 'thermal', 'elmer_thermal']
    assert tree.current_question() == 'dc' and tree.rows['thermal'].text(1) == 'fake + Elmer  ▾'
    pdn, th, el = (w.pages[k] for k in ('pdn', 'thermal', 'elmer_thermal'))
    w.run()
    run_to_the_end(w, app)
    assert all(tree.state(k).startswith('done ') for k in ('pdn', 'thermal', 'elmer_thermal'))
    assert tree.rows['thermal'].text(3).startswith('done ') and 'Elmer: done' in tree.rows['thermal'].toolTip(3)
    assert run_mark(pdn.out) == dict(engine='pdn', questions=('dc',), preview=False)      # the drop alone was asked

    assert analysis_of(th.out) == ('thermal', False) and analysis_of(el.out) == ('elmer_thermal', False)
    assert os.path.basename(el.out).startswith('b_elmer_thermal_losses_') and run_mark(el.out)['questions'] == ('thermal',)
    r = w.results                                                   # the last one's report, the other beside it
    assert r.kind() == 'elmer_thermal' and r.modes() == ['Report', 'Tables']
    titles = [t for t, _ in r.reportview._tables]
    assert titles[0] == 'Engines compared: Temperature' and titles[1:] == ['Parts', 'Layers']
    table = r.reportview._tables[0][1]
    assert table['columns'] == ['figure', 'unit', 'fake', 'Elmer', 'difference']
    assert table['rows'] == [['hottest', 'C', 75.0, 77.0, 2.0], ['Q1', 'C', 75.0, 77.0, 2.0], ['L1', 'C', 45.0, 47.0, 2.0]]
    text = r.reportview.page.toPlainText()
    assert 'Engines compared: Temperature' in text and os.path.basename(th.out) in text
    w._pick_run(pdn.out)                                            # a question one engine answered: nothing beside it
    assert [t for t, _ in r.reportview._tables] == ['Loads at DC']
    tree.choose('thermal', 'thermal', False)                        # Elmer alone, saved as such
    assert w.setup.dirty and w.setup.save()
    st = read_study(str(cfg))
    assert st.asked == dict(dc=[], thermal=['elmer_thermal']) and '[analysis]\nrun' not in cfg.read_text()
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
    assert {'dc', 'pdn'} <= set(w.study.asked())                    # proposed for it: asked, so Run includes it
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


def test_the_study_dock_closes_and_comes_back(window):
    """The study's dock closes from View (and by its key) and comes back the same way; closed when the window
    was, it is there again in the next one, the study being what a window opens on."""
    w, app, MainWindow = window
    w.show()
    app.processEvents()
    act = w.fold_acts['Questions']
    assert act.isEnabled() and act.isChecked() and not w.study_dock.isHidden()
    act.trigger()
    assert w.study_dock.isHidden() and not act.isChecked()
    act.trigger()                                                   # View > Questions: back
    assert not w.study_dock.isHidden() and w.setup.isAncestorOf(w.study)
    act.trigger()
    w.close()                                                       # saved with it closed
    again = MainWindow()
    try:
        again.show()
        app.processEvents()
        assert not again.study_dock.isHidden() and again.fold_acts['Questions'].isChecked()
    finally:
        again.system.stop()
        again.meters.stop()
        again.close()


def test_the_few_settings_first_and_the_rest_found(window):
    """The settings a run is set up with are in view (the registry says which: an option's level, a solver's
    `basic`), those of a solver while it is chosen; the others are under "More settings", in their sections, and
    found by a word of their label, their key or their section. The board's: its file and extra ports first."""
    from kicad2ems_gui.runner import basic_keys
    w, app, _ = window
    w.show()
    app.processEvents()
    st = w.setup
    first = [k for k, (frm, _) in st.rows.items() if frm is st.basic_form]
    assert first[:3] == ['fmin', 'fmax', 'points'] and set(first) | {'board', 'ports'} == basic_keys() & set(st.rows) | {'board', 'ports'}
    assert st.rows['board'][0] is not st.basic_form and st.rows['pos'][0] is st.board_more_form     # the board's own
    assert not st.more.expanded and st.more.head.text().startswith('More settings')
    assert st.find.placeholderText() == 'Find a setting'
    solver = next((k for k in first if st.group_of[k].split('/')[0] in ('FDTD', 'mom25d')), None)
    if solver:                                                      # a solver's, in view while it is chosen
        top = st.group_of[solver].split('/')[0]
        assert st.field_labels[solver].text().startswith(top + ': ')
        for name, box in st.solver_boxes.items():
            box.setChecked(False)
        st._update_sections()
        assert not st.basic_form.isRowVisible(st.rows[solver][1])
    st.set_values(dict(fmin=1, fmax=2, air=5))
    assert st.more.head.text() == 'More settings  (1 set)'          # those in view are not counted: they are seen
    hidden = lambda key: not st.rows[key][0].isRowVisible(st.rows[key][1])
    st.find.setText('sweep')
    assert not hidden('sweep') and st.sections['Frequency'].expanded and not st.sections['Frequency'].isHidden()
    assert st.sections['Output'].isHidden() and not hidden('fmin')  # (the first few stay)
    st.find.setText('output')                                       # a section's name: all of it
    assert not st.sections['Output'].isHidden() and not hidden('out') and st.sections['Frequency'].isHidden()
    st.find.setText('')
    assert not st.sections['Frequency'].isHidden() and not st.sections['Frequency'].expanded and not hidden('sweep')
    st.focus('sweep')
    assert st.more.expanded and st.sections['Frequency'].expanded
    st.focus('pos')
    assert st.sections['Board'].expanded and st.board_more.expanded
    w.setup.dirty = False


def test_still_needed_and_what_run_says(window, tmp_path):
    """What a run still needs is listed under the selected question's settings, each line leading to where it is
    set, and the Run button says the first of them instead of starting; with nothing missing it says what it will
    run. An analysis says what it needs itself (Analysis.missing: what its command raises, by default)."""
    w, app, _ = window
    w.show()
    app.processEvents()
    need, run = w.setup.needed, w.acts['Run']
    w.update_needed()
    assert run.text() == 'Choose the board' and [m['text'] for m in need.items] == ['choose the board']
    assert not need.isHidden() and need.title.text() == 'Still needed'
    w.run()                                                         # goes there, starts nothing
    assert not w.busy() and w.setup.sections['Board'].expanded and 'still needs: choose the board' in w.statusBar().currentMessage()
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    w.setup.set_values(dict(board=str(board), out=str(tmp_path / 'out')))
    w.update_needed()
    assert run.text() == 'Run' and need.items == [] and 'S-parameters' in run.toolTip()
    w.setup.set_values(dict(board=str(board), fmin=5, fmax=2))
    w.update_needed()
    assert run.text() == 'F max is not above f min' and need.items[0]['key'] == 'fmax'
    w.setup.set_values(dict(board=str(board), out=str(tmp_path / 'out')))
    w.study.set_ticked(['rf', 'pdn'])                               # an analysis that needs its rail named
    w.study.select('dc')
    w.update_needed()
    assert run.text() == 'Name the rail (its net)' and [m['run'] for m in need.items] == ['pdn']
    assert run.toolTip().startswith('Power integrity still needs: name the rail')
    w.study.select('sparams')                                       # the list: the selected question's
    assert need.items == [] and run.text() == 'Name the rail (its net)'
    w.pages['pdn'].set_values(dict(rail='+3V3'))
    w.update_needed()
    assert run.text() == 'Run 2' and run.toolTip().startswith('Run S-parameters, then Power integrity')
    w.study.set_ticked(['thermal'])                                 # the temperature alone: it has no losses
    w.study.select('thermal')
    w.update_needed()
    assert 'losses' in need.items[0]['text'] and run.text().startswith('Give the parts')
    w.study.set_ticked(['circuit', 'thermal'])                      # with the circuit asked, which runs first and
    w.update_needed()                                               # will give them: nothing to ask for
    assert [m for m in need.items if m['run'] == 'thermal'] == [] and w.needs(['circuit', 'thermal'])['thermal'] == []
    w.study.set_ticked([])
    w.update_needed()
    assert run.text() == 'Run' and 'Tick a question' in run.toolTip()
    w.setup.dirty = False


def test_the_window_s_own_run_starts_and_ends(window, tmp_path, monkeypatch):
    """Preview and Run start kicad2ems's own run (MainWindow.start: a Start page called `start` once hid it), its
    events reach the Log, and the window is idle after; a start that raises says so on its row and leaves the
    window idle too (it stayed busy, so every later Run said "a run is going")."""
    import sys
    from kicad2ems import runs
    w, app, _ = window
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    script = tmp_path / 'fake_run.py'
    script.write_text("import json, sys\nev = sys.argv[sys.argv.index('--events') + 1]\n"
                      "with open(ev, 'a') as f:\n"
                      "    f.write(json.dumps(dict(kind='log', text='fake run here')) + '\\n')\n"
                      "    f.write(json.dumps(dict(kind='done', code=0)) + '\\n')\n")
    monkeypatch.setattr(runs.Run, 'argv', lambda self: [sys.executable, str(script), self.toml, '--events', self.events])
    w.setup.set_values(dict(board=str(board), out=str(tmp_path / 'out')))
    w.study.set_ticked(['rf'])
    w.preview()
    assert w.job == 'rf' and w.proc is not None
    run_to_the_end(w, app)
    assert not w.busy() and 'fake run here' in w.runtab.log.toPlainText()
    monkeypatch.setattr(type(w), 'start', lambda self, preview: 1 / 0)
    w.preview()
    assert not w.busy() and 'ZeroDivisionError' in w.study.state('rf')
    assert 'ZeroDivisionError' in w.runtab.log.toPlainText()        # its traceback in the log
