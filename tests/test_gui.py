"""kicad2ems-gui: the settings form without a display, and the Qt window (offscreen)."""
import json, math, os, pytest
import numpy as np
from kicad2ems_gui.runner import write_toml, settings_values, FIELDS
from kicad2ems.config import build_settings


def test_settings_round_trip(tmp_path):
    vals = dict(board=str(tmp_path / 'b.kicad_pcb'), nets=['RF', 'GND'], fmin=1.0, fmax=6.0, points=201,
                ports=['P3=J1.1', 'P4@1,2,F.Cu'], cut_ports=True, region=[0.0, 0.0, 10.0, 5.0], fast='qucsator',
                end_on='ports', fine=None)
    p = tmp_path / 'c.toml'
    write_toml(p, vals)
    s = build_settings({}, str(p))
    assert s.nets == ['RF', 'GND'] and s.points == 201 and s.ports == ['P3=J1.1', 'P4@1,2,F.Cu'] and s.cut_ports
    assert s.region == (0, 0, 10, 5) and s.fast == 'qucsator' and s.fine is None
    back = settings_values(str(p))
    assert set(back) == {k for k, *_ in FIELDS} and back['fmax'] == 6.0


def test_window_builds(tmp_path):
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from kicad2ems_gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.setup.set_values(dict(board='x.kicad_pcb', nets=['RF'], fmin=1.0, fast='skrf', cut_ports=True, ports=['P3=J1.1']))
    v = w.setup.values()
    assert v['board'] == 'x.kicad_pcb' and v['nets'] == ['RF'] and v['cut_ports'] is True
    assert v['solvers'] == ['auto', 'scikit'] and 'fast' not in v              # the default (auto) + fast = skrf
    assert v['ports'] == ['P3=J1.1']
    w.runtab.status(dict(run='P1', step=1000, db=-12.0, fraction=0.3, eta=65))
    assert w.runtab.bars['P1'].value() == 30
    w.close()


def test_dump_lists_and_extra_settings(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('board = "b.kicad_pcb"\nmode = "antenna"\nair = 7.5\nno_mask = true\n'
                   'dump = ["E@F.Cu@2,6", "J@y=3"]\n[openems]\nbc = "pml_8"\n')
    vals = settings_values(str(cfg))
    assert vals['mode'] == 'antenna' and vals['dump'] == ['E@F.Cu@2,6', 'J@y=3']
    from kicad2ems_gui.runner import extra_values
    extra = extra_values(str(cfg))
    assert extra == dict(mask=False, bc='pml_8')                    # kept for the runs: no field in the form
    assert vals['air'] == 7.5                                       # the air margin has one (openEMS + gfdtd)
    write_toml(tmp_path / 'r.toml', dict(vals, **extra))
    s = build_settings({}, str(tmp_path / 'r.toml'))
    assert s.air == 7.5 and not s.mask and s.antenna and s.dump == ['E@F.Cu@2,6', 'J@y=3']
    write_toml(tmp_path / 'r.toml', dict(vals, **extra, air='5,5,5,40,5,5'))     # as the field writes six
    assert build_settings({}, str(tmp_path / 'r.toml')).air == (5, 5, 5, 40, 5, 5)


def test_window_tabs(tmp_path):
    """Four pages (Viewer, Run, Results, Filter), the settings collapsed, the Solvers window behind ? and Help."""
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from kicad2ems_gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.setup.set_values(dict(dump=['E@F.Cu@2,6', 'H@volume'], mode='antenna'))
    v = w.setup.values()
    assert v['dump'] == ['E@F.Cu@2,6', 'H@volume'] and v['mode'] == 'antenna'
    w.setup.extra = dict(air=3.0)
    assert w.setup.values()['air'] == 3.0
    assert list(w.docks) == ['Viewer', 'Run', 'Results', 'Filter']
    assert w.viewer.view() in ('3D', 'Plan')                         # 3D when OpenGL can be had
    w.viewer.set_view('Plan')
    assert w.viewer.view() == 'Plan' and w.viewer.buttons['Plan'].isChecked()
    assert all(not s.expanded for s in w.setup.sections.values())  # settings collapsed when the window opens
    assert 'set)' in w.setup.sections['FDTD/Field dumps'].head.text()   # the dumps given above count
    assert 'set)' in w.setup.parents['FDTD'][0].head.text()               # and in the FDTD section
    assert {'Open', 'Save', 'Preview', 'Run', 'Stop'} <= set(w.acts)
    assert w.setup.help_btn.text() == '?' and not w.solvers_dialog.isVisible()
    w.setup.help_btn.click()                                        # ? beside Solvers: the Solvers window
    assert w.solvers_dialog.isVisible() and w.system.isVisibleTo(w.solvers_dialog)
    w.fields.load(str(tmp_path))                                    # an empty folder: no dumps, no error
    assert w.fields.src is None and not w.results.load_antenna(str(tmp_path))
    assert not w.viewer.load(str(tmp_path)) and not w.viewer.buttons['Cut'].isEnabled()
    w.setup.dirty = False
    w.close()


def test_solver_boxes_estimates_and_availability():
    """A preview's estimates beside the solver tick boxes; a solver that cannot run here says why there."""
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from kicad2ems_gui import application
    from kicad2ems_gui.app import MainWindow
    app = application()
    w = MainWindow()
    w.system.stop()
    w.setup.set_estimates(dict(solvers=dict(mom25d=dict(seconds=35, gb=1.3, what='4,657 unknowns'),
                                            openems=dict(seconds=900, gb=0.4))))
    assert w.setup.solver_boxes['mom25d'].text() == 'mom25d (MoM)  ·  ~35 s, 1.3 GB'
    assert w.setup.solver_boxes['openems'].text().endswith('~15 min, 0.4 GB')
    w.setup.dirty = False
    w.setup.new()                                                   # another board: the estimates go
    assert w.setup.solver_boxes['mom25d'].text() == 'mom25d (MoM)'
    w.setup.set_availability(dict(solvers=[dict(name='openems', ok=False, what='no CSXCAD'),
                                           dict(name='mom25d', ok=True, what='0.6')]))
    assert 'no CSXCAD' in w.setup.solver_boxes['openems'].toolTip() and w.setup.solver_boxes['mom25d'].toolTip() == ''
    w.setup.dirty = False
    w.close()
    app.processEvents()


def test_run_panel_plots_the_mom25d_sweep():
    """mom25d's adaptive-sweep steps (status events with change / pred) go to the Run panel's plot: its model
    change and prediction error in dB per solve, and the tolerance it stops at."""
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from kicad2ems_gui import application
    from kicad2ems_gui.app import MainWindow
    app = application()
    w = MainWindow()
    rt = w.runtab
    for k, (c, p) in enumerate([(2.0, float('inf')), (0.1, 0.5), (1e-3, 2e-3)], 6):
        rt.status(dict(run='mom25d', fraction=k / 60, solves=k, f_ghz=2.4))     # progress: a bar, no curve
        rt.status(dict(run='mom25d', afs_solves=k, change=c, pred=p, tol=5e-3))
    assert set(rt.curves) == {'mom25d model change', 'mom25d prediction error'}
    xs, ys = rt.hist['mom25d model change']
    assert xs == [6, 7, 8] and abs(ys[-1] + 60) < 1e-9                         # 1e-3: -60 dB
    assert rt.hist['mom25d prediction error'][0] == [7, 8]                       # the first has none
    assert rt._tol is not None and abs(rt._tol.value() - 20 * math.log10(5e-3)) < 1e-9
    assert not rt.sweep.isHidden() and rt.plot.isHidden()                       # mom25d alone: its plot alone
    rt.status(dict(run='P1', step=1000, db=-10.0, fraction=0.1))                # openEMS too: both, one above the other
    assert not rt.sweep.isHidden() and not rt.plot.isHidden() and 'P1' in rt.curves
    rt.reset()
    assert rt.sweep.isHidden() and not rt.plot.isHidden() and not rt.curves
    w.close()
    app.processEvents()


def test_save_config_keeps_the_file(tmp_path):
    """Saving over a loaded config keeps its comments, tables and unknown keys; paths relative to the file."""
    from kicad2ems_gui.runner import save_config, extra_values
    (tmp_path / 'b.kicad_pcb').write_text('')
    src = tmp_path / 'c.toml'
    src.write_text('# my board\nboard = "b.kicad_pcb"   # the board\npos = "x.pos"\nfmin = 1.0  # GHz\n'
                   'nets = [\n  "RF",\n  "GND",\n]\nfuture_key = 3\n\n[openems]\nair = 5.0   # mm\nend-db = -40\n')
    vals = dict(settings_values(str(src)), **extra_values(str(src)))
    vals.update(fmin=2.0, nets=['RF'], **{'solver:mom25d': True})
    del vals['pos']                                                 # the field was cleared
    save_config(str(src), vals, template=str(src))
    text = src.read_text()
    assert '# my board' in text and 'board = "b.kicad_pcb"   # the board' in text
    assert 'fmin = 2.0  # GHz' in text and 'pos' not in text and 'future_key = 3' in text
    assert 'air = 5.0   # mm' in text and 'end-db = -40.0' in text
    assert text.index('solvers = ["auto", "mom25d"]') < text.index('[openems]')
    assert '\nout =' not in text and 'solver:' not in text          # the default folder is not pinned to the cwd
    s = build_settings({}, str(src))
    assert s.fmin == 2.0 and s.nets == ['RF'] and s.pos is None and s.air == 5.0
    assert s.solver_plan()[0] == ['auto', 'mom25d']
    assert s.board == str(tmp_path / 'b.kicad_pcb')
    new = tmp_path / 'sub' / 'n.toml'                                # a new file: only what differs from the defaults
    new.parent.mkdir()
    save_config(str(new), vals)
    t = new.read_text()
    assert 'board = "../b.kicad_pcb"' in t and 'points' not in t and 'fmin = 2.0' in t
    assert build_settings({}, str(new)).board == str(tmp_path / 'b.kicad_pcb')


def _s2p(path, f, S, names=('IN', 'OUT')):
    with open(path, 'w') as fh:
        fh.write(f"! ports: 1={names[0]}, 2={names[1]}\n# Hz S RI R 50\n")
        for fi, s in zip(f, S):
            fh.write(f"{fi:.6e} " + " ".join(f"{v.real:.9e} {v.imag:.9e}" for v in (s[0, 0], s[1, 0], s[0, 1], s[1, 1])) + "\n")


def test_traces(tmp_path):
    import numpy as np
    from kicad2ems_gui.traces import load_traces, transform, value_at, export_csv, smith_grid, default_visible
    f = np.linspace(1e9, 3e9, 21)
    tau = 0.5e-9                                                    # a matched 0.5 ns line
    S = np.zeros((21, 2, 2), complex)
    S[:, 1, 0] = S[:, 0, 1] = np.exp(-2j * np.pi * f * tau)
    S[:, 0, 0] = S[:, 1, 1] = 0.1
    _s2p(tmp_path / 'b_openems.s2p', f, S)
    _s2p(tmp_path / 'b_mom.s2p', f, S)
    trs = load_traces([('t', str(tmp_path / 'b_openems.s2p')), ('m', str(tmp_path / 'b_mom.s2p'))])
    assert [t.source for t in trs[:4]] == ['openEMS'] * 4 and trs[4].source == 'mom25d'
    s21 = next(t for t in trs if t.param == 'S21')
    assert s21.title == 'S21 (OUT ← IN)' and default_visible(s21) and not default_visible(trs[2])
    assert np.allclose(transform('Group delay (ns)', s21)[1], 0.5)
    s11 = next(t for t in trs if t.param == 'S11')
    assert value_at('|S| (dB)', s11, 2e9) == __import__('pytest').approx(-20.0)
    assert value_at('VSWR', s11, 2e9) == __import__('pytest').approx(1.1 / 0.9)
    assert np.isnan(value_at('|S| (dB)', s11, 5e9)) and value_at('Smith chart', s11, 2e9) == __import__('pytest').approx(0.1)
    export_csv(tmp_path / 'x.csv', [s11, s21], '|S| (dB)', reflections=[s11])
    head = (tmp_path / 'x.csv').read_text().splitlines()[0]
    assert head == 'f_GHz,S11 openEMS dB,S21 openEMS dB,S11 openEMS re,S11 openEMS im'
    assert len(smith_grid()) > 10


def test_window_config_and_plots(tmp_path, monkeypatch):
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    import numpy as np
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))   # recent files in a scratch QSettings
    from PySide6.QtWidgets import QApplication
    from kicad2ems_gui.app import MainWindow
    from kicad2ems_gui.traces import load_traces
    app = QApplication.instance() or QApplication([])
    cfg = tmp_path / 'c.toml'
    cfg.write_text('# hello\nboard = "b.kicad_pcb"\nfmin = 1.0\n')
    w = MainWindow(str(cfg))
    assert w.setup.path == str(cfg) and not w.setup.dirty and w.windowTitle().startswith('c.toml -')
    w.setup.edits['fmax'][0].setText('7')
    assert w.setup.dirty and w.windowTitle().startswith('c.toml*')
    assert w.setup.save() and not w.setup.dirty and 'fmax = 7.0' in cfg.read_text() and '# hello' in cfg.read_text()
    assert str(cfg) in w.recent()
    f = np.linspace(1e9, 3e9, 11)
    S = np.full((11, 2, 2), 0.2 + 0j)
    _s2p(tmp_path / 'b_openems.s2p', f, S)
    sp = w.results.splot
    sp.set_traces(load_traces([('t', str(tmp_path / 'b_openems.s2p'))]))
    assert [t.param for t in sp.visible()] == ['S11', 'S21'] and [t.param for t in sp.reflections()] == ['S11']
    sp.add_marker(2e9)
    assert sp.table.rowCount() == 1 and sp.table.item(0, 1).text() == '-13.98 dB'
    sp.kind.setCurrentText('VSWR')
    assert sp.table.item(0, 1).text() == '1.500'
    sp.export_csv(str(tmp_path / 'e.csv'))
    assert (tmp_path / 'e.csv').exists()
    w.setup.dirty = False
    w.close()


