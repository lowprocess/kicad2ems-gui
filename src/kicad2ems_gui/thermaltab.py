"""
The Thermal page: a board's steady temperature from what its parts dissipate (pcbqs's thermal tool,
`python -m pcbqs.thermal`): each part's temperature, each layer's hottest and mean, the heat given off through the
faces and the edges, and the maps.

The losses are the parts' own: typed as REF=W, or a Circuit run's (the Circuit page's latest, when none are typed;
its model's board then, unless one is named here). The tool runs as a separate process, as the PDN page's does, and
its options come from `python -m pcbqs.thermal --describe --json`; the form, the Study dock's settings and the run
are the PDN page's (pdntab.PdnTab), with this tool's command line, result and summary.

    describe()                       the tool's description (options), or None when it cannot run here
    thermal_argv(vals, board, out)   its command line
    load_result(out)                 what a run wrote in `out` ({method: summary}), or None
    summary_html(res)                the summary, as the page shows it
"""
import html, json, os

from .toolprocess import describe_tool
from .pdntab import pdn_argv, QS_PIP

ARGS = ('-m', 'pcbqs.thermal')
TOO_OLD = f"this pcbqs's thermal tool cannot describe its options (pcbqs 261111 or later): {QS_PIP}"


def describe(python=None):
    return describe_tool(python, ARGS, 'pcbqs', QS_PIP, too_old=TOO_OLD)[0]


def why_not(python=None):
    return describe_tool(python, ARGS, 'pcbqs', QS_PIP, too_old=TOO_OLD)[1]


def thermal_argv(vals, board, out, desc=None, python=None):
    """[python, -m, pcbqs.thermal, (board), --out, out, ...]: as the PDN page's (pdn_argv); board None when a
    circuit run names it."""
    return pdn_argv(vals, board, out, desc, python, module='pcbqs.thermal')


def circuit_run(folder):
    """A general circuit run's folder (model.json and circuit.json, python -m pcbqs.circuit): (folder, the board
    its model names or None), or None."""
    folder = str(folder or '')
    if not folder or not all(os.path.isfile(os.path.join(folder, f)) for f in ('model.json', 'circuit.json')):
        return None
    try:
        with open(os.path.join(folder, 'model.json')) as fh:
            board = (json.load(fh).get('board') or {}).get('file')
    except (OSError, ValueError):
        board = None
    return folder, (board if board and os.path.isfile(board) else None)


def load_result(out):
    """{method: its summary} ('grid', 'mesh'; with both, 'difference' too) from <out>/thermal.json, with '_dir'."""
    path = os.path.join(out or '', 'thermal.json')
    if not os.path.isfile(path):
        return None
    with open(path) as fh:
        res = json.load(fh)
    if 'method' in res:                                     # one solver
        res = {res['method']: res}
    res['_dir'] = out
    return res


def _methods(res):
    return {k: v for k, v in res.items() if k in ('grid', 'mesh')}


def summary_html(res, width=860):
    """The parts' temperatures (each solver's), the layers', the heat balance, the notes and the maps."""
    e = html.escape
    ms = _methods(res)
    if not ms:
        return '<p>No thermal result.</p>'
    first = next(iter(ms.values()))
    hot = max(m['hottest_C'] for m in ms.values())
    h = [f"<h3>Hottest copper {hot:.1f} °C</h3>"]
    src = os.path.basename(first.get('board') or '')
    if first.get('circuit'):
        src += f"; losses of circuit case {e(str(first.get('case')))} ({e(os.path.basename(first['circuit'].rstrip('/')))})"
    h.append(f"<p>{e(src)}. {first['heat_in_W']:.3g} W in, {first['heat_out_W']:.3g} W given off "
             f"({first.get('heat_out_edges_W', 0):.3g} W of it through the edges); air {first['ambient_C']:g} °C, "
             f"films {first['film_W_m2K'][1]:g} / {first['film_W_m2K'][0]:g} W/m²K top / bottom, "
             f"{first.get('edge_film_W_m2K', 0):g} at the edges.</p>")
    names = list(ms)
    h.append("<table border=0 cellspacing=6><tr><th align=left>part</th><th>W</th>"
             + ''.join(f"<th>board °C ({n})</th>" for n in names) + "<th>part °C</th></tr>")
    for ref, p in sorted(first['parts'].items(), key=lambda kv: -kv[1]['part_C']):
        h.append(f"<tr><td>{e(ref)}</td><td align=right>{p['power_W']:.3g}</td>"
                 + ''.join(f"<td align=right>{ms[n]['parts'][ref]['board_C']:.1f}</td>" for n in names if ref in ms[n]['parts'])
                 + f"<td align=right><b>{p['part_C']:.1f}</b></td></tr>")
    h.append("</table>")
    h.append("<h4>Layers</h4><table border=0 cellspacing=6><tr><th align=left>layer</th><th>hottest °C</th>"
             "<th>mean °C</th></tr>")
    for lay, v in first['layers'].items():
        h.append(f"<tr><td>{e(lay)}</td><td align=right>{v['hottest_C']:.1f}</td><td align=right>{v['mean_C']:.1f}</td></tr>")
    h.append("</table>")
    d = res.get('difference')
    if d:
        h.append(f"<p>Mesh against grid: parts within {max(abs(v) for v in d['parts_K'].values()):.2f} K, "
                 f"the maps within {d['largest_K']:.2f} K.</p>")
    notes = list(dict.fromkeys(first.get('notes') or []))
    if notes:
        h.append("<h4>Notes</h4><ul>" + ''.join(f"<li>{e(n)}</li>" for n in notes) + "</ul>")
    figs = [m.get('figure') for m in ms.values()] + (['thermal-compare.png'] if d else [])
    for f in figs:
        p = os.path.join(res.get('_dir') or '', f or '')
        if f and os.path.isfile(p):
            h.append(f"<p><img src='{e(p)}' width={width}></p>")
    s = first.get('seconds', {})
    h.append(f"<p style='color:gray'>{', '.join(f'{n}: {ms[n]['unknowns']:,} unknowns at {ms[n]['size_mm']:g} mm' for n in names)}; "
             + ', '.join(f"{k} {v:g} s" for k, v in s.items()) + "</p>")
    return '\n'.join(h)


