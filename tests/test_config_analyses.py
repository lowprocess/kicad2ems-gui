"""A study's analyses in its config: the [analysis] tables written (runner.write_analyses), a config opened in the
window (the analyses it runs ticked, their settings in their panels, the others' cleared) and saved back."""
import os

import pytest

from kicad2ems_gui import runner
from kicad2ems.api.frontend import read_analyses, build_settings


def test_the_tables_are_written_and_replaced(tmp_path):
    cfg = tmp_path / 'b.toml'
    cfg.write_text('# a board\nboard = "b.kicad_pcb"   # here\nfmin = 1.0\n\n[solver.mom25d]\ndmax = 0.4\n')
    runner.write_analyses(str(cfg), None, {})                       # nothing to say, none there: untouched
    assert '[analysis' not in cfg.read_text()
    runner.write_analyses(str(cfg), ['pdn', 'rf'], dict(pdn=dict(rail='+3V3', volts=5.0, load=['U1=2', 'U2=1'], no_pdn=True),
                                                         thermal={}))
    text = cfg.read_text()
    assert text.startswith('# a board\nboard = "b.kicad_pcb"   # here\n') and '[solver.mom25d]\ndmax = 0.4' in text
    assert text.endswith('[analysis]\nrun = ["pdn", "rf"]\n\n[analysis.pdn]\nrail = "+3V3"\nvolts = 5.0\n'
                         'load = ["U1=2", "U2=1"]\nno_pdn = true\n')
    assert read_analyses(str(cfg)) == (['pdn', 'rf'], dict(pdn=dict(rail='+3V3', volts=5.0, load=['U1=2', 'U2=1'], no_pdn=True)))
    assert build_settings({}, str(cfg)).notes == [] and build_settings({}, str(cfg)).mom_dmax == 0.4
    runner.write_analyses(str(cfg), ['rf'], dict(mqs=dict(converter='U7')))             # replaced, not added to
    assert read_analyses(str(cfg)) == (['rf'], dict(mqs=dict(converter='U7'))) and cfg.read_text().count('[analysis]') == 1
    runner.write_analyses(str(cfg), None, {})                       # none any more: the tables gone
    assert '[analysis' not in cfg.read_text() and 'dmax = 0.4' in cfg.read_text()
    # an analysis's several tables (a board's rails): an array, replaced as one table is
    rails = [dict(rail='+5V', volts=5.0), dict(rail='+3V3', volts=3.3, load=['U1=1'])]
    runner.write_analyses(str(cfg), None, dict(pdn=rails, mqs=[dict(converter='U7')], thermal=[{}]))
    assert cfg.read_text().endswith('[analysis]\n\n[[analysis.pdn]]\nrail = "+5V"\nvolts = 5.0\n\n[[analysis.pdn]]\n'
                                    'rail = "+3V3"\nvolts = 3.3\nload = ["U1=1"]\n\n[analysis.mqs]\nconverter = "U7"\n')
    from kicad2ems.api.frontend import read_analysis_sets
    assert read_analysis_sets(str(cfg)) == dict(pdn=rails, mqs=[dict(converter='U7')])
    runner.write_analyses(str(cfg), None, dict(pdn=rails[:1]))
    assert cfg.read_text().count('analysis.pdn') == 1 and '[[' not in cfg.read_text() and 'dmax = 0.4' in cfg.read_text()


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


