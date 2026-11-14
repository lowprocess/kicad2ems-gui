"""An analysis's settings panel (analysispanel.py), made from whatever the registry's plugin declares: its form,
what a config holds of it, a run of its command (the stand-ins' real child process), what the board and a result
propose. Nothing here is of one analysis: the stand-ins (fake_analyses.py) are any plugin."""
import os
import time

import pytest

import fake_analyses as FA
from kicad2ems_gui import analysispanel as AP


@pytest.fixture
def app():
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def wait(app, panel, seconds=60):
    t0 = time.time()
    while panel.proc is not None and time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.02)
    for _ in range(5):
        app.processEvents()
    assert panel.proc is None, panel.log.toPlainText()


def test_values_as_a_config_holds_them():
    o = FA.opt
    assert AP.typed(o('volts', 'float', 3.3), '5') == 5.0 and AP.typed(o('volts', 'float', 3.3), '3.3') is None
    assert AP.typed(o('n', 'int', 4), '8') == 8 and AP.typed(o('n', 'int', 4), '') is None
    assert AP.typed(o('rail'), ' +3V3 ') == '+3V3' and AP.typed(o('x', 'float', 1.0), 'vout/2') == 'vout/2'
    assert AP.typed(o('on', 'bool', False), True) is True and AP.typed(o('on', 'bool', False), False) is None
    assert AP.typed(o('load', 'list', []), 'U1=2\nCA1=47e-6,0.02, U2=1') == ['U1=2', 'CA1=47e-6,0.02', 'U2=1']
    assert AP.typed(o('load', 'list', []), ' \n') is None


def test_the_form_is_the_plugin_s_options(app, tmp_path):
    p = AP.AnalysisPanel(FA.PowerIntegrity())
    assert list(p.w) == ['rail', 'volts', 'load', 'scale', 'no_pdn'] and list(p.sections) == ['Files', 'Rail', 'PDN impedance']
    assert p.sections['Rail'].expanded and not p.sections['PDN impedance'].expanded      # the first group open
    assert p.w['volts'].placeholderText() == '3.3' and '--rail' in p.w['rail'].toolTip()
    assert not p.run_btn.isHidden() and p.find_btn is None          # alone: its own Run; nothing to find
    edits = []
    p.changed.connect(lambda: edits.append(1))
    p.set_values(dict(rail='+3V3', load=['U1=2', 'U2=1'], no_pdn=True, volts=5.0, nothing='x'))
    assert p.values() == dict(rail='+3V3', volts='5', load='U1=2\nU2=1', scale='', no_pdn=True) and not edits
    p.w['rail'].setText('+5V')                                      # by hand: a change a config should hold
    p.board.setText(str(tmp_path / 'b.kicad_pcb'))
    assert len(edits) == 2
    assert AP.config_values(p, str(tmp_path)) == dict(board='b.kicad_pcb', rail='+5V', volts=5.0, load=['U1=2', 'U2=1'],
                                                      no_pdn=True)
    p.reset()
    assert p.values() == dict(rail='', volts='', load='', scale='', no_pdn=False) and p.board.text() == '' and len(edits) == 2
    assert AP.config_values(p) == {}
    th = AP.AnalysisPanel(FA.Thermal())
    th.set_values(dict(circuit=str(tmp_path / 'run'), film=12))
    assert AP.config_values(th, str(tmp_path)) == dict(circuit='run', film=12.0)     # the plugin's paths: relative


