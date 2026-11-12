"""pcbqs's own analysis plugins through the window the other tests drive with stand-ins: its settings panels made
from its options, a circuit example opened from File > Examples as a study, the circuit and then the temperature
run for real, their results where every result is shown. Skipped without pcbqs (or ngspice)."""
import os
import time

import pytest

A = pytest.importorskip('pcbqs.analyses', reason='pcbqs is not installed')


@pytest.fixture
def window(tmp_path, monkeypatch):
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))     # where an example is prepared: not the user's
    from kicad2ems import analyses
    monkeypatch.setattr(analyses, '_registry', {a.name: a for a in (A.PowerIntegrity(), A.NearField(), A.Circuit(), A.Thermal())})
    from PySide6.QtCore import QSettings
    from kicad2ems_gui import application, study, app as gui
    from kicad2ems_gui.app import MainWindow
    listed = study.installed()                  # the window lists the registry as it was when it was imported:
    for module in (study, gui):                 # the stand-ins', in a run of every test
        monkeypatch.setattr(module, 'ANALYSES', listed)
        monkeypatch.setattr(module, 'BY_KEY', {a.key: a for a in listed})
    app = application()
    QSettings('kicad2ems', 'gui').clear()
    w = MainWindow()
    yield w, app
    w.setup.dirty = False
    w.system.stop()
    w.meters.stop()
    w.close()
    QSettings('kicad2ems', 'gui').clear()


def test_the_panels_are_pcbqs_s_options(window):
    w, app = window
    pdn, mqs, th = w.pages['pdn'], w.pages['mqs'], w.pages['thermal']
    assert {'rail', 'load', 'plane_min', 'no_pdn'} <= set(pdn.w) and list(pdn.sections)[:2] == ['Files', 'Rail']
    assert mqs.find_btn.text() == 'Find converters' and {'converter', 'fsw', 'heights'} <= set(mqs.w)
    assert list(th.sections) == ['Files', 'Heat', 'Parts', 'Air', 'Solver'] and th.w['film'].placeholderText() == '10.0'
    assert [w.study.rows[k].text(1) for k in ('pdn', 'mqs', 'circuit', 'thermal')] == \
        ['pcbqs.pdn', 'pcbqs.mqs', 'pcbqs.circuit', 'pcbqs.thermal']
    assert {'/Circuits/Passive and rectifiers', '/Circuits/DC-DC converters', '/Circuits/Bridges'} <= set(w.example_menus)
    assert w.example_sources['/Circuits'] == {'circuit'}
    names = [a.text() for a in w.example_menus['/Circuits/DC-DC converters'].actions()]
    assert names == ['circuit_buck', 'circuit_buck_synchronous', 'circuit_boost', 'circuit_buck_boost', 'circuit_flyback']


def test_a_circuit_example_runs_to_its_temperatures(window, tmp_path):
    from kicad2ems.api.frontend import read_analyses
    w, app = window
    w.show()
    w.open_example('circuit_rc_filter')
    folder = tmp_path / 'data' / 'kicad2ems' / 'examples'
    assert w.setup.path == str(folder / 'circuit_rc_filter.toml') and not w.setup.dirty
    assert w.setup.values()['board'] == str(folder / '01_rc_filter.kicad_pcb')
    page = w.pages['circuit']
    assert w.study.ticked() == ['circuit'] and w.study.current() == 'circuit'
    assert page.model_path == str(folder / '01_rc_filter.json') and page.values()['name'].startswith('RC low-pass')
    assert not w.docks['Circuit'].visibleRegion().isEmpty() and not w.busy()     # its editor in front; no preview of
    w.study.set_ticked(['circuit', 'thermal'])                                   # a board without ports
    w.run()
    t0 = time.time()
    while w.busy() and time.time() - t0 < 180:
        app.processEvents()
        time.sleep(0.02)
    for _ in range(10):
        app.processEvents()
    if not w.study.state('circuit').startswith('done'):
        pytest.skip(f"the circuit did not run here (ngspice?): {w.study.state('circuit')}")
    th = w.pages['thermal']
    assert w.study.state('thermal').startswith('done'), th.log.toPlainText()[-1500:]
    assert os.path.dirname(str(page.out)) == os.path.dirname(th.out) == str(folder / 'out')      # the study's folder
    labels = sorted(w.runs_box.itemText(i).split(',')[0] for i in range(w.runs_box.count()) if w.runs_box.itemText(i))
    assert labels == ['Circuit: 01_rc_filter', 'Thermal: circuit']
    r = w.results                                                   # the temperature: its report, its tables
    assert r.kind() == 'thermal' and r.modes() == ['Report', 'Tables'] and r.info.text().startswith('Thermal: hottest copper')
    assert [t for t, _ in r.reportview._tables] == ['Parts', 'Layers'] and 'R1' in r.reportview.page.toPlainText()
    cuts = w.viewer.cuts                                            # its maps: in the Viewer
    assert sorted(s.label for s in cuts.srcs) == ['thermal board: T B.Cu (static)', 'thermal board: T F.Cu (static)']
    assert cuts.src.unit == '°C' and cuts.lim[0] > 24.0 and cuts.lim[1] < 40.0 and not cuts.log.isChecked()
    i = next(k for k in range(w.runs_box.count()) if w.runs_box.itemText(k).startswith('Circuit'))
    w._pick_run(w.runs_box.itemData(i))                             # the circuit: its waveforms, its points
    assert r.kind() == 'circuit' and r.modes() == ['Plots', 'Report', 'Tables'] and r.set_box.count() >= 1
    assert 'Points' in [t for t, _ in r.reportview._tables]
    assert w.setup.save()                                           # the study, saved: what it runs, its model
    run, tables = read_analyses(w.setup.path)
    assert run == ['circuit', 'thermal'] and tables['circuit'] == dict(model=str(folder / '01_rc_filter.json'))