@pytest.mark.parametrize('name, nports', [('branchline', 4), ('wilkinson', 3), ('steplpf', 2), ('stubnotch', 2),
                                          ('gcpw', 2), ('coupler', 4)])
def test_rf_examples_load(name, nports):
    """The RF example boards load: ports, the Wilkinson resistor, the coupler's two separate lines."""
    from kicad2ems.importers.kicad import KiCadBoard
    from kicad2ems.board import Board
    from k2e_fixtures import ROOT as root                             # the kicad2ems checkout: its examples
    path = os.path.join(root, 'examples', f'rf_{name}.toml')
    s = build_settings({}, path)
    m = Board(KiCadBoard(s.board), ground=s.ground, log=lambda *a: None)
    assert len(m.ports) == nports
    if name == 'wilkinson':
        assert len(m.parts) == 1 and abs(m.parts[0].R - 100) < 1e-9
    if name == 'coupler':
        assert len(m.copper['F.Cu']) == 2                           # the gap is open: two separate conductors


def test_gui_solver_boxes(tmp_path, monkeypatch):
    from kicad2ems_gui.runner import settings_values, solvers_from_form, save_config, extra_values, write_toml, FIELDS
    from kicad2ems.solvers.lines import fastsolve
    monkeypatch.setattr(fastsolve.shutil, 'which', lambda name: None)    # no qucsator: lines is scikit
    assert [k for k, *_ in FIELDS if k.startswith('solver:')] == ['solver:auto', 'solver:openems', 'solver:mom25d',
                                                                    'solver:gfdtd', 'solver:qucs', 'solver:scikit']
    p = tmp_path / 'c.toml'
    p.write_text('board = "b.kicad_pcb"\nsolvers = ["mom", "lines"]\n')
    vals = settings_values(str(p))
    assert not vals['solver:openems'] and vals['solver:mom25d'] and vals['solver:scikit'] and not vals['solver:qucs']
    assert 'solvers' not in extra_values(str(p))                    # the tick boxes own it
    s = solvers_from_form(dict(vals, **{'solver:openems': True}))   # openEMS ticked again
    assert not any(k.startswith('solver:') for k in s) and s['solvers'] == ['openems', 'mom25d', 'scikit']
    save_config(str(p), s, template=str(p))
    assert build_settings({}, str(p)).solver_plan()[0] == ['openems', 'mom25d', 'scikit']
    s = solvers_from_form(dict(vals, **{'solver:auto': True, 'solver:mom25d': False, 'solver:scikit': False}))
    assert 'solvers' not in s                                       # auto alone: the default, not written
    save_config(str(p), s, template=str(p))
    assert 'solvers' not in p.read_text() and build_settings({}, str(p)).solver_plan()[0] == ['auto']
    s = solvers_from_form(dict(vals, **{'solver:mom25d': False}))   # only the line model
    assert s['solvers'] == ['scikit']
    write_toml(tmp_path / 'r.toml', s)
    assert build_settings({}, str(tmp_path / 'r.toml')).solver_plan()[0] == ['scikit']
    none = solvers_from_form({k: False for k, *_ in FIELDS if k.startswith('solver:')})
    assert none['solvers'] == []                                    # none: the GUI says so
    p.write_text('board = "b.kicad_pcb"\nsolvers = ["auto"]\n')     # auto has a box of its own (and is the default)
    vals = settings_values(str(p))
    assert vals['solver:auto'] and not vals['solver:openems'] and 'solvers' not in solvers_from_form(vals)   # the default