def test_a_run_alone(app, tmp_path):
    """The plugin's command as a child process: why it cannot start on the status line; its progress there while
    it runs, its log kept; done: its report's line; a failure: the tool's own last word."""
    p = AP.AnalysisPanel(FA.PowerIntegrity())
    p.start()
    assert p.proc is None and p.status.text() == 'choose a board first'
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    p.board.setText(str(board))
    p.start()
    assert p.proc is None and p.status.text() == 'name the rail (its net)'
    p.start(preview=True)                                           # it has no preview: nothing
    assert p.proc is None
    p.set_values(dict(rail='+3V3', scale=2))
    p.start()
    assert p.proc is not None and not p.run_btn.isEnabled() and p.stop_btn.isEnabled()
    assert p.out == str(tmp_path / 'pdn__3V3')                      # alone: <name>_<tag> beside the board
    wait(app, p)
    assert os.path.isfile(os.path.join(p.out, 'pdn.json')) and p.run_btn.isEnabled()
    assert p.status.text() == 'done: Power integrity, rail +3V3: worst DC drop 20.00 mV (at U1)'
    log = p.log.toPlainText()
    assert log.startswith('$ python ') and 'pdn: reading the board' in log and 'pdn: solved' in log
    assert p.result == p.out
    p.outdir.setText(str(tmp_path / 'named'))
    p.set_values(dict(rail='FAIL'))
    p.start()
    wait(app, p)
    assert p.out == str(tmp_path / 'named') and not os.path.exists(os.path.join(p.out, 'pdn.json'))
    assert p.status.text().startswith('the run failed (exit 3): pdn: error: the rail has no copper')


def test_a_preview_and_what_the_board_proposes(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    p = AP.AnalysisPanel(FA.NearField())
    assert p.find_btn.text() == 'Find converters'
    p.find()
    assert p.status.text() == 'choose a board first'
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    p.board.setText(str(board))
    asked = []
    monkeypatch.setattr(QInputDialog, 'getItem', lambda *a: (asked.append(a[3]) or a[3][1], True))
    edits = []
    p.changed.connect(lambda: edits.append(1))
    p.find()
    wait(app, p)
    assert asked == [['U7: VIN (inductor L3)', 'U9: +5V (inductor L4)']]                 # two: which, asked
    assert p.values()['converter'] == 'U9' and p.values()['vin'] == '+5V' and edits == [1]
    assert p.status.text() == 'U9: +5V: set; Run or Preview'
    p.pick([('U1: A (x)', dict(converter='U1'))])                   # one: taken
    assert p.values()['converter'] == 'U1' and len(asked) == 1
    p.pick([])
    assert p.status.text() == 'no converters found on this board'
    p.start(preview=True)
    wait(app, p)
    assert p.out == str(tmp_path / 'mqs_U1' / 'preview') and os.path.isfile(os.path.join(p.out, 'mqs-preview.json'))
    assert p.status.text() == 'preview ready'


def test_an_option_proposed_without_a_value_must_be_set(app, tmp_path):
    p = AP.AnalysisPanel(FA.PowerIntegrity())
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    p.board.setText(str(board))
    p.set_values(dict(rail='VIN'))
    p.required = {'volts'}
    p.start()
    assert p.proc is None and p.status.text().startswith('Set volts before Run')
    p.set_values(dict(volts=12))
    assert p.required == set()
    p.start()
    wait(app, p)
    assert p.status.text().startswith('done')


@pytest.mark.skipif(os.name != 'posix', reason='SIGTERM')
def test_stop_lets_the_tool_stop_what_it_started(app, tmp_path):
    """Stop asks the tool to end (SIGTERM: pcbqs stops its ngspice runs, kicad2ems-fem its Elmer and Palace), and a
    table's next rows are not run. It was killed at once, so what it had started ran on, and the next row began."""
    p = AP.AnalysisPanel(FA.PowerIntegrity())
    board = tmp_path / 'b.kicad_pcb'
    board.write_text('')
    p.board.setText(str(board))
    p.outdir.setText(str(tmp_path / 'out'))
    p.set_values(dict(rail='SLOW'))
    p.start()
    t0 = time.time()
    while 'pdn: solving' not in p.log.toPlainText() and time.time() - t0 < 30:
        app.processEvents()
        time.sleep(0.02)
    p._queue = [dict(rail='+3V3')]                                  # as a table's next row
    p.stop()
    wait(app, p)
    assert p._queue == [] and 'stopped what it started' in p.log.toPlainText() and p.status.text() == 'stopped'
    child = int((tmp_path / 'child.pid').read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)
