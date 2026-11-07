# kicad2ems-gui

The window of [kicad2ems](https://github.com/lowprocess/kicad2ems): a run's settings, the run itself and its
results. S-parameter plots and the report, the board in plan and 3D with the line model over it, field maps and
animations, antenna patterns and beam steering, dfsynth's filter synthesis (the Filter page), and converter input-loop magnetic fields (the Near field page).
The Near field page uses `python -m pcbqs.mqs`; update mom25d to obtain the command and its option schema.

![A hairpin filter's S-parameters from gfdtd, mom25d and the line model, with a Smith chart](https://github.com/lowprocess/kicad2ems/raw/main/docs/img/readme/gui_sparams.png)

The settings form is made from kicad2ems's option tables and its solver registry, so an installed solver package
(openEMS, mom25d, gfdtd or any other plugin) gets its tick box and its settings with no change here. Each run is a
`kicad2ems` process (`kicad2ems.runs`), so the window needs nothing of a solver's and closing it never loses a
run. kicad2ems's [GUI page](https://github.com/lowprocess/kicad2ems/blob/main/docs/gui.md) covers using it.

## Install

    python -m pip install 'kicad2ems[gui]'              # kicad2ems with its window
    python -m pip install 'kicad2ems-gui @ git+https://github.com/lowprocess/kicad2ems-gui'
    python -m pip install 'kicad2ems-gui[filter] @ ...' # with the Filter page (dfsynth)

    kicad2ems-gui [config.toml]                         # or: python -m kicad2ems_gui

It needs PySide6, pyqtgraph and PyOpenGL (installed with it), and kicad2ems 261101.post1 or later (its API 2.2).

## Inside

| Module | Contents |
|---|---|
| `app.py` | `MainWindow`: the panels, a run and its events |
| `runner.py` | the settings form without Qt: fields, sections, solver tick boxes, configs read and written back |
| `runfolders.py` | a folder per run and one per board's preview |
| `planview.py`, `meshpick.py` | the board seen from above, with the line model and the meshes (the KiCad plugin's map too) |
| `viewer.py`, `volumetab.py`, `volume3d.py` | the plan, cut and 3D views; `volume3d` holds their arrays, without Qt |
| `sectionview.py` | the field across a line-model section (the KiCad plugin's too) |
| `splot.py`, `traces.py` | S-parameter plots, Smith charts, traces and their export |
| `fieldtab.py`, `antennatab.py`, `steering.py` | field maps, antenna results, beam steering |
| `filtertab.py` | the Filter page (dfsynth) |
| `systempanel.py`, `statusbar.py`, `meters.py` | what this machine can run, memory, estimates |
| `panels.py` | a collapsible section, an image panel, a row of controls that wraps |
| `api.py` | what other packages may use (the KiCad plugin): `PlanView`, `SectionView`, `API_VERSION` |

## Tests

    python -m pytest

They use kicad2ems's fixtures, example boards and stand-in solvers from a kicad2ems checkout (`KICAD2EMS_SRC`,
default `../kicad2ems`), and run the window offscreen. kicad2ems's `tools/test_all.sh` runs them with the rest.
`python tools/readme_media.py` makes kicad2ems's README and GUI-page pictures from its examples.

## Licence

GPL-3.0-or-later, as kicad2ems.

Near field includes **Preview mesh** (no fill/solve), a layer-selectable copper
and component view, and interactive field overlays with opacity controls. The
Viewer supports the same meshes and approximate component bodies in 3D. Cyan
marks simulated copper, grey the layout context and gold selected components.
The **Use board and rail in Power Integrity** action transfers the board/net
context while leaving DC source, voltage and loads for review.

The **Circuit** page runs ngspice operational circuits through
`python -m pcbqs.power_circuit`. It accepts an editable component model with
switch/NMOS/VDMOS/vendor-subcircuit choices, capacitor ESR/ESL, inductor DCR,
input filter and coupled receiver. Select frequency/load-power sweeps and k,
optionally include a passive broadband PCB equivalent and infer periodic
copper fields. Top controls override corresponding JSON values. Individual
case fields open in the existing time-domain Viewer. The supplied parasitics
and receiver are assumptions; see pcbqs `docs/power-circuit.md` for scope and
validation, including the distinction between electrical startup and periodic
field inference. ngspice must be installed separately.

**Parallel circuit cases** runs independent operating points concurrently
(default four, capped by available CPUs). Extraction/field transfers are prepared
once and shared; stopping a sweep also stops its active ngspice children. Each
case records runtime and per-trial solver statistics for profiling.
