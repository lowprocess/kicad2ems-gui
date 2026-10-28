"""
kicad2ems-gui: kicad2ems's window (needs PySide6 and pyqtgraph). The settings form made from kicad2ems's option
tables and solver registry, runs as kicad2ems processes (kicad2ems.runs), and the results: S-parameter plots, the
report, the board in plan and 3D, field maps and animations, antenna patterns and beam steering, and dfsynth's
filter synthesis (the Filter page).

    app          MainWindow: the panels, the run and its events
    runner       the settings form without Qt: fields, sections, solver tick boxes, configs read and written
    api          the public surface (PlanView, for the KiCad plugin)
    planview     the board seen from above (also the KiCad plugin's map); viewer, volumetab: plan, cut and 3D views
    volume3d     the 3D view's arrays (no Qt): copper, parts, field volumes, far-field surfaces
    splot, traces, fieldtab, antennatab, steering, filtertab, systempanel, statusbar, meters, panels, runfolders
"""
__version__ = '261028-r1'



def application(argv=()):
    """The QApplication, made with shared OpenGL contexts when there is none yet: the 3D field view's shaders and
    buffers (pyqtgraph caches them across views) stay valid when a dock is moved or another window opens."""
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        app = QApplication(list(argv))
        import os
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kicad2ems.svg')))
        app.setDesktopFileName('kicad2ems')                         # Wayland: the window's launcher entry and icon
    return app


def main(argv=None):
    """kicad2ems-gui [config.toml]"""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        from .app import main as _main
    except ImportError as e:
        raise SystemExit(f"kicad2ems-gui needs PySide6 and pyqtgraph ({e}): python -m pip install kicad2ems-gui")
    return _main(argv)