def test_save_config_in_solver_tables(tmp_path):
    """A [solver.<name>] table: its short names are its settings; another tool's table is left alone."""
    from kicad2ems_gui.runner import settings_values, save_config, extra_values
    p = tmp_path / 'c.toml'
    p.write_text('board = "b.kicad_pcb"\n[solver.mom25d]\nport = "auto"  # MoM\ndmax = 0.4\n'
                 '[other]\nmom_port = "x"\n')
    vals = dict(settings_values(str(p)), **extra_values(str(p)))
    assert vals['mom_port'] == 'auto' and vals['mom_dmax'] == 0.4
    save_config(str(p), dict(vals, mom_port='lumped'), template=str(p))
    text = p.read_text()
    assert 'port = "lumped"' in text and '# MoM' in text and 'dmax = 0.4' in text and 'mom_port = "x"' in text
    s = build_settings({}, str(p))
    assert s.mom_port == 'lumped' and s.mom_dmax == 0.4


def test_system_panel(tmp_path):
    """The System panel: the machine as kicad2ems.sysinfo reports it, and a preview's estimates against it (a
    solver that cannot run here greyed, memory that does not fit marked)."""
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    import json
    from PySide6.QtWidgets import QApplication
    from kicad2ems_gui.systempanel import SystemPanel, fit_note
    from kicad2ems.sysinfo import info
    app = QApplication.instance() or QApplication([])
    p = SystemPanel()
    p.stop()                                                        # the panel's own check: not needed here
    sysinfo = info()
    assert {s['name'] for s in sysinfo['solvers']} >= {'mom25d', 'scikit'} and sysinfo['ram']['total'] > 0
    sysinfo['solvers'] = [dict(name='openems', label='openEMS', ok=False, what='no CSXCAD', consumes='board'),
                          dict(name='mom25d', label='mom25d', ok=True, what='0.6', consumes='board')]
    sysinfo['ram'] = dict(total=32.0, available=20.0)
    sysinfo['gpu'] = dict(device='GPU', backend='cupy', api='ROCm/HIP', free=16.0, total=17.0)
    p.set_info(sysinfo)
    assert p.solvers.topLevelItemCount() == 2
    est = dict(solvers=dict(openems=dict(seconds=60, gb=0.1, what='0.5 M cells'),
                            mom25d=dict(seconds=600, gb=30.0, gpu_gb=8.1, how='tiled', what='45,000 unknowns')))
    (tmp_path / 'b_run.json').write_text(json.dumps(dict(estimates=est)))
    assert p.load_estimates(str(tmp_path)) and p.est_tree.topLevelItemCount() == 2
    oems, mom = (p.est_tree.topLevelItem(i) for i in range(2))
    assert 'not available' in oems.text(4) and '~10 min' == mom.text(1)
    assert 'does not fit' in mom.text(2) and 'fits' in mom.text(3)
    assert fit_note(10, 20) == 'fits' and fit_note(18, 20) == 'tight' and not p.load_estimates(str(tmp_path / 'none'))


@pytest.fixture(scope='module')
def wilkinson_preview(tmp_path_factory):
    """A preview of the Wilkinson divider: its board, line model (<name>_lines.json), meshes and plots."""
    from kicad2ems.cli import main
    out = tmp_path_factory.mktemp('wilk')
    from k2e_fixtures import ROOT as root                             # the kicad2ems checkout: its examples
    assert main([os.path.join(root, 'examples', 'rf_wilkinson.toml'), '--preview', '--out', str(out),
                 '--solvers', 'openems,lines', '--no-report']) == 0
    return str(out)


def test_line_model_drawing(wilkinson_preview):
    """<name>_lines.json: every section with its points, layer height and Z0; paths as ids; the overlay's
    colours, hit test and description."""
    from kicad2ems import overlay as ov
    d = ov.load_lines(wilkinson_preview)
    assert d and d['format'] == 'kicad2ems-lines' and d['path'].endswith('_lines.json')
    els = d['elements']
    assert [e['id'] for e in els] == list(range(len(els)))
    assert all(len(e['pts']) >= 1 and e['z'] == pytest.approx(0.8) for e in els if e['layer'] == 'F.Cu')
    assert [p['port'] for p in d['paths']] == ['P1', 'P1', 'P2'] and all(p['ids'] for p in d['paths'])
    z0 = sorted({round(e['z0']) for e in els if e.get('z0') and e['kind'] == 'trace'})
    assert z0 == [49, 69]                                           # the 50 ohm feeds and the 70.7 ohm arms
    assert ov.reference(d) == 50.0 and ov.span(d) == pytest.approx(19.04, abs=0.05)
    arm = next(e for e in els if e['kind'] == 'trace' and e['z0'] > 60 and len(e['pts']) == 2)
    mid = np.mean(arm['pts'], 0)
    assert ov.nearest(els, mid[0], mid[1], 0.1) == arm['id']
    assert ov.nearest(els, 1e3, 1e3, 0.1) is None and ov.nearest(els, mid[0], mid[1], 0.1, layer='B.Cu') is None
    assert ov.z0_colour(50, 50, 10) == ov.MID and ov.z0_colour(None) == ov.MID
    assert ov.z0_colour(80, 50, 10) == pytest.approx(ov.HIGH) and ov.z0_colour(20, 50, 10) == pytest.approx(ov.LOW)
    assert 'Z0 69.0 Ω' in ov.describe(arm) and 'mm' in ov.describe(arm)
    seg = ov.plan_segments(next(iter(__import__('kicad2ems.meshes', fromlist=['find']).find(wilkinson_preview).values())),
                           (0, -20, 25, 0, 0, 0.8), 0.8)
    assert seg.shape[1] == 2 and len(seg) % 2 == 0 and len(seg) > 0


def test_viewer_sections_and_views(wilkinson_preview):
    """The viewer on a preview: the plan and the section list, one selection in every view; the views a folder
    has nothing for disabled."""
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from kicad2ems_gui import application
    from kicad2ems_gui.viewer import Viewer
    app = application()
    v = Viewer()
    assert v.load(wilkinson_preview)
    assert v.buttons['Plan'].isEnabled() and v.buttons['Images'].isEnabled() and not v.buttons['Cut'].isEnabled()
    assert v.plan.current_layer() == 'F.Cu' and v.plan.layer.count() == 2      # top first
    n = len([e for e in v.lines['elements'] if e['kind'] != 'coupling'])
    rows = sum(v.tree.topLevelItem(k).childCount() for k in range(v.tree.topLevelItemCount()))
    assert rows >= n and v.tree.topLevelItem(0).text(0) == 'P1 → P2'
    v.set_view('Plan')
    assert not v.side.isHidden()
    sec = v.tree.topLevelItem(0).child(1)
    sec.setSelected(True)                                           # the list: the plan and 3D follow
    i = sec.data(0, Qt_UserRole())
    assert v.plan.sel == i and v.volume.sel == i and 'Z0' in v.detail.text()
    v.plan.selected.emit(0)                                         # a click in the plan: the list follows
    assert v.tree.selectedItems()[0].data(0, Qt_UserRole()) == 0
    v.load(wilkinson_preview)                                       # the folder again: nothing selected
    assert v.detail.text().strip() == '' and v.plan.sel is None
    v.select(0)
    v.lines_on.setChecked(False)                                    # the overlay off: no list
    assert v.side.isHidden() and not v.plan.show_lines
    v.set_view('Images')
    assert v.side.isHidden()
    v.plan.mesh.setCurrentIndex(1)                                  # a solver's mesh on the layer
    assert v.plan.mesh.currentData() in ('openems', 'mom25d')


