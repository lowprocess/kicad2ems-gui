"""Every analysis's results in the pages: the run folders of the analyses' tools (runfolders), their curves on the
Results page (curves.py, curveplot.py) with other runs over them, a result's three views (its plots, its report,
its tables), the pages that come and go, a second Viewer. The analyses are the stand-ins (fake_analyses.py)."""
import json
import os
import time

import numpy as np
import pytest

import fake_analyses as FA
from kicad2ems_gui import curves, runfolders

_pdn = lambda folder, scale=1.0, rail='P': FA.write('pdn', folder, rail=rail, scale=scale)
_mqs = lambda folder: FA.write('mqs', folder, converter='U3')


def test_tool_run_folders(tmp_path):
    base, board = str(tmp_path / 'out'), str(tmp_path / 'b.kicad_pcb')
    t0 = __import__('datetime').datetime(2026, 11, 11, 1, 31, 36)
    a = runfolders.tool_dir(base, board, 'pdn', '+3V3', now=t0)
    assert os.path.basename(a) == 'b_pdn_3V3_20261111_013136'
    assert runfolders.tool_preview_dir(base, board, 'mqs').endswith('b_mqs_preview')
    assert runfolders.tool_titles() == dict(pdn='Power integrity', mqs='Near field', circuit='Circuit', thermal='Thermal')
    _pdn(a)
    os.makedirs(runfolders.tool_dir(base, board, 'pdn', 'X', now=t0.replace(second=40)))     # stopped: no result
    _mqs(str(tmp_path / 'mqs_U3'))                                  # the old place: beside the board
    _pdn(str(tmp_path / 'out' / 'other_pdn_P_20261111_013136'))     # another board's
    FA.write('mqs', runfolders.tool_preview_dir(base, board, 'mqs'), preview=True)      # a preview: not a run
    th = FA.write('thermal', runfolders.tool_dir(base, board, 'thermal', 'circuit', now=t0.replace(second=50)))
    found = runfolders.tool_runs(base, board)
    assert [(os.path.basename(d), k) for d, k, _ in found] == [
        ('mqs_U3', 'mqs'), ('b_thermal_circuit_20261111_013150', 'thermal'), ('b_pdn_3V3_20261111_013136', 'pdn')]
    assert found[2][2] == 'Power integrity: 3V3, 2026-11-11 01:31:36' and found[1][2].startswith('Thermal: circuit, ')
    assert runfolders.tool_kind(a) == 'pdn' and runfolders.tool_kind(str(tmp_path)) is None and runfolders.tool_kind(th) == 'thermal'
    assert runfolders.tool_kind(runfolders.tool_preview_dir(base, board, 'mqs')) is None
    assert curves.run_label(a) == '3V3, 11-11 01:31:36' and curves.run_label(str(tmp_path / 'mqs_U3')) == 'mqs_U3'


def test_curves(tmp_path):
    cs = curves.load_curves(_pdn(str(tmp_path / 'p')))
    assert cs.kind == 'pdn' and [c.role for c in cs.curves] == ['data', 'reference', 'limit']
    assert 'rail P' in cs.info and cs.curves[2].name == 'target 50 mΩ'
    u1 = cs.curves[0]
    assert curves.value_at(u1, 1e6) == pytest.approx(0.02, rel=0.05)        # between points, along the log axes
    assert curves.value_at(u1, 1e3) is None
    ms = curves.load_curves(_mqs(str(tmp_path / 'm')))
    assert ms.kind == 'mqs' and list(ms.curves[0].y) == [3, 1.5, 0.9] and not ms.curves[0].role != 'data'
    assert curves.load_curves(str(tmp_path)) is None and curves.load_sets(str(tmp_path)) == []
    sets = curves.load_sets(FA.write('circuit', str(tmp_path / 'c')))     # several sets: a circuit's waveforms
    assert [x.title for x in sets] == ['light: voltages', 'light: currents', 'full: voltages', 'full: currents']
    assert not sets[0].logx and not sets[0].logy and curves.value_at(sets[0].curves[0], 0.25, False, False) == 1.0
    assert curves.load_sets(FA.write('thermal', str(tmp_path / 't'))) == []         # a result with none
    curves.export_csv(str(tmp_path / 'c.csv'), [cs, ms])
    import csv
    head, *rows = list(csv.reader(open(tmp_path / 'c.csv')))
    assert sum('frequency (Hz)' in h for h in head) == 2 and len(rows) == 21 and all(len(r) == len(head) for r in rows)
    assert rows[-1][-1] == '' and rows[0][-1] == '3'                  # the spectrum's 3 points, padded


