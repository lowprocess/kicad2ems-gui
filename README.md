# kicad2ems-gui

The window of [kicad2ems](https://github.com/lowprocess/kicad2ems): a run's settings, the run itself and its
results. S-parameter plots and the report, the board in plan and 3D with the line model over it, field maps and
animations, antenna patterns and beam steering, dfsynth's filter synthesis (the Filter page), and whatever
analyses are installed beside S-parameters (pcbqs's power integrity, near field, circuit and thermal).

![A hairpin filter's S-parameters from gfdtd, mom25d and the line model, with a Smith chart](https://github.com/lowprocess/kicad2ems/raw/main/docs/img/readme/gui_sparams.png)

The settings form is made from kicad2ems's option tables and its solver registry, so an installed solver package
(openEMS, mom25d, gfdtd or any other plugin) gets its tick box and its settings with no change here. The analyses
come the same way, from kicad2ems's analysis registry (`kicad2ems.api.frontend.analyses`): the window knows none
of them by name. Each run is a process of its own (`kicad2ems.runs`, or the analysis's command), so the window
needs nothing of a solver's and closing it never loses a run. kicad2ems's [GUI page](https://github.com/lowprocess/kicad2ems/blob/main/docs/gui.md) covers using it.

## The study

The dock on the left is the study: the board (one for every analysis), the **Analyses** and the settings of the
analysis selected there. S-parameters is kicad2ems's own run with the solvers ticked under Solvers. The others are
the analysis plugins installed (`kicad2ems --check` lists them): each one's settings are a panel made from the
options its plugin declares, with what else it offers (Near field's *Find converters*, which lists the board's
converters to pick from; after a near-field run, *Copy the input rail to Power integrity*). None installed: the
list is S-parameters alone.

**Preview** and **Run** act on the ticked analyses, one after the other in the list's order; the Run page lists
them with each one's state, time and log. Run > *Run the selected analysis alone* (or the list's context menu) runs
one whatever is ticked. An analysis may start from another's result: Thermal takes its losses from the latest
circuit run when none are typed, so with both ticked it runs after Circuit and on that run's board.

**What a run leaves is shown where every result is**, not on a page of its own:

- its **maps** in the Viewer, 3D, Plan and Cut (an analysis writes them as field dumps: a rail's drop and current
  per layer, a near field's H, a board's temperature per layer, in °C on a scale from its coolest point);
- its **curves** on the Results page (a rail's impedance, a near field's spectrum, a circuit's waveforms: Plots);
- its **report** there too: what it found, to read (Report), or its tables to sort by a column, copy into a
  spreadsheet or export as CSV (Tables).

**Results of** (the toolbar) lists every result of the board, each run in a folder of its own under the output
folder: the preview, the S-parameter runs, and each analysis's runs. Choosing one fills the pages. Results >
**Compare with** lays other runs of the same kind over the plots, and View > **A second Viewer** opens another
run's maps in a window of its own.

A config holds the study: beside kicad2ems's settings, the analyses it runs and their settings under
`[analysis]` (`run = ["circuit", "thermal"]`, `[analysis.circuit] model = "buck.json"`), read when it is opened
and written back when it is saved. A config that names no analyses is an S-parameter study.

**File > Examples** lists the examples in their groups (Antennas, RF structures, Lumped-element demos, and those
the installed analyses ship: Circuits). A circuit to start from is an example like any other: it opens as a study
with its board, its model on the Circuit page and the circuit ticked.

Filter Synthesis opens from the toolbar's Filter (it is closed when the window opens). The **Circuit** page, the
one analysis with an editor of its own (its model as a schematic), is there while Circuit is ticked; its model is
a file the config names, saved back beside the config with the study.

## Install

    python -m pip install 'kicad2ems[gui]'              # kicad2ems with its window
    python -m pip install 'kicad2ems-gui @ git+https://github.com/lowprocess/kicad2ems-gui'
    python -m pip install 'kicad2ems-gui[filter] @ ...' # with the Filter page (dfsynth)

    kicad2ems-gui [config.toml]                         # or: python -m kicad2ems_gui

It needs PySide6, pyqtgraph and PyOpenGL (installed with it), and kicad2ems 261112 or later (its API 2.5). The
analyses need pcbqs 261112 or later (`kicad2ems[qs]`).

## Inside

| Module | Contents |
|---|---|
| `app.py` | `MainWindow`: the study dock, the pages, a run of the ticked analyses and its events |
| `study.py` | the analyses a board can have (S-parameters, then the registry's), what follows what, the list in the Study dock |
| `analysispanel.py` | an analysis's settings and its run, for any plugin: the form from its options, its command as a child process |
| `curves.py`, `curveplot.py` | an analysis's curves on the Results page (a rail's impedance, a spectrum, waveforms), other runs over them |
| `reportview.py` | an analysis's report on the Results page: the page to read, its tables to sort, copy and export |
| `runner.py` | the settings form without Qt: fields, sections, solver tick boxes, configs read and written back |
| `runfolders.py` | a folder per run and one per board's preview |
| `planview.py`, `meshpick.py` | the board seen from above, with the line model and the meshes (the KiCad plugin's map too) |
| `viewer.py`, `volumetab.py`, `volume3d.py` | the plan, cut and 3D views; `volume3d` holds their arrays, without Qt |
| `sectionview.py` | the field across a line-model section (the KiCad plugin's too) |
| `splot.py`, `traces.py` | S-parameter plots, Smith charts, traces and their export |
| `fieldtab.py`, `antennatab.py`, `steering.py` | field maps, antenna results, beam steering |
| `filtertab.py` | the Filter page (dfsynth) |
| `impedance.py` | Tools > Impedance calculator: a stack-up's Z0 and the width of a target (kicad2ems's `lines.calc`) |
| `powercircuittab.py`, `schematicview.py` | the Circuit page: the circuit analysis's model as a schematic to edit, its run |
| `toolprocess.py` | a tool as a child process (an analysis's command, dfsynth) |
| `systempanel.py`, `statusbar.py`, `meters.py` | what this machine can run, memory, estimates |
| `panels.py` | a collapsible section, an image panel, a row of controls that wraps |
| `api.py` | what other packages may use (the KiCad plugin): `PlanView`, `SectionView`, `API_VERSION` |

## Tests

    python -m pytest

They use kicad2ems's fixtures, example boards and stand-in solvers from a kicad2ems checkout (`KICAD2EMS_SRC`,
default `../kicad2ems`), and run the window offscreen. The analyses are stand-ins too (`tests/fake_analyses.py`:
the same names as pcbqs's, each a few lines with a tool that writes a small result), so the window is tested as
the host of any plugin; `tests/test_real_analyses.py` runs pcbqs's own through it when pcbqs is installed. kicad2ems's `tools/test_all.sh` runs them with the rest.
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

The Circuit page now includes a **Schematic** editor beside **Model JSON**.
Select symbols to edit component models/parasitics/connections, add/remove
passives, undo/redo and save diagram positions. Search references or highlight
nets; expand Operating settings for the sweep controls. The optional pcbqs
backend owns KiCad import: `.kicad_sch` uses `kicad-cli`, or import a KiCad XML
netlist directly. Review existing/source values and selected parts before
applying changes. The original sheets can be viewed read-only with Qt SVG
support. DNP markers, hierarchy, fields and pin/net information remain visible;
unknown IC behavior is not automatically modeled. All edits affect the saved
simulation JSON, not the KiCad source file.