try:
    from .pdntab import PdnTab
except ImportError:                                     # pragma: no cover
    PdnTab = object


class ThermalTab(PdnTab):
    """The PDN page's form and run, for pcbqs.thermal."""
    KIND = 'thermal'
    OPEN = ('Heat',)
    EMPTY = ("Tick Thermal under Analyses, and Run: the parts' losses typed under Heat (REF=W), or the Circuit "
             "page's latest run when none are. The parts' temperatures and the maps come here.")

    def __init__(self, win=None):
        from . import pdntab as P                           # PdnTab's __init__, with this tool's description
        P.QWidget.__init__(self)
        self.win, self.proc, self.out, self.result = win, None, None, None
        self.desc = describe()
        lay = P.QHBoxLayout(self)
        self.split = P.QSplitter(P.Qt.Horizontal)
        lay.addWidget(self.split)
        self.split.addWidget(self._form())
        self.split.addWidget(self._views())
        self.split.setSizes([380, 900])
        if self.desc is None:
            self.split.widget(0).setEnabled(False)
            self.say(why_not() or f"the thermal tool cannot run here: {QS_PIP}")

    def _form(self):
        left = super()._form()
        self.outdir.setPlaceholderText('thermal_<what> beside the board')
        self.run_btn.setToolTip("the board's steady temperature from its parts' losses")
        if self.desc is None:
            self.status.setText(why_not() or f"the thermal tool cannot run here: {QS_PIP}")
        loss = self.w.get('loss')
        if loss is not None:
            loss.setPlaceholderText("Q1=0.35\nL1=0.48\n(none: the Circuit page's latest run)")
        return left

    def extra_tabs(self):
        return [self.zplot, self.maps, self.log]

    def latest_circuit(self):
        """The Circuit page's latest run, when it is a general circuit's (model.json, circuit.json)."""
        page = getattr(self.win, 'circuit', None) if self.win is not None else None
        return circuit_run(getattr(page, 'out', None))

    def plan(self):
        """(values, board or None, a name for its folder) of a run as the settings stand, or why it cannot run."""
        vals = self.values()
        typed = [s for s in str(vals.get('loss') or '').replace(',', '\n').splitlines() if s.strip()]
        circuit = str(vals.get('circuit') or '').strip()
        run = circuit_run(circuit) if circuit else None
        if circuit and run is None:
            return f'{circuit}: not a circuit run (model.json and circuit.json)'
        if not circuit and not typed:
            run = self.latest_circuit()
            if run is None:
                return "give the parts' losses (REF=W), or run the Circuit page first"
            vals = dict(vals, circuit=run[0])
        board = self.board.text().strip() or (run[1] if run and run[1] else None) or self.board_path() or None
        if board and not os.path.exists(board):
            return f'{board}: no such board'
        if not board and not (run and run[1]):
            return 'choose a board first (here, or in the main settings)'
        name = (str(vals.get('case') or '').strip() or (os.path.basename(run[0].rstrip('/')) if run else 'losses'))
        return vals, board, name

    def start(self, preview=False):
        if self.proc is not None or preview:
            return
        p = self.plan()
        if isinstance(p, str):
            self.status.setText(p)
            return
        vals, board, name = p
        out = self.outdir.text().strip() or self.default_out(board, name)
        self.out = os.path.abspath(out)
        argv = thermal_argv(vals, board, self.out, self.desc)
        self.log.clear()
        self.say('$ python ' + ' '.join(argv[1:]))
        self._front(self.log)
        self.run_btn.setEnabled(False); self.stop_btn.setEnabled(True); self.busy.show()
        self.status.setText('running…')
        from .toolprocess import run_tool
        run_tool(self, argv, self._stdout, self._finished)

    def _stdout(self):
        text = bytes(self.proc.readAllStandardOutput()).decode(errors='replace')
        for line in text.splitlines():
            if 'Warning' in line:
                continue
            self.say(line)
            if line.startswith(('thermal ', 'losses of', 'results in')) or ' W into the board' in line:
                self.status.setText(line.strip()[:160])

    def _finished(self, code, _status=None):
        self.proc = None
        self.run_btn.setEnabled(True); self.stop_btn.setEnabled(False); self.busy.hide()
        try:
            res = load_result(self.out) if code == 0 else None
        except (OSError, ValueError) as exc:
            self.say(str(exc)); res = None
        if res is None:
            self.status.setText(f'the run failed (exit {code}): see the Log')
            self.summary.setHtml(self.failed_html(code))
            self._front(self.summary)
            return
        self.show_result(res)
        hot = max(m['hottest_C'] for m in _methods(res).values())
        self.status.setText(f"done: hottest copper {hot:.1f} °C")
        self._front(self.summary)

    def show_result(self, res):
        self.result = res
        self.summary.setHtml(summary_html(res, width=max(400, self.summary.viewport().width() - 40)))
        if self.tabs.indexOf(self.maps) >= 0:
            ms = _methods(res)
            self.maps.show_images([os.path.join(res['_dir'], m['figure']) for m in ms.values() if m.get('figure')])