@pytest.fixture
def window(tmp_path, monkeypatch):
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    from PySide6.QtCore import QSettings
    from kicad2ems_gui import application
    from kicad2ems_gui.app import MainWindow
    app = application()
    QSettings('kicad2ems', 'gui').clear()
    w = MainWindow()
    yield w, app
    w.setup.dirty = False
    w.system.stop()
    w.meters.stop()
    w.close()
    QSettings('kicad2ems', 'gui').clear()


def test_results_of_lists_every_analysis_and_compares_runs(window, tmp_path):
    w, app = window
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    w.setup.set_values(dict(board=str(board)))
    base = w.out_dir()
    t = __import__('datetime').datetime(2026, 11, 11, 1, 0, 0)
    old = _pdn(runfolders.tool_dir(base, str(board), 'pdn', 'P', now=t))
    new = _pdn(runfolders.tool_dir(base, str(board), 'pdn', 'P', now=t.replace(minute=5)), scale=2)
    nf = _mqs(runfolders.tool_dir(base, str(board), 'mqs', 'U3', now=t))
    w.refresh_runs()
    labels = [w.runs_box.itemText(i) for i in range(w.runs_box.count()) if w.runs_box.itemText(i)]
    assert labels == ['Power integrity: P, 2026-11-11 01:05:00', 'Power integrity: P, 2026-11-11 01:00:00',
                      'Near field: U3, 2026-11-11 01:00:00']
    w._pick_run(new)
    r = w.results
    assert r.kind() == 'pdn' and r.views.currentWidget() is r.curveplot and 'rail P' in r.info.text()
    assert r.modes() == ['Plots', 'Report', 'Tables'] and r.mode == 'Plots' and r.set_box.isHidden()
    assert w.runs_box.currentData() == new
    assert r.add_folder(old) and r.compared() == [os.path.abspath(old)]
    assert not r.add_folder(nf)                                     # another kind: not over these
    cp = r.curveplot
    assert [cs.label for cs in cp.sets] == ['P, 11-11 01:05:00', 'P, 11-11 01:00:00']
    cp.add_marker(1e6)
    row = cp.values()[0]
    assert row[0] == '1: 1 MHz' and len(row) == 3                   # this run's U1, the other's (no bare planes)
    assert float(row[1].split()[0]) == pytest.approx(2 * float(row[2].split()[0]), rel=0.02)
    r._fill_compare()
    acts = [a for a in r.cmp_menu.actions() if a.isCheckable()]
    assert [a.text() for a in acts] == ['Power integrity: P, 2026-11-11 01:00:00'] and acts[0].isChecked()
    acts[0].setChecked(False)
    assert r.compared() == []
    w._pick_run(nf)                                                 # the near field: its spectrum, its report
    assert r.kind() == 'mqs' and cp.main.curves[0].name == 'peak |H|'
    assert 'U3' in r.reportview.page.toPlainText() and r.info.text() == 'Near field, U3 on VIN: 3 harmonics'
    w.open_results(str(tmp_path), quiet=True)                       # nothing of an analysis: S-parameters again
    assert r.kind() == 'rf' and r.views.currentWidget() is r.splot and r.modes() == []
    assert all(b.isHidden() for b in r.mode_btns.values())


