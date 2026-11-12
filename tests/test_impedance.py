"""Tools > Impedance calculator: what is typed solved as it is typed, a fit's size back in its box, a board's layer
as the stack, what is wrong said in the window."""
import os
import time

import pytest

pytest.importorskip('PySide6')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
EXAMPLES = os.path.join(os.environ.get('KICAD2EMS_SRC') or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'kicad2ems'), 'examples')


def settle(app, dlg, seconds=30):
    end = time.time() + seconds
    app.processEvents()
    while dlg.busy() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not dlg.busy()


@pytest.fixture
def dialog():
    from kicad2ems_gui import application
    from kicad2ems_gui.impedance import ImpedanceCalculator
    app = application()
    dlg = ImpedanceCalculator()
    yield dlg, app
    settle(app, dlg)
    dlg.close()


def test_what_is_typed_is_solved(dialog):
    dlg, app = dialog
    settle(app, dlg)
    assert dlg.result['z0'] == pytest.approx(50.8, abs=0.3) and 'Z0 50.' in dlg.out.text() and 'Hammerstad' in dlg.out.text()
    assert dlg.text().startswith('microstrip: w 0.35, t 0.035 mm on 0.2 mm εr 4.3')
    assert dlg.view.v is not None and 'Z0 50.' in dlg.view.info.text() and 'line model' not in dlg.view.info.text()
    assert [dlg.what.itemData(i) for i in range(dlg.what.count())] == ['z0'] and dlg.vary.count() == 1
    assert not dlg.gap.isEnabled() and dlg.over_row.isHidden()
    dlg.w.setValue(0.2)                                         # narrower: higher
    settle(app, dlg)
    assert dlg.result['z0'] > 60
    dlg.over.setCurrentIndex(dlg.over.findData('plane'))        # a plane 0.2 mm over it: a stripline
    settle(app, dlg)
    assert dlg.result['kind'] == 'stripline' and dlg.result['eeff'] == pytest.approx(4.3) and not dlg.over_row.isHidden()
    dlg.over.setCurrentIndex(dlg.over.findData('mask'))
    settle(app, dlg)
    assert dlg.solved.mask == pytest.approx(0.02) and dlg.over_label.text() == "the mask's thickness"


def test_a_fit_puts_its_size_in_the_box(dialog):
    dlg, app = dialog
    dlg.target.setValue(50)
    dlg.calculate(fit=True)
    settle(app, dlg)
    assert dlg.result['z0'] == pytest.approx(50, rel=1e-3) and dlg.w.value() == pytest.approx(0.3597, abs=2e-3)
    dlg.pair.setChecked(True)
    settle(app, dlg)
    assert [dlg.what.itemData(i) for i in range(dlg.what.count())] == ['zdiff', 'zcommon', 'zodd', 'zeven']
    assert [dlg.vary.itemData(i) for i in range(dlg.vary.count())] == ['w', 'gap'] and 'Zdiff' in dlg.out.text()
    assert [dlg.view.mode.itemData(i) for i in range(dlg.view.mode.count())] == ['odd', 'even', 'line']
    dlg.target.setValue(100)
    dlg.vary.setCurrentIndex(dlg.vary.findData('gap'))
    dlg.calculate(fit=True)
    settle(app, dlg)
    assert dlg.result['zdiff'] == pytest.approx(100, rel=1e-3) and dlg.gap.value() != 0.15 and dlg.fit_btn.isEnabled()
    dlg.target.setValue(400)                                    # out of reach: said, nothing changed
    gap = dlg.gap.value()
    dlg.calculate(fit=True)
    settle(app, dlg)
    assert 'gives Zdiff 400 Ω' in dlg.out.text() and dlg.result is None and dlg.gap.value() == gap and dlg.text() == ''


def test_the_open_board_s_layers_are_stacks(dialog):
    dlg, app = dialog
    dlg.set_board(os.path.join(EXAMPLES, 'demo_transition.kicad_pcb'))
    assert [dlg.stack.itemData(i) for i in range(dlg.stack.count())] == [None, 'F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu']
    dlg.stack.setCurrentIndex(dlg.stack.findData('In1.Cu'))
    settle(app, dlg)
    assert dlg.result['kind'] == 'stripline' and dlg.below_row.isHidden() and dlg.over.isHidden()
    assert dlg.stack_note.text().startswith('stripline: w 0.35')
    dlg.set_board(None)                                         # the board closed: typed again
    settle(app, dlg)
    assert dlg.stack.count() == 1 and dlg.result['kind'] == 'microstrip' and not dlg.below_row.isHidden()
    dlg.set_board('/no/such/board.kicad_pcb')
    assert dlg.stack.count() == 1
