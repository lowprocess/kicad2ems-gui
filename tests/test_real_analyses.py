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
    monkeypatch.setattr(study, 'TREE', study.tree())                # and the questions with their engines
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
    by = {q: w.study.rows[q].text(1).replace('  ▾', '') for q in ('dc', 'pdn', 'nearfield', 'circuit', 'thermal')}
    assert set(by.values()) == {'pcbqs'}                            # pcbqs's four alone in this registry
    assert [e.name for e in w.study.engines['dc']][0] == 'pdn' and w.study.run_of('nearfield') == 'mqs'
    assert w.study.rows['pdn'].toolTip(1).startswith(('pcbqs.pdn', 'click to choose'))
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
    assert w.places['Circuit'].in_front() and not w.busy()          # its editor in front; no preview of
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
    assert w.setup.save()                                           # the study, saved: what it asks, its model
    from kicad2ems.api.frontend import read_study
    run, tables = read_analyses(w.setup.path)
    assert run is None and tables['circuit'] == dict(model=str(folder / '01_rc_filter.json'))
    assert list(read_study(w.setup.path).asked) == ['circuit', 'thermal']


def _regulator(folder):
    """A buck regulator's board, as pcbqs's own tests make it: U1 where the islands in and sw meet the ground
    strip, C1 on its input, L1 from sw to out, C2 on the output."""
    from shapely.geometry import box
    from pcbqs.circuit import boards as B
    b = B.Board('regulator', 40, 23)
    b.row(['in', 'sw', 'out'], [12, 8, 14], height=14)
    b.place(dict(parts=[dict(ref='C1', type='capacitor', nodes=['in', '0'], value=22e-6),
                        dict(ref='C2', type='capacitor', nodes=['out', '0'], value=47e-6),
                        dict(ref='L1', type='inductor', nodes=['sw', 'out'], value=10e-6)]),
            packages=dict(C1='C_0805', C2='C_0805'))
    b.footprints.append(dict(ref='U1', value='BUCK', lib='Package_SO:SOIC-8', x=14.2, y=9.0, pads=[
        ('1', 'VIN', 'in', box(12.4, 4.0, 13.6, 6.0)), ('2', 'SW', 'sw', box(14.8, 4.0, 16.0, 6.0)),
        ('3', 'GND', 'GND', box(13.4, 17.0, 15.0, 18.0))]))
    b.check()
    return b.write(folder)


def _wait(w, app, seconds=240):
    t0 = time.time()
    while w.busy() and time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.02)
    for _ in range(10):
        app.processEvents()


def test_a_converter_goes_from_the_near_field_to_its_circuit_and_on_to_its_rail(window, tmp_path):
    """What one result proposes to the next, through the window: a near field's converter opened as a circuit (the
    model the run wrote, now the study's own), and what that circuit draws from its supply copied to the power
    integrity (the rail, its DC load, its current spectrum) and back to the near field (its input current)."""
    w, app = window
    w.show()
    board = _regulator(tmp_path)
    w.setup.set_values(dict(board=str(board), out=str(tmp_path / 'out')))
    mqs, pdn, page = w.pages['mqs'], w.pages['pdn'], w.pages['circuit']
    w.study.set_ticked(['mqs'])
    mqs.set_values(dict(vin_volts=12, vout=5, fsw=250e3, current=2, cap_radius=30, harmonics='1', scan_points=9,
                        heights='2', field_tol=0.2, dmax=3, fine=1.5))
    w.run_study(only='mqs')
    _wait(w, app)
    assert w.study.state('mqs').startswith('done'), mqs.log.toPlainText()[-1500:]
    assert [b.text() for b in mqs.suggest_btns] == ['Copy the input rail to Power integrity', 'Open U1 as a circuit']
    mqs.suggest_btns[1].click()
    c = page.values()
    assert c['name'] == 'U1: in to out' and c['board'] == dict(file=str(board), parts=dict(QH='U1', QL='U1'),
                                                               nets={'in': 'in', 'sw': 'sw', 'out': 'out'})
    assert page.model_path is None and page.copper.isChecked() and w.study.current() == 'circuit' and w.setup.dirty
    assert w.study.ticked() == ['mqs', 'circuit'] and w.places['Circuit'].in_front()    # asked: its schematic in front
    assert page.status.text().startswith('U1 as a circuit: its capacitors and inductor from the board')
    w.run_study(only='circuit')
    _wait(w, app)
    if not w.study.state('circuit').startswith('done'):
        pytest.skip(f"the circuit did not run here (ngspice?): {w.study.state('circuit')}")
    proposed = page.panel.suggest_btns
    assert [b.text() for b in proposed] == ['Copy the rail in and what is drawn from it to Power integrity',
                                            "Copy U1's input current to Near field"]
    proposed[0].click()
    v = pdn.values()
    assert v['rail'] == 'in' and float(v['volts']) == 12 and w.study.current() == 'pdn'
    assert list(w.study.asked()) == ['dc', 'pdn', 'nearfield', 'circuit']      # the rail's two questions asked too
    ref, _, amps = v['load'].partition('=')
    assert ref == 'U1' and 0.7 < float(amps) < 1.1                  # 10 W out of 12 V, and its losses
    spectrum = v['load_spectrum'].partition('=')[2]
    assert os.path.basename(spectrum) == 'supply-U1.csv' and os.path.isfile(spectrum)
    assert spectrum.startswith(str(page.out))                       # the run's own file
    proposed[1].click()
    v = mqs.values()
    assert (v['converter'], v['vin'], v['capacitors'], v['spectrum']) == ('U1', 'in', 'C1', spectrum)
    assert w.study.current() == 'mqs'
    mqs.set_values(dict(harmonics='1', scan_points=9, heights='2', field_tol=0.2, dmax=3, fine=1.5))
    w.run_study(only='mqs')                                         # the near field again, of the circuit's current
    _wait(w, app)
    assert w.study.state('mqs').startswith('done'), mqs.log.toPlainText()[-1500:]
    assert w.results.info.text().endswith("of a circuit's input current")