def test_a_result_as_its_plots_its_report_or_its_tables(window, tmp_path):
    """The Results page's three views of an analysis's result, whichever analysis: the ones the result has."""
    w, app = window
    w.show()
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    w.setup.set_values(dict(board=str(board)))
    base = w.out_dir()
    th = FA.write('thermal', runfolders.tool_dir(base, str(board), 'thermal', 'losses'), loss='L1=0.48\nQ2=0.2')
    ci = FA.write('circuit', runfolders.tool_dir(base, str(board), 'circuit', 'buck'))
    pd = FA.write('pdn', runfolders.tool_dir(base, str(board), 'pdn', 'P'), note=True)
    r = w.results
    w.refresh_runs()
    w._pick_run(th)                                                 # no curves: its report in front
    assert r.kind() == 'thermal' and r.modes() == ['Report', 'Tables'] and r.mode == 'Report'
    assert r.views.currentWidget() is r.reportview and r.reportview.mode() == 'Report'
    assert not r.mode_btns['Plots'].isEnabled() and r.mode_btns['Report'].isChecked() and not r.cmp_btn.isEnabled()
    assert r.info.text() == 'Thermal: hottest copper 73.0 °C' and 'L1' in r.reportview.page.toPlainText()
    r.mode_btns['Tables'].click()
    assert r.mode == 'Tables' and r.reportview.mode() == 'Tables' and r.reportview.table()[0] == 'Parts'
    assert r.reportview.grid.rowCount() == 2 and r.reportview.grid.item(0, 2).text() == '73.0'
    w._pick_run(pd)                                                 # the view kept, when the next result has it
    assert r.kind() == 'pdn' and r.mode == 'Tables' and r.reportview.table()[0] == 'Loads at DC'
    assert r.notes_btn.isHidden() and 'a note' in r.reportview.page.toPlainText()        # its notes: in its report
    r.set_mode('Plots')
    assert r.views.currentWidget() is r.curveplot and r.cmp_btn.isEnabled()
    w._pick_run(ci)                                                 # several curve sets: one at a time
    assert r.kind() == 'circuit' and r.mode == 'Plots' and not r.set_box.isHidden() and r.set_box.count() == 4
    assert r.curveplot.main.title == 'light: voltages' and not r.curveplot.main.logx
    r.set_box.setCurrentIndex(3)
    assert r.curveplot.main.title == 'full: currents' and r.curves is r.curve_sets[3]
    r.set_mode('Report')
    assert r.set_box.isHidden() and 'Stand-in circuit' in r.reportview.page.toPlainText()
    w._pick_run(th)                                                 # no plots there: its report
    assert r.mode == 'Report' and r.set_box.isHidden()


def test_pages_that_come_and_go(window):
    w, app = window
    w.show()
    app.processEvents()
    assert not w.docks['Filter'].isVisible()                        # opened by hand only
    w.acts['Filter'].trigger()
    assert w.docks['Filter'].isVisible()
    assert not w.docks['Circuit'].isVisible() and 'circuit' not in w.study.ticked()
    if 'circuit' in w.study.why:
        pytest.skip('pcbqs is not installed: Circuit cannot be ticked')
    w.study.set_ticked(['rf', 'circuit'])
    assert w.docks['Circuit'].isVisible()
    w.study.set_ticked(['rf'])
    assert not w.docks['Circuit'].isVisible()


def test_second_viewer(window, tmp_path):
    w, app = window
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    w.setup.set_values(dict(board=str(board)))
    base = w.out_dir()
    t = __import__('datetime').datetime(2026, 11, 11, 1, 0, 0)
    a = _pdn(runfolders.tool_dir(base, str(board), 'pdn', 'P', now=t))
    b = _pdn(runfolders.tool_dir(base, str(board), 'pdn', 'P', now=t.replace(minute=5)))
    w.refresh_runs(select=b)
    v2 = w.second_viewer()
    assert v2.runs.count() == 2 and v2.runs.currentData() == a      # the run before the one shown
    assert w.second_viewer() is v2