def Qt_UserRole():
    from PySide6.QtCore import Qt
    return Qt.UserRole


def test_results_subplots_and_layout(tmp_path, monkeypatch):
    """Subplots added and removed (Cartesian, Smith, polar), markers on all of them, antenna quantities when a
    folder has antenna results, the layout and the window's shape remembered by the next window."""
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    from PySide6.QtCore import QSettings
    from kicad2ems_gui import application
    from kicad2ems_gui.app import MainWindow
    from kicad2ems_gui.splot import default_layout
    from kicad2ems_gui.traces import load_traces
    app = application()
    QSettings('kicad2ems', 'gui').clear()
    w = MainWindow()
    sp = w.results.splot
    assert sp.layout_spec() == default_layout()
    f = np.linspace(1e9, 3e9, 11)
    S = np.zeros((11, 2, 2), complex)
    S[:, 0, 0], S[:, 1, 0] = 0.2, 0.9
    _s2p(tmp_path / 'b_openems.s2p', f, S)
    sp.set_traces(load_traces([('t', str(tmp_path / 'b_openems.s2p'))]))
    polar = sp.add_subplot('Polar')
    assert sp.layout_spec()[-1] == 'Polar:S (polar)' and polar.option.count() == 1   # no far field: S only
    sp.add_subplot('Cartesian', 'Phase (deg)')
    assert sp.s_kinds() == ['|S| (dB)', 'Phase (deg)']
    m = sp.add_marker(2e9)
    assert set(m['items']) == {id(p) for p in sp.subplots}          # on every plot
    assert sp.table.columnCount() == 1 + 2 * 2 + 1                  # f, |S| and phase of S11, S21, S11 on Smith
    m['items'][id(sp.subplots[0])][0].setValue(2.4)                  # dragged on one plot: moved on the others
    assert m['f'] == pytest.approx(2.4e9) and m['items'][id(sp.subplots[3])][0].value() == pytest.approx(2.4)
    sp.remove_subplot(polar)
    assert 'Polar:S (polar)' not in sp.layout_spec() and len(sp.subplots) == 3
    res = dict(rows=[dict(f=f0, D_dbi=5.0, G_dbi=3.0, Grealized_dbi=2.5, eff=0.6, Prad=0.6, Pinc=1.0)
                     for f0 in (1e9, 2e9, 3e9)], f_pattern=2e9)
    th, ph = np.arange(0, 181, 5.0), np.arange(0, 360, 5.0)
    sph = dict(freq=np.array([2e9]), theta=th, phi=ph, e_norm=np.ones((1, len(ph), len(th))), dmax=np.array([2.0]))
    sp.set_antenna(res, sph)
    assert sp.subplots[0].option.findText('Gain (dBi)') >= 0
    cuts = sp.add_subplot('Polar', 'Far-field cuts')
    assert cuts.mode == 'Far-field cuts' and cuts.freq.count() == 1 and cuts.freq.isVisibleTo(cuts)
    sp.subplots[0].option.setCurrentText('Gain (dBi)')
    assert 'gain' in [sp.table.horizontalHeaderItem(c).text() for c in range(sp.table.columnCount())]
    spec = sp.layout_spec()
    w.results._mode = 'sparams'
    w.results._save_layout()
    w.resize(760, 590)                                              # fits the offscreen screen (800 x 800)
    w.setup.dirty = False
    w.close()
    w2 = MainWindow()                                               # the next window: the same plots and size
    assert w2.results.splot.layout_spec() == spec and (w2.width(), w2.height()) == (760, 590)
    first = w2.results.splot.subplots[0]
    assert first.mode == '|S| (dB)'                                 # no antenna results here: |S| for now
    w2.results.splot.set_antenna(res, sph)
    assert first.mode == 'Gain (dBi)'                               # and the gain once there are
    w2.setup.dirty = False
    w2.close()
    app.processEvents()


def test_meters(tmp_path):
    """The status bar's readings: system RAM from /proc/meminfo, a process tree's memory, the GPU tools' output."""
    from kicad2ems_gui import meters
    mi = tmp_path / 'meminfo'
    mi.write_text('MemTotal:       16000000 kB\nMemFree:  1 kB\nMemAvailable:    4000000 kB\n')
    used, total = meters.ram(str(mi))
    assert total == pytest.approx(16.384) and used == pytest.approx(12.288)
    assert meters.ram(str(tmp_path / 'none')) is None or len(meters.ram(str(tmp_path / 'none'))) == 2   # sysconf
    if os.path.isdir('/proc/self'):
        assert meters.tree_rss(os.getpid()) > 0.01                  # this test process
    assert meters.tree_rss(None) is None and meters.tree_rss(2 ** 30) is None
    assert meters.parse_gpu('nvidia-smi', '2048, 16384, RTX\n') == [pytest.approx((2.147483648, 17.179869184))]
    rocm = 'WARNING: x\n{"card0": {"VRAM Total Memory (B)": "17163091968", "VRAM Total Used Memory (B)": "1000000000"}}'
    assert meters.parse_gpu('/opt/rocm/bin/rocm-smi', rocm) == [pytest.approx((1.0, 17.163091968))]
    assert meters.parse_gpu('nvidia-smi', 'garbage') == [] and meters.duration(263) == '~4 min'


def test_estimate_follows_the_solvers():
    """The toolbar's estimate: auto takes the fastest solver that can run and fits; named solvers add up; auto adds
    no full-wave solver beside a named one (as the pipeline); stale settings and a misfit are marked."""
    from kicad2ems_gui.meters import estimate
    est = dict(solvers=dict(openems=dict(seconds=818, gb=0.05), mom25d=dict(seconds=264, gb=1.3, gpu_gb=0.8)))
    e = estimate(est, {})                                           # the default: auto
    assert [r[0] for r in e['rows']] == ['mom25d'] and e['rows'][0][4] and e['gpu_gb'] == 0.8
    assert estimate(est, {}, usable={'openems'})['rows'][0][0] == 'openems'          # mom25d can't run here
    assert estimate(est, {}, ram_avail=1.0)['rows'][0][0] == 'openems'               # mom25d doesn't fit
    both = estimate(est, dict(solvers=['openems', 'mom25d', 'scikit']))
    assert both['seconds'] == 818 + 264 and both['gb'] == 1.3 and not any(r[4] for r in both['rows'])
    named = estimate(est, dict(solvers=['auto', 'gfdtd']))          # a named full-wave solver: auto adds none
    assert named is None
    assert estimate(est, dict(solvers=['scikit'])) is None and estimate(None, {}) is None
    assert not estimate(est, dict(solvers=['mom25d']), ram_avail=1.0)['fits']
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from kicad2ems_gui import application
    from kicad2ems_gui.app import MainWindow
    app = application()
    w = MainWindow()
    w.system.stop()
    assert w.est_btn.text().startswith('No estimate')
    w.setup.set_values(dict(board='b.kicad_pcb'))
    w.new_estimates(est)
    assert w.est_btn.text().startswith('~4 min · 1.3 GB · GPU 0.8 GB') and '(auto)' in w.est_btn.text()
    assert 'changed' not in w.est_btn.text()
    w.setup.solver_boxes['openems'].setChecked(True)                # a named solver: auto's choice gives way
    assert w.est_btn.text().startswith('~14 min') and 'changed' not in w.est_btn.text()
    w.setup.edits['out'][0].setText('elsewhere')                   # where results go: the same estimate
    assert 'changed' not in w.est_btn.text()
    w.setup.edits['fmax'][0].setText('9')                           # another setting: the estimate is stale
    assert w.est_btn.text().endswith('· changed')
    w.setup.dirty = False                                           # (else New asks to save first)
    w.setup.new()                                                   # another board: no estimate
    assert w.est_btn.text().startswith('No estimate')
    assert w.meters.ram.format().startswith('RAM ') and not w.meters.run.isVisible()
    w.setup.dirty = False
    w.close()
    app.processEvents()


