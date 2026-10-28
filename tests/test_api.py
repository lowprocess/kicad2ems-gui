"""kicad2ems_gui.api, the surface the KiCad plugin imports: PlanView and the members a subclass may use."""
import subprocess, sys


def test_api_loads_qt_on_first_use():
    code = "import sys, kicad2ems_gui.api as a; print('PySide6' in sys.modules, a.API_VERSION)"
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True).stdout.split(None, 1)
    assert out == ['False', '(1, 0)\n']


def test_planview_has_what_a_subclass_uses():
    from kicad2ems_gui import application
    from kicad2ems_gui.api import PlanView
    application()
    v = PlanView()
    for name in ('load', 'set_board', 'set_lines_visible', 'current_layer', 'z_of', 'redraw', 'fit', 'select',
                 'selected', 'plot', 'mesh', '_moved', '_clicked'):
        assert hasattr(v, name), name
    import shiboken6
    shiboken6.delete(v)                     # now, not at interpreter exit (a parentless plot can crash it then)
