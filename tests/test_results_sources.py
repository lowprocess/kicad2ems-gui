"""Every analysis's results in the pages: the run folders of pcbqs's tools (runfolders), their curves on the Results
page (curves.py, curveplot.py) with other runs over them, the pages that come and go, a second Viewer."""
import json
import os
import time

import numpy as np
import pytest

from kicad2ems_gui import curves, runfolders


def _pdn(folder, scale=1.0, rail='P'):
    os.makedirs(folder, exist_ok=True)
    f = np.logspace(4, 8, 21)
    z = dict(U1=dict(mag=(scale * 0.01 * (1 + f / 1e6)).tolist(), deg=[0] * 21, bare=(1e3 / f).tolist(), target=0.05, over=[]))
    res = dict(format=1, rail=rail, nets=[rail], ground=['GND'], volts=3.3, assumed_loads=False, tree=[], source=['L1'],
               loads=dict(U1=dict(I=2, V=3.29, drop=0.01, power_drop=0.006, ground_rise=0.004)), series={},
               loss_W=0.1, vias=dict(power=[], ground=[]), vertices=dict(power=10, ground=10), seconds=dict(total=1),
               notes=[], figures=[], pdn=dict(f=f.tolist(), target=0.05, z=z, cavities=[], parts={}, vertices=5))
    with open(os.path.join(folder, 'pdn.json'), 'w') as fh:
        json.dump(res, fh)
    return folder


def _mqs(folder):
    os.makedirs(folder, exist_ok=True)
    res = dict(format=1, selection=dict(converter='U3', vin='VIN', ground='GND', capacitors=['C1']), triangles=100,
               frequencies_Hz=[5e5, 1e6, 1.5e6], harmonic_peak_A=[1, .5, .3], copper_R_ohm=[1e-3] * 3,
               copper_L_H=[1e-9] * 3, peak_H_Am=[[3, 2], [1.5, 1], [0.9, 0.5]], notes=[])
    with open(os.path.join(folder, 'mqs.json'), 'w') as fh:
        json.dump(res, fh)
    return folder


def test_tool_run_folders(tmp_path):
    base, board = str(tmp_path / 'out'), str(tmp_path / 'b.kicad_pcb')
    t0 = __import__('datetime').datetime(2026, 11, 11, 1, 31, 36)
    a = runfolders.tool_dir(base, board, 'pdn', '+3V3', now=t0)
    assert os.path.basename(a) == 'b_pdn_3V3_20261111_013136'
    assert runfolders.tool_preview_dir(base, board, 'mqs').endswith('b_mqs_preview')
    _pdn(a)
    os.makedirs(runfolders.tool_dir(base, board, 'pdn', 'X', now=t0.replace(second=40)))     # stopped: no result
    _mqs(str(tmp_path / 'mqs_U3'))                                  # the old place: beside the board
    _pdn(str(tmp_path / 'out' / 'other_pdn_P_20261111_013136'))     # another board's
    found = runfolders.tool_runs(base, board)
    assert [(os.path.basename(d), k) for d, k, _ in found] == [('mqs_U3', 'mqs'), ('b_pdn_3V3_20261111_013136', 'pdn')]
    assert found[1][2] == 'Power integrity: 3V3, 2026-11-11 01:31:36'
    assert runfolders.tool_kind(a) == 'pdn' and runfolders.tool_kind(str(tmp_path)) is None
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
    assert curves.load_curves(str(tmp_path)) is None
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
    w.system.stop()
    w.meters.stop()
    w.close()
    QSettings('kicad2ems', 'gui').clear()


def test_results_of_lists_every_analysis_and_compares_runs(window, tmp_path):
    from kicad2ems_gui.curveplot import CurvePlot
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
    w._pick_run(nf)                                                 # the near field: its spectrum, its summary
    assert r.kind() == 'mqs' and cp.main.curves[0].name == 'peak |H|'
    assert 'U3' in w.mqs.summary.toPlainText()
    assert w.mqs.tabs.count() == (1 if w.mqs.desc is not None else w.mqs.tabs.count())
    w.open_results(str(tmp_path), quiet=True)                       # nothing of an analysis: S-parameters again
    assert r.kind() == 'rf' and r.views.currentWidget() is r.splot


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
