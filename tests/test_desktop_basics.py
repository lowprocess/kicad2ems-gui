"""The window's desktop basics (R-E25): settings undo and redo, the plots' colours, a report saved and printed, a
run's S-parameters exported as Touchstone."""
import os
from types import SimpleNamespace

import pytest

pytest.importorskip('PySide6')
pytest.importorskip('pyqtgraph')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / 'settings'))
    from kicad2ems_gui.app import MainWindow
    w = MainWindow()
    w.setup.set_values(dict(board='x.kicad_pcb', fmin=1.0, fmax=6.0, cut_ports=False))
    return w


def test_settings_undo_and_redo(win, app):
    s = win.setup
    fmax, cut = s.edits['fmax'][0], s.edits['cut_ports'][0]
    assert not s.can_undo() and not win.undo_act.isEnabled()                    # a loaded config: nothing to undo
    for t in ('8', '8.', '8.5'):                                                # typing: one step once it rests
        fmax.setText(t)
    assert s.can_undo() and s.undo_text() == 'Undo fmax'
    cut.setChecked(True)                                                        # a tick: a step at once
    assert s._undo and win.undo_act.isEnabled() and s.undo_text() == 'Undo cut_ports'
    assert s.undo() and not cut.isChecked() and fmax.text() == '8.5'
    assert s.undo() and fmax.text() == '6.0' and not s.can_undo() and s.dirty
    assert s.can_redo() and s.undo_text(redo=True) == 'Redo fmax'
    assert s.redo() and fmax.text() == '8.5' and s.redo() and cut.isChecked() and not s.redo()
    s.undo()
    fmax.setText('7')                                                           # a new change drops the redo
    s._commit()
    assert not s.can_redo() and s.values()['fmax'] == 7.0
    s.set_values(dict(board='y.kicad_pcb'))                                     # another config: a fresh start
    assert not s.can_undo() and not s.can_redo()


def test_the_plots_follow_the_theme(win, app):
    import pyqtgraph as pg
    from kicad2ems_gui import theme
    w = pg.PlotWidget(title='t')
    try:
        win.set_plot_colours('dark')
        assert theme.dark() and win.qsettings.value('view/plots') == 'dark'
        assert w.backgroundBrush().color().name() == theme.DARK['bg']          # an open plot restyled
        assert pg.getConfigOption('background') == theme.DARK['bg']            # and the plots to come
        assert w.getPlotItem().getAxis('left').pen().color().name() == theme.DARK['fg']
        assert [a.isChecked() for a in win.plot_acts.actions()] == [False, False, True]
        win.results.splot.restyle()                                            # its own items: no fault
        win.set_plot_colours('light')
        assert w.backgroundBrush().color().name() == theme.LIGHT['bg'] and not theme.dark()
        win.set_plot_colours('system')
        assert theme.choice() == 'system' and theme.dark() == theme.system_dark()
    finally:
        theme.set_choice('light')


def test_a_report_saved_and_printed(app, tmp_path):
    from PySide6.QtPrintSupport import QPrinter
    from kicad2ems_gui import reportview as RV
    png = tmp_path / 'map.png'
    from PySide6.QtGui import QImage, QColor
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(QColor('red'))
    img.save(str(png))
    rep = dict(title='Hottest copper 84.2 °C', sections=[dict(title='Parts', table=dict(columns=['part', 'W'],
               rows=[['L1', 0.48]]))], images=[str(png)])
    v = RV.ReportView()
    assert not any(b.isEnabled() for b in v.page_buttons)                       # no report: nothing to save
    assert v.save(str(tmp_path / 'r.html')) is None
    v.set_report(rep)
    assert all(b.isEnabled() for b in v.page_buttons)
    h = v.save(str(tmp_path / 'r'))                                             # .html added
    text = open(h, encoding='utf-8').read()
    assert h.endswith('r.html') and text.startswith('<!doctype html>') and 'data:image/png;base64,' in text
    assert str(png) not in text and '<td align=left>L1</td>' in text            # the picture inside it
    pdf = v.save(str(tmp_path / 'r.pdf'))
    assert open(pdf, 'rb').read(4) == b'%PDF'
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(tmp_path / 'printed.pdf'))
    assert v.print_(printer) and (tmp_path / 'printed.pdf').read_bytes()[:4] == b'%PDF'


def test_a_run_s_touchstone_exported(tmp_path):
    from kicad2ems_gui.resultstab import ResultsTab
    src = tmp_path / 'run' / 'b_mom25d.s2p'
    src.parent.mkdir()
    src.write_text('# GHz S RI R 50\n1 0 0 1 0 1 0 0 0\n')
    (tmp_path / 'run' / 'b_run.json').write_text('{}')
    tab = SimpleNamespace(_files=[('mom25d', str(src)), ('summary', str(tmp_path / 'run' / 'b_run.json')),
                                  ('gone', str(tmp_path / 'run' / 'b_x.s4p'))])
    assert ResultsTab.touchstones(tab) == [('mom25d', str(src))]                # Touchstone files that are there
    out = ResultsTab.export_touchstone(tab, str(src), str(tmp_path / 'mine'))   # the extension kept
    assert out.endswith('mine.s2p') and open(out).read() == src.read_text()
    assert ResultsTab.export_touchstone(tab, str(src), str(src)) == str(src)    # onto itself: left as it is
