# kicad2ems-gui

The window of [kicad2ems](https://github.com/lowprocess/kicad2ems): a run's settings, the run itself and its
results. S-parameter plots and the report, the board in plan and 3D with the line model over it, field maps and
animations, antenna patterns and beam steering, and dfsynth's filter synthesis (the Filter page).

The settings form is made from kicad2ems's option tables and its solver registry, so a solver package that is
installed (openEMS, mom25d, gfdtd or any other plugin) gets its tick box and its settings with no change here.
Each run is a `kicad2ems` process (`kicad2ems.runs`), so the window needs nothing of a solver's and closing it
never loses a run. kicad2ems's [GUI page](https://github.com/lowprocess/kicad2ems/blob/main/docs/gui.md) covers
using it.

## Install

    python -m pip install 'kicad2ems[gui]'              # kicad2ems with its window
    python -m pip install 'kicad2ems-gui @ git+https://github.com/lowprocess/kicad2ems-gui'
    python -m pip install 'kicad2ems-gui[filter] @ ...' # with the Filter page (dfsynth)

    kicad2ems-gui [config.toml]                         # or: python -m kicad2ems_gui

It needs PySide6, pyqtgraph and PyOpenGL (installed with it), and kicad2ems 261027-r2 or later.

## Inside

| Module | Contents |
|---|---|
| `app.py` | `MainWindow`: the panels, a run and its events |
| `runner.py` | the settings form without Qt: fields, sections, solver tick boxes, configs read and written back |
| `planview.py` | the board seen from above, with the line model and the meshes (the KiCad plugin's map too) |
| `viewer.py`, `volumetab.py`, `volume3d.py` | the plan, cut and 3D views; `volume3d` holds their arrays, without Qt |
| `splot.py`, `traces.py` | S-parameter plots, Smith charts, traces and their export |
| `fieldtab.py`, `antennatab.py`, `steering.py` | field maps, antenna results, beam steering |
| `filtertab.py` | the Filter page (dfsynth) |
| `systempanel.py`, `statusbar.py`, `meters.py` | what this machine can run, memory, estimates |

## Tests

    python -m pytest

They use kicad2ems's fixtures, example boards and stand-in solvers from a kicad2ems checkout (`KICAD2EMS_SRC`,
default `../kicad2ems`), and run the window offscreen. kicad2ems's `tools/test_all.sh` runs them with the rest.

## Licence

GPL-3.0-or-later, as kicad2ems.