def test_a_config_opens_as_a_study_and_saves_back(window, tmp_path):
    w, app = window
    (tmp_path / 'b.kicad_pcb').write_text('')
    cfg = tmp_path / 'b.toml'
    cfg.write_text('board = "b.kicad_pcb"\n\n[analysis]\nrun = ["pdn", "thermal"]\n\n[analysis.pdn]\nrail = "+3V3"\n'
                   'load = ["U1=2", "U2=1"]\nboard = "other.kicad_pcb"\n\n[analysis.thermal]\nfilm = 12\n'
                   'circuit = "out/run"\n\n[analysis.cfd]\nfans = 2\n')
    pdn, mqs, th = (w.pages[k] for k in ('pdn', 'mqs', 'thermal'))
    mqs.set_values(dict(converter='U9'))                            # of the board before: gone with it
    assert w.setup.load(str(cfg))
    assert w.study.ticked() == ['pdn', 'thermal'] and w.study.current() == 'pdn' and not w.setup.dirty
    assert pdn.values()['rail'] == '+3V3' and pdn.values()['load'] == 'U1=2\nU2=1'
    assert pdn.board.text() == str(tmp_path / 'other.kicad_pcb')    # its own board: beside the config
    assert th.values()['film'] == '12' and th.values()['circuit'] == str(tmp_path / 'out' / 'run')
    assert mqs.values()['converter'] == '' and w.extra_analyses == dict(cfd=dict(fans=2))
    pdn.w['rail'].setText('+5V')                                    # an edit by hand: unsaved
    assert w.setup.dirty
    w.study.rows['nearfield'].setCheckState(0, __import__('PySide6.QtCore', fromlist=['Qt']).Qt.Checked)
    assert w.study.ticked() == ['pdn', 'mqs', 'thermal']
    assert w.setup.save() and not w.setup.dirty
    from kicad2ems.api.frontend import read_study
    run, tables = read_analyses(str(cfg))
    assert run is None and tables['cfd'] == dict(fans=2)            # [study] says what runs now; not installed: kept
    st = read_study(str(cfg))                                       # the rail tool answered both its questions
    assert st.said == 'study' and st.fields == {}                   # the analyses the config named: kept by name
    assert st.asked == dict(dc=['pdn'], pdn=['pdn'], nearfield=[], thermal=['thermal'])
    assert tables['pdn'] == dict(board='other.kicad_pcb', rail='+5V', load=['U1=2', 'U2=1'])    # the panel's own: as written
    assert tables['thermal'] == dict(circuit=str(tmp_path / 'out' / 'run'), film=12.0)
    assert 'circuit = "out/run"' in cfg.read_text() and 'board = "other.kicad_pcb"' in cfg.read_text()    # relative
    # a config with several rails: the first shown and run here, the others said, kept and written back
    many = tmp_path / 'rails.toml'
    many.write_text('board = "b.kicad_pcb"\n\n[study]\nrun = ["dc"]\n\n[[analysis.pdn]]\nrail = "+5V"\nvolts = 5\n\n'
                    '[[analysis.pdn]]\nrail = "+3V3"\nvolts = 3.3\nboard = "other.kicad_pcb"\n\n[[analysis.pdn]]\nrail = "+1V8"\n')
    assert w.setup.load(str(many))
    assert pdn.values()['rail'] == '+5V' and w.more_sets == dict(pdn=[
        dict(rail='+3V3', volts=3.3, board=str(tmp_path / 'other.kicad_pcb')), dict(rail='+1V8')])
    assert pdn.status.text().startswith('This config has 2 more of these (+3V3, +1V8): the first is shown and run here')
    pdn.w['volts'].setText('5.1')
    assert w.setup.save()
    from kicad2ems.api.frontend import read_analysis_sets
    assert read_analysis_sets(str(many))['pdn'] == [
        dict(rail='+5V', volts=5.1), dict(rail='+3V3', volts=3.3, board='other.kicad_pcb'), dict(rail='+1V8')]
    assert many.read_text().count('[[analysis.pdn]]') == 3
    plain = tmp_path / 'rf.toml'                                    # a config that says nothing of analyses:
    plain.write_text('board = "b.kicad_pcb"\n')                     # S-parameters, the panels cleared
    assert w.setup.load(str(plain))
    assert w.study.ticked() == ['rf'] and pdn.values()['rail'] == '' and pdn.board.text() == '' and w.extra_analyses == {}
    assert w.more_sets == {}
    assert w.setup.save() and '[analysis' not in plain.read_text() and '[study' not in plain.read_text()   # it stays plain
    w.study.set_ticked(['rf', 'pdn'])
    assert w.setup.dirty                                            # an open config: its ticks are its
    w.setup.dirty = False
    w.setup.new()
    assert w.study.ticked() == ['rf'] and w.setup.path is None
    w.study.set_ticked(['rf', 'thermal'])
    assert not w.setup.dirty                                        # no config open: the next window remembers
