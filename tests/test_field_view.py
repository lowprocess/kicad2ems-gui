"""The field view tab on a run folder: a time-domain plane dump (VTR frames) and a frequency-domain one (HDF5),
frames, components, live following and the phase of a frequency-domain dump (from kicad2ems's field tests)."""
import os
import pytest




def test_field_view_tab(run_folder, tmp_path):
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from kicad2ems_gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    out, _ = run_folder
    w = MainWindow()
    f = w.fields
    f.load(out)
    assert len(f.srcs) == 2 and f.src.domain == 'TD' and f.frame.maximum() == 4 and f.axis.currentText() == 'z'
    f.frame.setValue(3)
    assert '4/5' in f.frame_lab.text() and f.pl.img.shape == (30, 12)
    f.comp.setCurrentIndex(3)                                       # Ez: signed, symmetric range
    assert f.pl.signed and f.lim[0] == -f.lim[1]
    f.follow(out)                                                   # live: jumps to the newest frame
    assert f.frame.value() == 4
    f.dump.setCurrentIndex(1)
    f.phase_on.setChecked(True)
    f.phase.setValue(90)
    assert 'phase 90°' in f.frame_lab.text()
    w.close()
