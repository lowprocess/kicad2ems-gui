"""A setting picked on the board: the board as drawn in the Viewer's plan before any run (kicad2ems.layout), an
option's `pick` as a button beside the setting, and clicks on the plan into it."""
import os
import time

import pytest

from k2e_fixtures import ROOT

BUS = os.path.join(ROOT, 'examples', 'rf_bus.kicad_pcb')           # three traces D0, D1, D2 over a plane


@pytest.fixture
def window(tmp_path, monkeypatch):
    """The window with kicad2ems's own crosstalk question and, where pcbqs is installed, its rail (the other tests'
    stand-ins have nothing to pick), on the bus board: its layout read."""
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    from kicad2ems import analyses
    from kicad2ems.si import Crosstalk
    reg = dict(analyses.registry())                                 # the stand-ins, and
    reg['crosstalk'] = Crosstalk()
    try:
        from pcbqs.analyses import PowerIntegrity
        reg['pdn'] = PowerIntegrity()
    except ImportError:
        pass
    monkeypatch.setattr(analyses, '_registry', reg)
    from PySide6.QtCore import QSettings
    from kicad2ems_gui import application, study, app as gui
    from kicad2ems_gui.app import MainWindow
    listed = study.installed()
    for module in (study, gui):
        monkeypatch.setattr(module, 'ANALYSES', listed)
        monkeypatch.setattr(module, 'BY_KEY', {a.key: a for a in listed})
    monkeypatch.setattr(study, 'TREE', study.tree())
    app = application()
    QSettings('kicad2ems', 'gui').clear()
    w = MainWindow()
    w.system.stop()
    w.meters.stop()
    w.setup.set_values(dict(board=BUS, out=str(tmp_path / 'out')))
    w.show()
    w.update_needed()
    t0 = time.time()
    while w.drawn is None and time.time() - t0 < 30:                # the layout: read in a thread
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    yield w, app
    w.end_pick()
    w.setup.dirty = False
    w.close()
    QSettings('kicad2ems', 'gui').clear()


class _Click:
    """A left click at a point of the plan (model mm)."""
    def __init__(self, plan, x, y):
        from PySide6.QtCore import QPointF
        self.pos = plan.plot.getPlotItem().vb.mapViewToScene(QPointF(x, y))

    def button(self):
        from PySide6.QtCore import Qt
        return Qt.LeftButton

    def scenePos(self):
        return self.pos


def _end(layout, net):
    """A point on a net's copper on F.Cu."""
    from shapely.geometry import shape
    p = shape(next(it['polygon'] for it in layout['copper']['F.Cu'] if it['net'] == net)).representative_point()
    return p.x, p.y


def test_the_board_is_shown_as_drawn_before_any_run(window):
    w, app = window
    plan = w.viewer.plan
    assert w.drawn is not None and plan.board is w.drawn and plan.board['layout_of'] == os.path.abspath(BUS)
    assert w.viewer.view() == 'Plan' and not w.viewer.buttons['3D'].isEnabled()
    assert {it['net'] for it in plan.board['copper']['F.Cu']} == {'D0', 'D1', 'D2'}
    from kicad2ems_gui import app as gui
    drawn = w.drawn
    w.update_needed()                                               # the same file: not read again
    app.processEvents()
    assert w.drawn is drawn and not any(t.isRunning() for t in gui._READING)


def test_a_run_s_board_stays_and_the_pick_is_on_the_board_as_drawn(window, tmp_path):
    """A run's board has only the nets it simulated and no parts: a pick shows the board as drawn in its place,
    and the run's is back when the pick ends; a folder without a board leaves the board as drawn."""
    import json
    w, app = window
    xt, plan = w.pages['crosstalk'], w.viewer.plan
    ran = {k: v for k, v in w.drawn.items() if k not in ('layout_of', 'footprints', '_prepared')}
    ran['copper'] = dict(ran['copper'], **{'F.Cu': [it for it in ran['copper']['F.Cu'] if it['net'] == 'D0']})
    out = tmp_path / 'run'
    out.mkdir()
    (out / 'bus_board.json').write_text(json.dumps(ran))
    assert w.viewer.load(str(out)) and not plan.board.get('layout_of')
    w.viewer.show_layout(w.drawn)                                   # (a layout read after: the run's board stays)
    assert not plan.board.get('layout_of')
    xt.pick_btns['nets'].setChecked(True)
    app.processEvents()
    assert plan.board is w.drawn and plan._pick[0] == 'nets'
    plan.layer.setCurrentIndex(plan.layer.findData('F.Cu'))
    plan._clicked(_Click(plan, *_end(w.drawn, 'D2')))               # a net the run did not have
    assert xt.picked_names('nets') == ['D2']
    xt.pick_btns['nets'].setChecked(False)
    app.processEvents()
    assert not plan.board.get('layout_of') and plan._behind is None
    empty = tmp_path / 'none'
    empty.mkdir()
    w.viewer.load(str(empty))                                       # nothing of a board in it: as drawn
    assert plan.board is w.drawn and w.viewer.buttons['Plan'].isEnabled()
    assert not w.viewer.buttons['3D'].isEnabled()