def test_line_model_relief(wilkinson_preview):
    """The 3D line model: sections as slabs at their width, taller for a higher Z0."""
    from kicad2ems import overlay as ov
    d = ov.load_lines(wilkinson_preview)
    arm = next(e for e in d['elements'] if e['kind'] == 'trace' and e['z0'] > 60 and len(e['pts']) == 2)
    g = ov.section_polygon(arm)
    assert g.area == pytest.approx(arm['w'] * arm['length'], rel=1e-6)          # its width, its length
    assert ov.relief(69, 49, 69) == 1.0 and ov.relief(49, 49, 69) == 0.25 and ov.relief(None, 49, 69) == 0.25
    assert ov.relief(59, 49, 69) == pytest.approx(0.625) and ov.relief(50, 50, 50) == pytest.approx(0.625)
    pytest.importorskip('PySide6')
    pytest.importorskip('OpenGL')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from kicad2ems_gui import application
    from kicad2ems_gui.volumetab import VolumeTab
    app = application()
    v = VolumeTab()
    if v.gl is None:
        pytest.skip('no OpenGL')
    v.set_lines(d)
    assert v.load(wilkinson_preview)
    slabs = [k for k in v.items if k.startswith('ln') and k != 'ln_rims']
    assert len(slabs) >= 20 and 'ln_rims' in v.items and v.relief.value() == pytest.approx(0.38)
    tall = v.items[f"ln{arm['id']}"].opts['meshdata'].vertexes()[:, 2].max()
    feed = next(e for e in d['elements'] if e['kind'] == 'trace' and e['z0'] < 55 and len(e['pts']) == 2)
    low = v.items[f"ln{feed['id']}"].opts['meshdata'].vertexes()[:, 2].max()
    assert tall - low == pytest.approx(0.75 * 0.38, abs=1e-3)       # the step in Z0 is a step in height
    v.lines_on.setChecked(False)
    assert not any(k.startswith('ln') for k in v.items)


def test_parts_in_the_viewer(wilkinson_preview):
    """The Wilkinson's resistor as an 0805 chip: green in 3D with its value, outlined in the plan."""
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from kicad2ems_gui import application
    from kicad2ems_gui.viewer import Viewer
    from kicad2ems_gui.volumetab import _value
    app = application()
    v = Viewer()
    assert v.load(wilkinson_preview)
    r1 = v.plan.board['parts'][0]
    assert r1['ref'] == 'R1' and r1['package'] == '0805' and _value(r1) == '100 Ω'
    assert _value(dict(R=0.4, L=2.7e-8, C=None), main=True) == '27 nH' and _value(dict(R=0.4, L=2.7e-8, C=None)) == \
        '0.4 Ω + 27 nH'
    v.set_view('Plan')
    assert any(isinstance(it, __import__('pyqtgraph').TextItem) and it.toPlainText() == 'R1' for it in v.plan._items)
    vol = v.volume
    if vol.gl is None:
        return
    assert not vol.parts_on.isHidden() and {'part0_0', 'part0_1', 'part0_2', 'part0_label'} <= set(vol.items)
    assert vol.items['part0_label'].text == 'R1 100 Ω'
    strip = next(e['id'] for e in v.lines['elements'] if e['kind'] == 'part')
    assert f"ln{strip}" not in vol.items                            # no line-model strip inside the chip
    vol.parts_on.setChecked(False)
    assert not any(k.startswith('part') for k in vol.items) and f"ln{strip}" in vol.items


def test_run_folders(tmp_path):
    """Each GUI run in a folder of its own (<board>_<date>_<time>), a preview in <board>_preview; a board's runs
    are only its own, the newest first, and only those that wrote a summary."""
    import datetime
    from kicad2ems_gui.runfolders import run_dir, preview_dir, runs, board_name
    base = str(tmp_path)
    assert board_name('/x/rf_coupler.kicad_pcb') == 'rf_coupler' and board_name('a/b_board.json') == 'b'
    t = datetime.datetime(2026, 10, 13, 14, 15, 2)
    d1 = run_dir(base, 'x/rf_coupler.kicad_pcb', t)
    d2 = run_dir(base, 'x/rf_coupler.kicad_pcb', t + datetime.timedelta(minutes=5))
    other = run_dir(base, 'x/rf_coupler2.kicad_pcb', t)              # another board, a name that starts the same
    assert os.path.basename(d1) == 'rf_coupler_20261013_141502'
    assert preview_dir(base, 'x/rf_coupler.kicad_pcb') == os.path.join(base, 'rf_coupler_preview')
    for d, solvers in ((d1, ['openems']), (d2, ['mom25d', 'qucs']), (other, ['openems'])):
        os.makedirs(d)
        name = os.path.basename(d).rsplit('_', 2)[0]
        json.dump(dict(solvers=solvers), open(os.path.join(d, f"{name}_run.json"), 'w'))
    os.makedirs(run_dir(base, 'x/rf_coupler.kicad_pcb', t + datetime.timedelta(hours=1)))   # stopped: no summary
    rs = runs(base, 'x/rf_coupler.kicad_pcb')
    assert [d for d, _ in rs] == [d2, d1]
    assert rs[0][1] == '2026-10-13 14:20:02 (mom25d, qucs)'


def test_solver_sections(tmp_path):
    """Each solver's settings in a section of its own (openEMS's in Mesh, Run and Field dumps sub-sections), the
    shared ones apart (Antenna; the dump settings both use under Output), qucsator not a board's setting (the
    Solvers and hardware window); a section greyed while none of its solvers is ticked."""
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from kicad2ems_gui import application
    from kicad2ems_gui.app import MainWindow
    app = application()
    w = MainWindow()
    st = w.setup
    if not any(b.isChecked() for b in st.solver_boxes.values()) and not st.edits['solver:auto'][0].isChecked():
        assert not st.parents['FDTD'][0].isEnabled() and not st.sections['mom25d'].isEnabled()   # first launch
        assert not st.edits['ff_freq'][0].isEnabled()
    assert st.group_of['res'] == 'FDTD/Mesh' and st.group_of['mom_dmax'] == 'mom25d'
    assert st.group_of['excite'] == 'Solvers' and st.group_of['ff_freq'] == 'Output' and 'Antenna' not in st.sections
    assert st.group_of['dump_port'] == st.group_of['dump_animate'] == 'Output'
    assert 'qucsator' not in st.group_of and 'Line model' not in st.sections and 'Field dumps' not in st.sections
    assert 'mom_dmax' not in [k for k, g in st.group_of.items() if g == 'Solvers']
    assert w.system.qucsator.text() == ''                           # the Solvers window's, empty: the PATH's
    st.set_values(dict(board='b.kicad_pcb', solvers=['mom25d']))
    oems, mom = st.parents['FDTD'][0], st.sections['mom25d']
    assert not oems.isEnabled() and mom.isEnabled() and 'openEMS' in oems.toolTip() and 'gfdtd' in oems.toolTip()
    from kicad2ems_gui.runner import SECTION_TITLES, SECTION_ORDER    # built from the plugins installed
    assert SECTION_TITLES['FDTD'] == 'FDTD (openEMS, gfdtd)' and SECTION_ORDER[3:5] == ['FDTD', 'mom25d']
    assert st.sections['Output'].isEnabled() and not st.edits['ff_freq'][0].isEnabled()    # S-parameters: no pattern
    st.edits['mode'][0].setCurrentText('antenna')
    assert st.edits['ff_freq'][0].isEnabled() and st.field_labels['ff_freq'].isEnabled()
    st.solver_boxes['openems'].setChecked(True)
    assert oems.isEnabled()
    st.set_values(dict(board='b.kicad_pcb'))                        # auto: openEMS, mom25d and the line model may run
    assert oems.isEnabled() and mom.isEnabled()
    w.hide()
    app.processEvents()


