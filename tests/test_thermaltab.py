"""The Thermal page (thermaltab.py): pcbqs.thermal's command line from the page's settings, where its losses and
its board come from, and a run of the real tool through the window's Study, its result under Results of."""
import json
import os
import time

import pytest

from kicad2ems_gui import thermaltab as T


def test_the_command_line():
    desc = dict(options=[dict(key='loss', flag='--loss', kind='list', default=[]),
                         dict(key='film', flag='--film', kind='float', default=10.0),
                         dict(key='circuit', flag='--circuit', kind='str', default='')])
    argv = T.thermal_argv(dict(loss='Q1=0.35\nL1=0.5', film='', circuit=''), 'b.kicad_pcb', 'out', desc)
    assert argv[1:] == ['-m', 'pcbqs.thermal', 'b.kicad_pcb', '--out', 'out', '--loss', 'Q1=0.35', '--loss', 'L1=0.5']
    argv = T.thermal_argv(dict(circuit='run', film='12'), None, 'out', desc)        # the run names the board
    assert argv[1:] == ['-m', 'pcbqs.thermal', '--out', 'out', '--circuit', 'run', '--film', '12']


def circuit_folder(tmp_path, board):
    run = tmp_path / 'circuit-run'
    run.mkdir()
    (run / 'model.json').write_text(json.dumps(dict(format=2, board=dict(file=str(board)), parts=[])))
    (run / 'circuit.json').write_text(json.dumps(dict(cases=[dict(name='full', loss_W=0.5,
                                                                  parts={'L1': dict(power_W=0.4)})])))
    return run


def test_a_circuit_run_and_its_board(tmp_path):
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    run = circuit_folder(tmp_path, board)
    assert T.circuit_run(run) == (str(run), str(board))
    assert T.circuit_run(tmp_path) is None and T.circuit_run(None) is None


def example_board():
    try:
        import pcbqs.circuit
    except ImportError:
        pytest.skip('pcbqs is not installed')
    b = os.path.join(os.path.dirname(pcbqs.circuit.__file__), 'examples', '05_buck_synchronous.kicad_pcb')
    if not os.path.isfile(b):
        pytest.skip('pcbqs without its example boards')
    return b


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
    if w.thermal.desc is None:
        pytest.skip('pcbqs without its thermal tool')
    yield w, app
    w.system.stop()
    w.meters.stop()
    w.close()
    QSettings('kicad2ems', 'gui').clear()


def test_where_the_losses_come_from(window, tmp_path):
    w, app = window
    p = w.thermal
    assert 'Thermal' in w.docks and w.study.rows['thermal'].text(1) == 'pcbqs.thermal'
    assert 'losses' in p.plan()                                     # nothing typed, no circuit run
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    w.circuit.out = circuit_folder(tmp_path, board)                 # the Circuit page's latest run (a Path)
    vals, b, name = p.plan()
    assert vals['circuit'] == str(w.circuit.out) and b == str(board) and name == 'circuit-run'
    p.set_values(dict(loss='Q1=0.2'))                               # typed: those, on the study's board
    w.setup.set_values(dict(board=str(board)))
    vals, b, name = p.plan()
    assert not vals.get('circuit') and b == str(board) and name == 'losses'
    w.setup.set_values(dict(board=''))
    assert 'board' in p.plan()


def test_a_run_through_the_study(window, tmp_path):
    """Thermal ticked and run as the window runs it: the real tool on a pcbqs example board, the summary on the
    page, the run under Results of."""
    w, app = window
    board = example_board()
    w.setup.set_values(dict(board=board, out=str(tmp_path / 'out')))
    w.thermal.set_values(dict(loss='L1=0.48\nQ2=0.2', theta='Q2=8'))
    w.run_study(only='thermal')
    t0 = time.time()
    while (w.job is not None or w.thermal.proc is not None) and time.time() - t0 < 120:
        app.processEvents()
        time.sleep(0.05)
    assert w.job is None, w.thermal.log.toPlainText()[-2000:]
    out = w.thermal.out
    res = T.load_result(out)
    assert res is not None, w.thermal.log.toPlainText()[-2000:]
    parts = res['grid']['parts']
    assert set(parts) == {'L1', 'Q2'} and parts['Q2']['part_C'] == pytest.approx(parts['Q2']['board_C'] + 1.6)
    assert res['grid']['board'] == os.path.abspath(board) and os.path.isfile(os.path.join(out, 'thermal.png'))
    assert 'Hottest copper' in w.thermal.summary.toHtml() and 'hottest copper' in w.thermal.status.text()
    labels = [w.runs_box.itemText(i) for i in range(w.runs_box.count())]
    assert any(l.startswith('Thermal: losses,') for l in labels) and w.runs_box.currentData() == out
    assert 'done' in w.study.rows['thermal'].text(2)