def test_a_setting_s_pick_button_takes_clicks_on_the_plan(window):
    w, app = window
    xt, plan = w.pages['crosstalk'], w.viewer.plan
    assert {'nets', 'aggressor', 'near'} <= set(xt.pick_btns) and 'rise' not in xt.pick_btns
    assert xt.pick_kind('nets') == 'nets' and xt.pick_kind('near') == 'parts' and xt.pick_kind('rise') is None
    xt.pick_btns['nets'].setChecked(True)
    app.processEvents()
    assert w._picking == (xt, 'nets') and plan._pick[0] == 'nets' and w.viewer.view() == 'Plan'
    plan.layer.setCurrentIndex(plan.layer.findData('F.Cu'))
    app.processEvents()
    for net in ('D0', 'D1'):
        plan._clicked(_Click(plan, *_end(w.drawn, net)))
    assert xt.picked_names('nets') == ['D0', 'D1'] and plan.picked == ['D0', 'D1']
    assert xt.values()['nets'] in (['D0', 'D1'], 'D0\nD1')
    plan._clicked(_Click(plan, *_end(w.drawn, 'D0')))               # again: taken out
    assert xt.picked_names('nets') == ['D1'] and plan.picked == ['D1']
    x, y = _end(w.drawn, 'D0')
    plan._clicked(_Click(plan, x, y + 30.0))                        # off the copper: nothing
    assert xt.picked_names('nets') == ['D1']
    # another setting's button: this one's is let go, and the plan marks the other's names
    xt.pick_btns['aggressor'].setChecked(True)
    app.processEvents()
    assert not xt.pick_btns['nets'].isChecked() and w._picking == (xt, 'aggressor') and plan.picked == []
    plan._clicked(_Click(plan, *_end(w.drawn, 'D2')))
    assert xt.picked_names('aggressor') == ['D2'] and xt.picked_names('nets') == ['D1']
    xt.pick_btns['aggressor'].setChecked(False)
    app.processEvents()
    assert w._picking is None and plan._pick is None and plan.picked == []
    plan._clicked(_Click(plan, *_end(w.drawn, 'D0')))               # no pick: a click picks nothing
    assert xt.picked_names('aggressor') == ['D2']


def test_one_name_replaces_and_several_are_listed(window):
    w, app = window
    xt = w.pages['crosstalk']
    assert xt.take_pick('near', 'U1') == ['U1'] and xt.take_pick('near', 'J2') == ['U1', 'J2']
    assert xt.w['near'].text() == 'U1, J2' and xt.take_pick('near', 'U1') == ['J2']


def test_a_rail_s_table_cell_is_picked_by_its_column(window):
    pytest.importorskip('pcbqs')
    from kicad2ems_gui.analysispanel import CELL
    w, app = window
    pdn, plan = w.pages['pdn'], w.viewer.plan
    assert CELL in pdn.pick_btns and pdn.pick_kind('rail') == 'net' and pdn.pick_kind('source') == 'part'
    t, keys = pdn.table, pdn.run_keys
    t.setCurrentCell(0, keys.index('rail'))
    pdn.pick_btns[CELL].setChecked(True)
    app.processEvents()
    assert w._picking == (pdn, CELL) and plan._pick[0] == 'net'
    plan.layer.setCurrentIndex(plan.layer.findData('F.Cu'))
    plan._clicked(_Click(plan, *_end(w.drawn, 'D1')))
    plan._clicked(_Click(plan, *_end(w.drawn, 'D2')))               # one net: the last picked
    assert t.item(0, keys.index('rail')).text() == 'D2' and pdn.runs()[0]['rail'] == 'D2'
    t.setCurrentCell(0, keys.index('source'))                       # the pick follows the cell: a part now
    app.processEvents()
    assert plan._pick[0] == 'part' and pdn.pick_btns[CELL].isChecked()
    t.setCurrentCell(0, keys.index('volts'))                        # not a net's or a part's: the pick ends
    app.processEvents()
    assert not pdn.pick_btns[CELL].isChecked() and w._picking is None and plan._pick is None
    assert 'select a cell' in w.statusBar().currentMessage()
    assert pdn.pick_kind('ground') == 'nets' and 'ground' in pdn.pick_btns     # a shared setting: its own button