def test_solvers_window_saves_qucsator(tmp_path, monkeypatch):
    """The Solvers and hardware window's qucsator field: saved for the user (sitecfg), then the solvers checked
    again; emptied, the PATH's again."""
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    from kicad2ems import sitecfg
    monkeypatch.setattr(sitecfg, '_cache', None)
    from kicad2ems_gui import application
    from kicad2ems_gui.systempanel import SystemPanel
    app = application()
    p = SystemPanel()
    p.stop()
    checks = []
    monkeypatch.setattr(p, 'refresh', lambda: checks.append(1))
    p.qucsator.setText('/opt/qucs/bin/qucsator_rf')
    p._save_programs()
    assert sitecfg.get('qucsator') == '/opt/qucs/bin/qucsator_rf' and checks == [1]
    p._save_programs()                                              # unchanged: no new check
    assert checks == [1]
    p.qucsator.setText('')
    p._save_programs()
    assert sitecfg.get('qucsator') is None and checks == [1, 1]
    p.openems_venv.setText('/opt/openems/venv')                     # the openEMS environment, the same way
    p._save_programs()
    assert sitecfg.get('openems_venv') == '/opt/openems/venv' and sitecfg.get('qucsator') is None and checks == [1, 1, 1]
    monkeypatch.setattr(sitecfg, '_cache', None)


def test_beam_steering_bar(tmp_path, monkeypatch):
    """An antenna result with each port's far field kept: the Results page's Beam steering bar recombines them for
    a phase step (the plots' antenna results follow), Animate steps it, a drive that does not parse is shown."""
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    from kicad2ems import phased
    from kicad2ems_gui import application
    from kicad2ems_gui.app import MainWindow
    from test_phased import two_sources
    app = application()
    data, _ = two_sources()
    phased.save(tmp_path / 'b_mom25d_array.npz', **data)
    c = phased.combine(data, data['drive'])
    np.savez_compressed(tmp_path / 'b_mom25d_sphere.npz', **c['sphere'])
    res = dict(match=dict(f_res=2.45e9, s11_db=-20.0, zin=[50.0, 0.0], bw10=None), rows=c['rows'],
               f_pattern=2.45e9, port='P1@0, P2@0', solver='mom25d', sphere_file='b_mom25d_sphere.npz',
               array_file='b_mom25d_array.npz', drive=['P1@0', 'P2@0'], peak=c['peak'])
    (tmp_path / 'b_mom25d_antenna.json').write_text(json.dumps(res))
    w = MainWindow()
    assert w.results.load_antenna(str(tmp_path))
    bar = w.results.steer
    assert bar.isVisibleTo(w.results) and bar.drive.text() == 'P1@0, P2@0' and 'θ 0°' in bar.readout.text()
    got = []
    bar.steered.connect(lambda r, s: got.append(r))
    bar.spin.setValue(60)
    assert got and got[-1]['drive'] == ['P1@0', 'P2@60'] and got[-1]['peak']['theta'] > 10
    assert w.results.splot.antenna['peak'] == got[-1]['peak']        # the plots show the steered drive
    vb = getattr(w.volume, 'steer', None)                            # the 3D view's bar (with PyOpenGL)
    if vb is not None:
        assert vb.data is not None and vb.spin.value() == 60 and vb.readout.text() == bar.readout.text()
        vb.spin.setValue(-30)                                        # steered from the 3D view: this page follows
        assert bar.spin.value() == -30 and w.results.splot.antenna['drive'] == ['P1@0', 'P2@-30']
        vb.anim.setChecked(True)                                     # one timer runs, both buttons show it
        assert vb.timer.isActive() and bar.anim.isChecked() and not bar.timer.isActive()
        bar.anim.setChecked(False)
        assert not vb.timer.isActive() and not vb.anim.isChecked()
        bar.spin.setValue(60)
    bar.anim.setChecked(True)
    bar._frame()
    assert bar.spin.value() == 63
    bar.anim.setChecked(False)
    bar.drive.setText('P7@0')
    bar.update()
    assert 'no port' in bar.readout.text()
    bar.reset.click()
    assert bar.spin.value() == 0 and bar.drive.text() == 'P1@0, P2@0'
    assert not w.results.load_antenna(None) and not bar.isVisibleTo(w.results)
    w.hide()


def test_trace_colours_and_styles(tmp_path, monkeypatch):
    """Every trace its own colour, every source its own line style (S11 of two solvers had shared both, an added
    folder's traces openEMS's solid line); the user's colour / style / width from the trace list, remembered."""
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    from PySide6.QtCore import QSettings
    from kicad2ems_gui import application
    from kicad2ems_gui.splot import SPlot
    from kicad2ems_gui.traces import load_traces
    app = application()
    QSettings('kicad2ems', 'gui').clear()
    f = np.linspace(1e9, 3e9, 11)
    S = np.zeros((11, 2, 2), complex)
    S[:, 0, 0], S[:, 1, 0] = 0.2, 0.9
    for name in ('b_openems', 'b_mom25d', 'b_qucs', 'b_scikit'):
        _s2p(tmp_path / f'{name}.s2p', f, S)
    tr = load_traces([('t', str(tmp_path / f'{n}.s2p')) for n in ('b_openems', 'b_mom25d', 'b_qucs', 'b_scikit')])
    extra = load_traces([('t', str(tmp_path / 'b_openems.s2p'))])
    for t in extra:
        t.source = f"other run: {t.source}"
    sp = SPlot()
    sp.set_traces(tr + extra)
    looks = [sp.look(t) for t in sp.traces]
    assert len({c for c, _, _ in looks}) == len(looks)               # a colour each
    s11 = [t for t in sp.traces if t.param == 'S11']
    assert len({sp.look(t)[1] for t in s11}) == len(s11) == 5        # a style per source, the added folder too
    sp.set_look([s11[0]], color='#000000', style='dot', width=3)
    assert sp.look(s11[0]) == ('#000000', 'dot', 3) and sp._pen(s11[0]).width() == 3
    assert not sp.tree.topLevelItem(0).child(0).icon(0).isNull()     # the line beside its name
    sp2 = SPlot()                                                    # remembered
    sp2.set_traces(tr + extra)
    assert sp2.look(sp2.traces[0]) == ('#000000', 'dot', 3)
    sp2.set_look([sp2.traces[0]], color=None, style=None, width=None)
    assert sp2.look(sp2.traces[0]) == looks[0]
    QSettings('kicad2ems', 'gui').clear()


def test_filter_command_line():
    """The Filter page's settings as dfsynth's command line: empty fields left to dfsynth, flags only when set,
    the validation only when asked for."""
    from kicad2ems_gui.filtertab import filter_argv
    vals = dict(type='bandpass', topology='interdigital', f0='5G', bw='500M', order=None, ripple=None, h=0.8,
                allow_fab_violations=True, no_calibrate=False, out='/x/idg', validate='gfdtd', em_tune=3,
                k2e_args='--fine 0.03')
    a = filter_argv(vals)
    assert a[:3] == ['-u', '-m', 'dfsynth'] and a[a.index('--f0') + 1] == '5G' and a[a.index('--h') + 1] == '0.8'
    assert '--allow-fab-violations' in a and '--no-calibrate' not in a and '--order' not in a
    assert a[a.index('--em-tune') + 1] == '3' and a[a.index('--k2e-args') + 1] == '--fine 0.03'
    b = filter_argv(vals, validate=False)
    assert '--validate' not in b and '--em-tune' not in b and '--k2e-args' not in b


