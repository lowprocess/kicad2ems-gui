"""
kicad2ems-gui's public API: what other packages may import (the KiCad plugin, kicad2ems-ipc). Everything else in
kicad2ems_gui is private to it and may change in any release.

    PlanView      the board seen from above, the window's plan view and the KiCad plugin's map

A subclass of PlanView may use, beside its public methods (load, set_board, set_lines_visible, current_layer,
z_of, redraw, fit, select) and its `selected` signal: `plot` (the pyqtgraph PlotWidget it draws in), `mesh` (the
mesh selector), and override redraw() and the mouse hooks _moved(scene_pos) and _clicked(event), calling the
base's for what it does not handle itself.

API_VERSION is (major, minor), as kicad2ems.api's: a minor release adds names, a major one removes or changes one.
"""
API_VERSION = (1, 0)


def __getattr__(name):                                          # PySide6 and pyqtgraph load on first use
    if name == 'PlanView':
        from .planview import PlanView
        return PlanView
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ['API_VERSION', 'PlanView']
