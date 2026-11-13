# The window, from a clean slate

A design for kicad2ems-gui as it would be built today, and the order in which the present window can be taken
there. Written 2026-11-12. Steps 2 to 5 of [Getting there](#getting-there-from-the-present-window) are built
(the same day); the rest is as written. It assumes the registry of questions and engines in kicad2ems's
`ROADMAP.md` ("The study: questions and engines").

## What is wrong with the present window

It grew one page at a time, and each page solved its own problem:

- **Peers that are really steps.** Viewer, Run, Results, Filter and Circuit are tabs of equal weight, but three
  of them are stages of one job (set up, run, look) and two are separate tools. Nothing says what to do next.
- **Three places to open a file.** The toolbar (New, Open, Save, Save as), the File menu, and the Circuit page's
  own Load model, Save model and Choose PCB.
- **Every setting has the same weight.** A solver's form lists the mesh's corner refinement beside the frequency
  range. The four values a run needs are among forty.
- **State in five places.** The status bar, the Run page's stage line, the Study's State column, the estimate in
  the toolbar, and the "Results of" box.
- **The board is one tab among others.** Setting a port, a rail or a converter means typing a name read off
  another page.
- **Free docks.** Any panel can be floated, closed or stacked, and the saved layout is restored. That is how a
  panel ends up disabled or lost, and it buys little: nobody needs the log beside the schematic.
- **Disabled buttons that do not say why.** What a run still needs is in tooltips.

## Principles

1. **The board is the window.** Everything else is laid on it or beside it: what a question is about is drawn on
   the board, and picked from it.
2. **One question at a time.** The left side lists what you want to know; selecting one shows only its settings
   and its results.
3. **One primary action.** At every moment one button is the next step, and it is in the same place.
4. **Few settings, then the rest.** Each question shows what it cannot run without. The rest is one click away
   and searchable.
5. **Say what is missing.** A short list of what a run still needs, each line leading to where it is set.
6. **One place for each thing:** files in the header, questions on the left, settings on the right, answers
   under the board, activity at the bottom.

## Layout

One fixed layout: three columns and a drawer. The side columns fold away; nothing floats.

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ ≡  buck_sync ▾     Board ── Questions ── Set up ── Run ── Results          [ ▶ Run 2 ]  ⋯   │ header
├─────────────────┬────────────────────────────────────────────────────────┬───────────────────┤
│ RF              │  2D  3D │ F.Cu ▾ │ nets ▾ │ T ▾  62 ─────── 84 °C       │ Temperature       │
│  ○ S-parameters │                                                        │ pcbqs ▾           │
│  ○ Antenna      │                                                        │                   │
│ POWER           │                                                        │ Heat from         │
│  ○ Rail drop    │                  the board                             │  ◉ the circuit run│
│  ● Circuit    ✓ │        with what the selected question is about:       │  ○ typed losses   │
│ THERMAL         │        its ports, rail, loop, or its answer            │ Ambient   25 °C   │
│  ● Temperature ⚠│                                                        │ Air       still ▾ │
│                 │                                                        │                   │
│                 │                                                        │ ▸ More settings   │
│                 ├────────────────────────────────────────────────────────┤───────────────────│
│                 │ Plots │ Report │ Tables │ Log          run 14:02 ▾  ⇄  │ Still needed      │
│ + Add a question│  (curves, the report, a table, the run's output)       │ ⚠ Q1 has no loss: │
│                 │                                                        │   run the circuit │
├─────────────────┴────────────────────────────────────────────────────────┴───────────────────┤
│ ● Circuit: case 2 of 3, 41 s        last run 14:02 (56 s)              RAM 5 / 33 GB   GPU 0 % │ activity
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Header.** The study's name (a menu: new, open, recent, examples, save, export); the five steps, the present
  one marked, each clickable once it can be reached; the primary action; an overflow menu (settings, tools, help).
- **Left: the questions.** Grouped as the registry groups them. A filled dot is one this study asks; its mark is
  its state (needs something, ready, running, done, failed). "Add a question" lists the rest with one line each
  on what it gives and what it needs. An engine is not chosen here.
- **Middle: the board.** 2D and 3D of the same thing, with the layer, the nets shown and the field drawn as
  small controls along its top edge. No separate preview page: a preview is the board with the model's mesh on.
- **Right: the inspector.** The selected question: its engine ("auto", or a pick, or several to compare), then
  its few settings, then "More settings" (grouped, with a search box). Under it, what it still needs.
- **Drawer.** The answers that are not maps: Plots, Report, Tables and the Log, with the run they are of and a
  compare switch. It folds to its tab bar.
- **Activity bar.** What is running, with Stop beside it; the last run; the machine.

## The workflow

The header's steps are the same for every question. A step is offered when the one before it is complete.

| Step | What it shows | Primary action |
|---|---|---|
| Start (no study) | Open a board or a config, the recent ones, the examples as a gallery by group with a picture and a line each | Open |
| Board | The board, its stack-up and materials as read, with what looks wrong ("no stack-up in the file: FR-4 1.6 mm assumed") | Choose what to find out |
| Questions | The list of questions, each with what it gives, what it needs and roughly what it costs on this board | Set up |
| Set up | The selected question's settings; what it needs, picked on the board (click a net: the rail; a part: the converter; a pad: a port) | Run |
| Run | Progress per question in its row, the estimate before, the log in the drawer; the others stay usable | Stop |
| Results | The answer on the board and in the drawer; the run history; compare | Run again |

Details that make it explain itself:

- **The Run button says what it will do** ("Run 2": the circuit, then the temperature) and, when it cannot, what
  is missing ("Name the rail"), which is also the first line of "Still needed".
- **No Preview button.** Preparing the model is cheap and automatic after a change; its result ("12,400 cells,
  about 40 s, 1.1 GB") stands under the Run button and its mesh is a layer of the board view.
- **An order, not a queue to manage.** Questions that start from another's result (the temperature from the
  circuit's losses) say so in their row and run after it.
- **Every run is kept.** The drawer's run box lists them by time with what changed since the one before; pinning
  one lays it under the current one in every plot and table.
- **Empty states carry the instruction.** An empty drawer says "Run to see the waveforms here"; an empty
  inspector says "Select a question, or add one".
- **The circuit's schematic is a view of the middle column**, beside 2D and 3D, shown when the circuit is
  selected: the same place a board is looked at, not a page with its own file buttons.

## What is not in the window

- **Filter synthesis and the impedance calculator** are not about an open board. They open from a Tools menu in
  their own window (the calculator does already) and end by making a study ("Open as a board").
- **Solver and machine set-up** (where openEMS is, which GPU) is a Settings dialog with `--check`'s lines, not a
  panel.
- **Docking.** The two side columns and the drawer fold; that is all the arranging there is.

## Under the surface

- **A study model without Qt.** One object holds the board, the questions asked, each one's settings, its state
  and its runs, and emits changes. Widgets draw it and edit it; nothing else keeps state. `app.py` (2,150
  lines, where state lives in widgets today) becomes a shell of a few hundred lines and one module per region.
  The model is testable without a display, and kicad2ems-ipc can drive it.
- **Settings by level.** An option declares `level = 'basic' | 'more'` in the registry (most are 'more'); the
  inspector is generated from that, as the forms are from options today.
- **Picking as a contract.** An option may declare what it is picked from (`pick = 'net' | 'part' | 'pad' |
  'layer'`); the board view offers it, so a new engine's settings are pickable with no window code.
- **One style.** Spacing on a 4 px grid, two text sizes, one accent colour, one icon set, light and dark from
  the system: a single stylesheet with named values in place of per-widget styles.
- **Keyboard.** Ctrl+R runs, Ctrl+. stops, Ctrl+K opens a command box that finds any action, setting or example.
- **Qt Widgets stay.** The 3D view, the plots and the schematic are the costly parts and they are sound; the
  shell around them is what changes.

## Getting there from the present window

In an order where each step leaves a working window:

1. The study model, with the present widgets reading and writing it (no visible change; most of the risk).
   *Begun (2026-11-13): `study.StudyModel` holds what is asked, who answers, the Fields ticks, what cannot run
   here and each run's state, with no Qt, and the Study dock's list (`studytree.py`) is its view. Still in the
   widgets: every analysis's and the solvers' settings (the panels), the board and output folder, and the runs
   in progress (`app.py`).*
2. The questions list grouped, the engine on the row, the Solvers section folded into it (the registry's step 4).
   *Done.*
3. `level` on options; the inspector with "More settings". *Done for the solvers' settings (an option's `level`,
   a solver's `basic`, a search box). An analysis's panel is still its groups, the first one open.*
4. The fixed layout: the board in the middle, the drawer, the activity bar; docking removed. *Built, then taken back on the user's word (2026-11-12): the settings are a dock on the left under the questions, and every panel is a dock again (it moves, tabs, floats, closes), with the board over the Results and Run pages as a new window's arrangement. The layout sections above describe what was tried, not the window as it is.* *It had been done with these
   differences from the drawing above: the toolbar is the one it was (no header with the five steps); the drawer's
   tabs are the Results page and the Run page whole, not Plots, Report, Tables and Log; the status bar is the
   activity bar; Filter Synthesis is already a window of its own.* *With docks (2026-11-13, the user's choice
   among three mock-ups): Plots, Report, Tables and Log are docks of their own (Plots beside the board where the
   workspace has 1,400 px, else the first tab under it), Section is one too (under the board, so the plan it
   is picked on stays in view; the Viewer's buttons are Plan, 2D, 3D, Images), and the five steps are a bar
   under the toolbar, not in place of it: a toolbar of its own that drags to the bottom and hides.*
5. "Still needed", and the Run button's wording. *Done: `rf_needs` and an analysis's `missing` (kicad2ems API 2.9).*
6. The start page and the examples gallery. *Done (2026-11-13): `startpage.py`, a dock tabbed with the Viewer
   that has the workspace to itself while no board is chosen (the result pages step aside and come back).*
7. Picking on the board. *Done for nets and parts (an option's `pick`, kicad2ems API 2.11; the plan shows the
   board as drawn before any run). Not yet: a pad, a layer, and the pick in the 3D view.*
8. The Tools menu; the Circuit page's file buttons go.

Step 1 and 6 to 8 are about two weeks.