def test_filter_page(tmp_path):
    """dfsynth (the checkout's) designs a filter; the page reads what it wrote (design, layout, model response)
    and shows it; the main window has the page."""
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from kicad2ems_gui import filtertab as ft
    ds = ft.dfsynth_module()
    if ds is None:
        pytest.skip('no dfsynth')
    from dfsynth.cli import main as dfsynth
    base = str(tmp_path / 'lpf')
    assert dfsynth(['--type', 'lowpass', '--topology', 'stepped', '--f0', '2G', '--substrate', 'RO4003C-0.813',
                    '-o', base]) == 0
    res = ft.load_design(base)
    assert res and res['model'][1].shape[1:] == (2, 2) and res['em'] == [] and os.path.exists(res['toml'])
    geo = res['design']['geometry']
    assert geo['polys'] and len(geo['ports']) == 2
    from PySide6.QtWidgets import QApplication
    from kicad2ems_gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    assert 'Filter' in w.docks and w.filter.ds is not None
    page = w.filter
    page.set_values(dict(type='lowpass', topology='radial', f0='2G', out=base))
    v = page.values()
    assert v['topology'] == 'radial' and v['bw'] is None and v['f0'] == '2G'
    assert page.w['stub_angle'].isEnabled() and not page.w['zlow'].isEnabled()
    page.show_result(res)
    assert page.table.rowCount() == len(res['design']['elements']) and page.open_btn.isEnabled()
    assert 'lowpass / stepped' in page.summary.toPlainText()
    # problems go to the log, in red, counted on its tab; the rest plain
    lv, last = [], None
    for line in ['g = 1.0', '  note: order 3 Chebyshev needs unequal terminations', '',
                 'dfsynth: the design cannot be made as asked:', '  gap 0.05 mm is below the 0.1 mm minimum',
                 'wrote x.kicad_pcb', 'Traceback (most recent call last):', '  File "x.py", line 1',
                 'ValueError: no', 'usage: dfsynth', 'dfsynth: error: unrecognized arguments: --x',
                 'kicad2ems (gfdtd):', '    note: P2 not excited', '    WARNING: the run stopped at --max-steps']:
        last = line_level = ft.line_level(line, last)
        lv.append(line_level)
    assert lv == [None, 'warn', None, 'error', 'error', None, 'error', 'error', 'error', None, 'error', None, None, 'warn']
    assert ft.PROGRESS.match('    P1: step 36600, energy -3.2 dB, 14 s') and ft.PROGRESS.match('    mom25d: 40% (24 f')
    page.clear_log()
    page.say('fine')
    page.say('a warning', 'warn')
    assert page.tabs.tabText(page.tabs.indexOf(page.log)) == 'Log (1 warning)'
    page.say('broken', 'error')
    assert page.tabs.tabText(page.tabs.indexOf(page.log)) == 'Log (1 error, 1 warning)'
    assert page.tabs.currentWidget() is page.log and '⚠ a warning' in page.log.toPlainText()
    page.clear_log()
    assert page.tabs.tabText(page.tabs.indexOf(page.log)) == 'Log'
    w.setup.dirty = False
    w.close()


def test_new_page_docks_into_an_older_layout(monkeypatch, tmp_path):
    """A layout saved before a page existed (the Filter page): the page comes up tabbed with the others, not
    floating; and the toolbar opens it."""
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from kicad2ems_gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    QSettings('kicad2ems', 'gui').clear()
    w = MainWindow()
    w.docks['Filter'].setFloating(True)                             # as Qt leaves a dock the saved state lacks
    w.setup.dirty = False
    w.close()                                                       # saves the layout, the page floating
    QSettings('kicad2ems', 'gui').setValue('work/pages', ['Viewer', 'Run', 'Results'])   # saved before it existed
    w = MainWindow()
    assert not w.docks['Filter'].isFloating()
    assert w.docks['Filter'] in w.work.tabifiedDockWidgets(w.docks['Viewer'])
    w.acts['Filter'].trigger()
    assert w.docks['Filter'].isVisibleTo(w)
    if w.filter.ds is not None:
        assert w.filter.w['substrate'].findText('FR4-1.6') >= 0 and w.filter.design_btn.isEnabled()
    w.setup.dirty = False
    w.close()
    QSettings('kicad2ems', 'gui').clear()


def test_beam_steering_bar_2d(tmp_path, monkeypatch):
    """A 4 x 4 array with a feed per element: the run's grid fills the Grid field, an X step per column and a Y step
    per row steer the beam in two planes, the phase map shows each element, Circle animates both, the 3D view's
    bar follows; a bad grid is shown, an empty one goes back to a line of ports."""
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    from kicad2ems import phased
    from kicad2ems_gui import application
    from kicad2ems_gui.app import MainWindow
    from test_phased import grid_sources
    app = application()
    data, k0, d = grid_sources()
    phased.save(tmp_path / 'a_mom25d_array.npz', **data)
    c = phased.combine(data, data['drive'])
    np.savez_compressed(tmp_path / 'a_mom25d_sphere.npz', **c['sphere'])
    drive = phased.format_drive(data['drive'], data['ports'])
    res = dict(match=dict(f_res=2.45e9, s11_db=-20.0, zin=[50.0, 0.0], bw10=None), rows=c['rows'],
               f_pattern=2.45e9, port=', '.join(drive), solver='mom25d', sphere_file='a_mom25d_sphere.npz',
               array_file='a_mom25d_array.npz', drive=drive, grid='4x4', peak=c['peak'])
    (tmp_path / 'a_mom25d_antenna.json').write_text(json.dumps(res))
    w = MainWindow()
    assert w.results.load_antenna(str(tmp_path))
    bar = w.results.steer
    assert bar.grid.text() == '4x4' and bar.spin_y.isVisibleTo(bar) and bar.map.isVisibleTo(bar)
    assert len(bar.map.cells) == 16 and bar.map.cells[5][:3] == (1, 1, 'P6')
    got = []
    bar.steered.connect(lambda r, s: got.append(r))
    bar.spin.setValue(40)
    bar.spin_y.setValue(-40)
    r = got[-1]
    assert r['grid'] == '4x4' and 'P6@0' in r['drive'] and 'P2@40' in r['drive'] and 'P5@-40' in r['drive']
    th, ph = np.radians(r['peak']['theta']), np.radians(r['peak']['phi'])
    assert abs(np.sin(th) * np.cos(ph) + np.radians(40) / (k0 * d)) < 0.05
    assert abs(np.sin(th) * np.sin(ph) - np.radians(40) / (k0 * d)) < 0.05
    assert abs({c[2]: c[3] for c in bar.map.cells}['P16']) < 1e-6   # 3 x 40 - 3 x 40
    assert 'worst' in bar.readout.text()                             # 16 active reflections: the range
    vb = getattr(w.volume, 'steer', None)
    if vb is not None:
        assert vb.grid.text() == '4x4' and vb.spin_y.value() == -40
        vb.spin_y.setValue(20)
        assert bar.spin_y.value() == 20
    bar.anim_mode.setCurrentIndex(2)                                 # Circle: both steps round
    bar.anim.setChecked(True)
    x0, y0 = bar.spin.value(), bar.spin_y.value()
    for _ in range(10):
        bar._frame()
    assert (bar.spin.value(), bar.spin_y.value()) != (x0, y0)
    assert abs(np.hypot(bar.spin.value(), bar.spin_y.value()) - np.hypot(x0, y0)) < 2
    bar.anim.setChecked(False)
    bar.grid.setText('P1:0')
    bar.update()
    assert 'expected' in bar.readout.text()
    bar.grid.setText('')
    bar.update()
    assert not bar.spin_y.isVisibleTo(bar) and bar.label_x.text() == 'Phase step' and 'grid' not in got[-1]
    bar.reset.click()
    assert bar.grid.text() == '4x4' and bar.spin.value() == 0 and bar.spin_y.value() == 0
    bar.taper.setCurrentIndex(1)                                     # Taylor: the corners weakest
    assert bar.sll.isEnabled() and bar.taper_spec() == 'taylor:25'
    r = got[-1]
    amps = {c[2]: c[5] for c in bar.map.cells}
    assert amps['P1'] < amps['P2'] < 1 and amps['P6'] == pytest.approx(1) and 'Taylor' in bar.readout.text()
    assert 'P1=0.' in ', '.join(r['drive']) and r['peak']['gain_dbi'] < res['peak']['gain_dbi']
    if vb is not None:
        assert vb.taper_spec() == 'taylor:25'
    bar.taper.setCurrentIndex(3)                                     # cosine: no level to set
    assert not bar.sll.isEnabled() and bar.taper_spec() == 'cosine'
    bar.set_data(dict(res, drive_base=drive, taper='chebyshev:30', steer=[20.0, -10.0]), bar.data)
    assert bar.taper_spec() == 'chebyshev:30' and (bar.spin.value(), bar.spin_y.value()) == (20, -10)
    assert bar.drive.text() == ', '.join(drive)                      # the run's untapered drive, not tapered twice


def test_beam_steering_aim(tmp_path, monkeypatch):
    """A result that kept the ports' places (three feeds in a triangle): Aim points the beam at θ, φ, Animate
    sweeps θ or turns φ, Reset gives the run's aim back; a result without places has no Aim."""
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    from kicad2ems import phased
    from kicad2ems_gui import application
    from kicad2ems_gui.steering import SteeringBar
    from test_phased import placed_sources
    application()
    data = placed_sources({'P1': (0.0, 0.0), 'P2': (61.2, 0.0), 'P3': (30.6, 53.0)})
    c = phased.combine(data, data['drive'])
    drive = phased.format_drive(data['drive'], data['ports'])
    res = dict(rows=c['rows'], peak=c['peak'], drive=drive, drive_base=drive, taper='uniform', steer=[0.0, 0.0],
               aim=[25.0, 45.0])
    bar = SteeringBar()
    got = []
    bar.steered.connect(lambda r, s: got.append(r))
    bar.set_data(res, data)
    assert bar.aim_row.isVisibleTo(bar) and bar.aim.isChecked() and (bar.theta.value(), bar.phi.value()) == (25, 45)
    assert [bar.anim_mode.itemText(i) for i in range(bar.anim_mode.count())] == ['θ', 'φ']
    bar.phi.setValue(200)
    pk = got[-1]['peak']
    assert abs(pk['theta'] - 25) <= 2 and abs(pk['phi'] - 200) <= 4 and 'aimed at θ 25°' in bar.readout.text()
    assert 'aim' not in got[-1]                                      # the drive holds it all now
    bar.anim.setChecked(True)
    t0 = bar.theta.value()
    for _ in range(5):
        bar._frame()
    assert bar.theta.value() != t0 and 0 <= bar.theta.value() <= 60
    bar.anim_mode.setCurrentIndex(1)                                 # φ round, θ kept
    t1, p1 = bar.theta.value(), bar.phi.value()
    bar._frame()
    assert bar.theta.value() == t1 and bar.phi.value() != p1
    bar.anim.setChecked(False)
    bar.aim.setChecked(False)                                        # off: the drive's own phases, broadside
    assert got[-1]['peak']['theta'] == 0 and not bar.anim_mode.isVisibleTo(bar)
    bar.reset.click()
    assert bar.aim.isChecked() and (bar.theta.value(), bar.phi.value()) == (25, 45)
    old = {k: v for k, v in data.items() if k != 'pos'}               # a result from before the places were kept
    bar.set_data(dict(res, aim=None), old)
    assert not bar.aim_row.isVisibleTo(bar) and not bar.aiming()
    from PySide6.QtWidgets import QApplication
    bar.steered.disconnect()                                         # a parentless bar: gone before the interpreter
    bar.deleteLater()
    QApplication.processEvents()


def test_mixed_mode_names():
    """A file with differential pairs (kicad2ems's P1d, P1c ports) names its traces by mode and pair: Sdd21, Scd21,
    and s for a single-ended port among them; a file without pairs keeps S21."""
    from kicad2ems_gui.traces import Trace, modes
    names = ['P1d', 'P1c', 'P2d', 'P2c', 'P3']
    assert modes(names) == [('d', 1), ('c', 1), ('d', 2), ('c', 2), ('s', 3)]
    assert modes(['IN', 'OUT']) is None and modes(None) is None and modes(['Pd', 'Q']) is None
    f, s = np.array([1e9, 2e9]), np.zeros(2)
    tr = lambda i, j, nm=names: Trace('mom25d', i, j, f, s, list(nm))
    assert [tr(2, 0).param, tr(3, 0).param, tr(0, 0).param, tr(4, 0).param, tr(2, 4).param] == \
        ['Sdd21', 'Scd21', 'Sdd11', 'Ssd31', 'Sds23']
    assert tr(2, 0).title == 'Sdd21 (P2d ← P1d)' and tr(1, 0, ['IN', 'OUT']).param == 'S21'


def test_difference_plot(tmp_path, monkeypatch):
    """Two solvers' results: the Cartesian plot offers Δ|S| and |ΔS| against a chosen solver, and draws each other
    solver's checked trace as its difference from the reference's same S; with one solver there is none."""
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    from kicad2ems_gui import application
    from kicad2ems_gui.splot import SPlot
    from kicad2ems_gui.traces import DIFF_KINDS, load_traces, difference, counterpart
    application()
    f = np.linspace(1e9, 3e9, 11)
    _s2p(tmp_path / 'b_openems.s2p', f, np.full((11, 2, 2), 0.2 + 0j))
    _s2p(tmp_path / 'b_mom25d.s2p', f, np.full((11, 2, 2), 0.25 + 0j))
    sp = SPlot()
    sp.set_traces(load_traces([('t', str(tmp_path / 'b_openems.s2p'))]))
    opts = lambda: [sp.subplots[0].option.itemText(i) for i in range(sp.subplots[0].option.count())]
    assert not set(DIFF_KINDS) & set(opts())                         # one solver: nothing to compare
    trs = load_traces([('a', str(tmp_path / 'b_openems.s2p')), ('b', str(tmp_path / 'b_mom25d.s2p'))])
    sp.set_traces(trs)
    assert set(DIFF_KINDS) <= set(opts())
    plot = sp.subplots[0]
    plot.option.setCurrentText(DIFF_KINDS[0])
    assert plot.ref.isVisibleTo(plot) and plot.reference == 'openEMS'
    import pyqtgraph as pg
    lines = lambda: [c for c in plot.pw.listDataItems() if isinstance(c, pg.PlotDataItem)]   # not the cursor dot
    curves = lines()
    assert len(curves) == 2 and all(np.allclose(c.yData, 20 * np.log10(0.25 / 0.2)) for c in curves)
    m21 = next(t for t in trs if t.source == 'mom25d' and t.param == 'S21')
    _, y = difference(DIFF_KINDS[1], m21, counterpart(trs, m21, 'openEMS'))
    assert np.allclose(y, 20 * np.log10(0.05))                       # |0.25 - 0.2|
    plot.ref.setCurrentText('against mom25d')                         # openEMS against mom25d: the other sign
    assert lines() and all(np.allclose(c.yData, -20 * np.log10(0.25 / 0.2)) for c in lines())


def test_run_notes_on_the_results_page(tmp_path, monkeypatch):
    """The run's warnings and notes (the board's conversion, the line model, the log's 'note:' lines) under a fold
    on the Results page: open and red with a warning, folded with notes only, hidden with neither."""
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    from kicad2ems_gui import application
    from kicad2ems_gui.app import MainWindow, run_notes
    application()
    sm = dict(warnings=['WARNING: openems: 2 vias moved onto the mesh'], model=dict(notes=['B.Cu: solid ground']),
              lines=dict(notes=['P2: no reference copper']),
              log=['mom25d: 400 unknowns', 'note: --steer, --taper and --aim need --drive: ignored',
                   'mom25d: note: wave ports need a longer feed', 'WARNING: openems: 2 vias moved onto the mesh'])
    warns, notes = run_notes(sm)
    assert warns == ['openems: 2 vias moved onto the mesh']
    assert notes == ['B.Cu: solid ground', 'P2: no reference copper', '--steer, --taper and --aim need --drive: ignored',
                     'wave ports need a longer feed']
    f = np.linspace(1e9, 3e9, 11)
    _s2p(tmp_path / 'b_openems.s2p', f, np.full((11, 2, 2), 0.2 + 0j))
    (tmp_path / 'b_run.json').write_text(json.dumps(sm))
    w = MainWindow()
    r = w.results
    files = [('s', str(tmp_path / 'b_openems.s2p')), ('run', str(tmp_path / 'b_run.json'))]
    r.show(files)
    assert r.notes_btn.isVisibleTo(r) and r.notes_btn.text() == 'Notes and warnings (1 warning, 4 notes)'
    assert r.notes_btn.isChecked() and r.notes.isVisibleTo(r) and '#c62828' in r.notes.text()
    (tmp_path / 'b_run.json').write_text(json.dumps(dict(sm, warnings=[], log=[])))
    r.show(files)
    assert r.notes_btn.text() == 'Notes and warnings (2 notes)' and not r.notes.isVisibleTo(r)
    r.notes_btn.setChecked(True)
    assert r.notes.isVisibleTo(r) and 'solid ground' in r.notes.text()
    (tmp_path / 'b_run.json').write_text(json.dumps(dict(warnings=[], model=dict(notes=[]))))
    r.show(files)
    assert not r.notes_btn.isVisibleTo(r)
    w.setup.dirty = False
    w.close()
