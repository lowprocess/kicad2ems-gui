"""
The PDN page: a power rail's DC drop and PDN impedance (pcbqs's power-integrity tool, `python -m pcbqs.pdn`): the
rail, its loads and the regulator on the left; the impedance each load sees, the drop and current maps, the summary
(the rail tree, each load's voltage, the plane pairs, each part's connection) and the log on the right.

In the window the page is the summary alone (settings_panel): the settings are in the Study dock, the impedance on
the Results page (curves.py), the maps in the Viewer (the tool writes them as field dumps, pcbqs 261111 on) and the
log on the Run page; a run that failed says why in the summary.

The tool runs as a separate process, as kicad2ems runs and dfsynth do: the page follows its output and reads what it
wrote when it ends (<out>/pdn.json, its figures). Its options come from `python -m pcbqs.pdn --describe --json`, so
the page never imports pcbqs.

    describe()                 the tool's description (options), or None when it cannot run here
    pdn_argv(vals, board, out) its command line for the page's settings
    load_result(out)           what a run wrote in `out`, or None
    summary_html(res)          the summary of a result, as the page shows it
"""
import html, json, os, re, sys
import numpy as np

from .toolprocess import describe_tool, run_tool

QS_PIP = "python -m pip install 'kicad2ems[qs]' (pcbqs, with its power-integrity tool)"


def describe(python=None):
    """{'options': [{key, flag, kind, default, help, group}]} from the tool, or None (why_not() says why)."""
    return describe_tool(python, ('-m', 'pcbqs.pdn'), 'pcbqs', QS_PIP)[0]


def why_not(python=None):
    return describe_tool(python, ('-m', 'pcbqs.pdn'), 'pcbqs', QS_PIP)[1]


def pdn_argv(vals, board, out, desc=None, python=None):
    """[python, -m, pcbqs.pdn, board, --out, out, ...] for the page's values {key: text or bool}: an option left
    empty (or at its default) is not passed; a list ('load', 'cap') is lines, or REF=... items joined by commas
    (a comma inside one, CA1=47e-6,0.02,1e-9, stays in it)."""
    opts = {o['key']: o for o in (desc or {}).get('options', [])}
    argv = [python or sys.executable, '-m', 'pcbqs.pdn', board, '--out', out]
    for key, v in vals.items():
        o = opts.get(key)
        if o is None:
            continue
        if o['kind'] == 'bool':
            if v:
                argv.append(o['flag'])
        elif o['kind'] == 'list':
            for item in [s.strip() for s in re.split(r'\n|,(?=\s*[^\s,=]+\s*=)', str(v or '')) if s.strip()]:
                argv += [o['flag'], item]
        else:
            s = str(v).strip()
            if s and s != str(o['default']):
                argv += [o['flag'], s]
    return argv


def load_result(out):
    path = os.path.join(out or '', 'pdn.json')
    if not os.path.isfile(path):
        return None
    with open(path) as fh:
        res = json.load(fh)
    res['_dir'] = out
    return res


def _mv(v):
    return f"{v * 1e3:.2f}"


def _hz(f):
    return f"{f / 1e9:.3g} GHz" if f >= 1e9 else (f"{f / 1e6:.3g} MHz" if f >= 1e6 else f"{f / 1e3:.3g} kHz")


def _ohm(z):
    return f"{z:.3g} Ω" if z >= 1 else f"{z * 1e3:.3g} mΩ"


def summary_html(res):
    """The summary of a result: the rail tree, the loads, the series parts, the plane pairs, the parts, the notes."""
    e = html.escape
    h = [f"<h3>{e(res['rail'])}: {res['volts']:g} V</h3>"]
    if res.get('assumed_loads'):
        h.append("<p style='color:#b35900'>The loads' currents are assumed (shared by pad count), not known.</p>")
    h.append(f"<p>Rail tree: {', '.join(e(n) for n in res['nets'])}; source {', '.join(e(s) for s in res['source'])}; "
             f"{res['loss_W'] * 1e3:.1f} mW in the copper.</p>")
    if res['tree']:
        h.append("<table border=0 cellspacing=6><tr><th align=left>series part</th><th>kind</th><th>R (Ω)</th>"
                 "<th>L (µH)</th><th>current (A)</th><th>drop (mV)</th><th align=left>between</th></tr>")
        for t in res['tree']:
            s = res['series'].get(t['ref'], {})
            L = f"{t['L'] * 1e6:.3g}" if t.get('L') else ''          # a followed series (filter) inductor
            h.append(f"<tr><td>{e(t['ref'])}</td><td>{e(t['kind'])}{' (DCR assumed)' if t['defaulted'] else ''}</td>"
                     f"<td align=right>{t['R']:.3g}</td><td align=right>{L}</td><td align=right>{s.get('I', 0):.3g}</td>"
                     f"<td align=right>{_mv(s.get('drop', 0))}</td><td>{e(t['a'])} → {e(t['b'])}</td></tr>")
        h.append("</table>")
    h.append("<h4>Loads at DC</h4><table border=0 cellspacing=6><tr><th align=left>load</th><th>I (A)</th><th>sees (V)</th>"
             "<th>drop (mV)</th><th>supply side</th><th>ground rise</th></tr>")
    for r, l in sorted(res['loads'].items(), key=lambda kv: -kv[1]['drop']):
        h.append(f"<tr><td>{e(r)}</td><td align=right>{l['I']:.3g}</td><td align=right>{l['V']:.4f}</td>"
                 f"<td align=right><b>{_mv(l['drop'])}</b></td><td align=right>{_mv(l['power_drop'])}</td>"
                 f"<td align=right>{_mv(l['ground_rise'])}</td></tr>")
    h.append("</table>")
    vp = res['vias']['power'][:5]
    if vp:
        h.append("<p>Hottest supply vias: " + ', '.join(f"{v['I']:.2f} A at ({v['x']:.1f}, {v['y']:.1f})" for v in vp) + "</p>")
    p = res.get('pdn')
    if p:
        h.append("<h4>PDN impedance" + (f" (target {p['target'] * 1e3:.1f} mΩ)" if p.get('target') else '') + "</h4>")
        h.append("<table border=0 cellspacing=6><tr><th align=left>plane pair</th><th>d (mm)</th><th>εr</th>"
                 "<th>area (mm²)</th><th>C (nF)</th></tr>")
        for c in p['cavities']:
            h.append(f"<tr><td>{e(c['rail'])} over {e(c['ground'])}</td><td align=right>{c['d']:.3g}</td>"
                     f"<td align=right>{c['er']:.3g}</td><td align=right>{c['area']:.0f}</td>"
                     f"<td align=right>{c['C'] * 1e9:.3g}</td></tr>")
        h.append("</table>")
        for r, z in p['z'].items():
            t = z.get('target', p.get('target'))          # per load (--load-target), or none (--no-target)
            if t:
                bands = '; '.join(f"{_hz(a)} – {_hz(b)}" for a, b in z['over']) or 'never'
                own = f" ({_ohm(t)})" if t != p.get('target') else ''
                h.append(f"<p>{e(r)}: over the target{own} {bands}; at most {_ohm(max(z['mag']))}.</p>")
            else:
                h.append(f"<p>{e(r)}: no target; at most {_ohm(max(z['mag']))}.</p>")
        h.append("<table border=0 cellspacing=6><tr><th align=left>part</th><th>role</th><th>element</th>"
                 "<th>mount (nH)</th><th align=left>connection</th></tr>")
        for n, i in sorted(p['parts'].items(), key=lambda kv: (kv[1]['role'], kv[0])):
            el = i['element']
            txt = (f"{el['C'] * 1e6:.3g} µF, {el.get('ESR', 0) * 1e3:.3g} mΩ, {el.get('ESL', 0) * 1e9:.2f} nH"
                   if 'C' in el else (f"{el.get('R', 0) * 1e3:.3g} mΩ, {el.get('L', 0) * 1e9:.3g} nH" if el else ''))
            if i.get('defaulted'):
                txt += ' (ESR/ESL by package)'
            conn = f"node {i['node']}" if i['node'] else i['rail']
            h.append(f"<tr><td>{e(n)}</td><td>{e(i['role'])}</td><td>{e(txt)}</td>"
                     f"<td align=right>{i['mount_nH']:.2f}</td><td>{e(conn)}</td></tr>")
        h.append("</table>")
    if res.get('notes'):
        h.append("<h4>Notes</h4><ul>" + ''.join(f"<li>{e(n)}</li>" for n in res['notes']) + "</ul>")
    s = res.get('seconds', {})
    h.append(f"<p style='color:gray'>{res['vertices']['power']:,} + {res['vertices']['ground']:,} DC vertices; "
             + ', '.join(f"{k} {v} s" for k, v in s.items()) + "</p>")
    return '\n'.join(h)


try:                                                    # the page itself (Qt); the helpers above need none
    import pyqtgraph as pg
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QFormLayout, QSplitter, QLineEdit, QPushButton,
                                   QPlainTextEdit, QTextBrowser, QTabWidget, QCheckBox, QScrollArea, QFileDialog,
                                   QProgressBar, QLabel)
    from PySide6.QtGui import QFontDatabase
    from .panels import Section, ImagePanel
except ImportError:                                     # pragma: no cover
    QWidget = object

COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']


class FitImages(ImagePanel if QWidget is not object else object):
    """The maps, each scaled to the panel's width (the plots are two maps wide), again when it is resized."""

    def show_images(self, paths):
        super().show_images(paths)
        self._fit()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit()

    def _fit(self):
        from PySide6.QtGui import QPixmap
        w = max(200, self.width() - 30)
        for k in range(self.inner.count()):
            lab = self.inner.itemAt(k).widget()
            if isinstance(lab, QLabel) and lab.toolTip():
                lab.setPixmap(QPixmap(lab.toolTip()).scaledToWidth(w, Qt.SmoothTransformation))


class PdnTab(QWidget):
    """The tool's settings on the left; the impedance, the maps, the summary and the log on the right. In the
    window the settings are in its Study dock instead (settings_panel) and its Run starts the tool."""
    _panel = None                                       # the settings, once moved out of the page
    KIND = 'pdn'                                        # its run folders' (runfolders.tool_dir)

    def __init__(self, win=None):
        super().__init__()
        self.win, self.proc, self.out, self.result = win, None, None, None
        self.desc = describe()
        lay = QHBoxLayout(self)
        self.split = QSplitter(Qt.Horizontal)
        lay.addWidget(self.split)
        self.split.addWidget(self._form())
        self.split.addWidget(self._views())
        self.split.setSizes([380, 900])
        if self.desc is None:
            self.split.widget(0).setEnabled(False)
            self.say(why_not() or f"the PDN tool cannot run here: {QS_PIP}")

    # ---- the settings ----
    def _form(self):
        self.w = {}
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        files = QWidget()
        f = QFormLayout(files)
        f.setContentsMargins(0, 0, 0, 0)
        self.board = QLineEdit()
        self.board.setPlaceholderText("the main settings' board")
        self.board.setToolTip('.kicad_pcb (or a run\'s <name>_board.json); empty: the board of the main settings')
        b = QPushButton('…'); b.setFixedWidth(28); b.clicked.connect(self._browse)
        row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.addWidget(self.board, 1); rl.addWidget(b)
        f.addRow('Board', row)
        self.outdir = QLineEdit()
        self.outdir.setPlaceholderText('pdn_<rail> beside the board')
        f.addRow('Output folder', self.outdir)
        self._files = Section('Board', files, True)
        v.addWidget(self._files)
        groups = {}
        for o in (self.desc or {}).get('options', []):
            groups.setdefault(o['group'], []).append(o)
        for g, opts in groups.items():
            inner = QWidget()
            fl = QFormLayout(inner)
            fl.setContentsMargins(0, 0, 0, 0)
            for o in opts:
                if o['kind'] == 'bool':
                    wid = QCheckBox(o['help'])
                    wid.setChecked(bool(o['default']))
                elif o['kind'] == 'list':
                    wid = QPlainTextEdit()
                    wid.setPlaceholderText('U21=2\nU14=1.5')
                    wid.setFixedHeight(70)
                else:
                    wid = QLineEdit()
                    wid.setPlaceholderText(str(o['default']) if o['default'] not in ('', None) else '')
                wid.setToolTip(f"{o['flag']}: {o['help']}")
                self.w[o['key']] = wid
                fl.addRow(o['key'].replace('_', ' ').capitalize() if o['kind'] != 'bool' else '', wid)
            v.addWidget(Section(g, inner, g in ('Rail',)))
        v.addStretch(1)
        foot = QWidget()
        fv = QVBoxLayout(foot)
        fv.setContentsMargins(6, 4, 6, 6)
        btns = QHBoxLayout()
        self.run_btn = QPushButton('Run')
        self.run_btn.setToolTip('the rail tree, its DC drop, then its PDN impedance')
        self.run_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton('Stop')
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        btns.addWidget(self.run_btn); btns.addWidget(self.stop_btn)
        fv.addLayout(btns)
        self.busy = QProgressBar(); self.busy.setRange(0, 0); self.busy.hide()
        fv.addWidget(self.busy)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        fv.addWidget(self.status)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(box)
        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(0)
        lv.addWidget(sc, 1); lv.addWidget(foot)
        self._form_scroll, self._form_foot, self._form_left = sc, foot, left
        return left

    def run_buttons(self):
        """The page's own Run and Stop: hidden once the window's toolbar runs the tool."""
        return [self.run_btn, self.stop_btn]

    def settings_panel(self):
        """The settings out of the page, for the window's Study dock: the sections, then the status line. The
        page keeps its results and takes the whole of itself for them. Run and Stop are the window's then; the
        board is the study's unless one is named here."""
        if self._panel is None:
            box = self._form_scroll.takeWidget()
            self._panel = QWidget()
            v = QVBoxLayout(self._panel)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            v.addWidget(box)
            v.addWidget(self._form_foot)
            for b in self.run_buttons():
                b.hide()
            self._form_left.hide()
            self.board.setPlaceholderText("the study's board")
            self.board.setToolTip('.kicad_pcb (or a run\'s <name>_board.json); empty: the board under Board, above')
            self._files.title = 'Files'
            self._files.set_count(0)
            self.outdir.setPlaceholderText('a folder per run, in the output folder')
            self.summary_only()
        return self._panel

    def summary_only(self):
        """The page as the window has it: the summary. The other tabs' content is on the Results page, in the
        Viewer and on the Run page (their widgets stay, filled or not, for the page used alone)."""
        for w in list(self.extra_tabs()):
            i = self.tabs.indexOf(w)
            if i >= 0:
                self.tabs.removeTab(i)
        self.tabs.tabBar().hide()
        self.tabs.setDocumentMode(True)
        self.summary.setPlaceholderText(self.EMPTY)

    EMPTY = ("Tick Power integrity under Analyses, name the rail and its loads, and Run. The summary comes here; "
             "the impedance each load sees is on the Results page and the drop and current maps are in the Viewer.")

    def extra_tabs(self):
        return [self.zplot, self.maps, self.log]

    def _front(self, w):
        """A tab in front, when the page still has it."""
        if self.tabs.indexOf(w) >= 0:
            self.tabs.setCurrentWidget(w)

    def default_out(self, board, name, preview=False):
        """Where a run goes when no folder is named: in the window a folder per run under its output folder
        (MainWindow.tool_out), alone <kind>_<name> beside the board, as before."""
        if self.win is not None and hasattr(self.win, 'tool_out'):
            return self.win.tool_out(self.KIND, board, name, preview)
        base = os.path.join(os.path.dirname(os.path.abspath(board)),
                            f"{self.KIND}_" + ''.join(c if c.isalnum() else '_' for c in name))
        return os.path.join(base, 'preview') if preview else base

    def failed_html(self, code):
        """A failed run in the summary: the tool's own error lines (else its last ones), where the log is."""
        lines = [l for l in self.log.toPlainText().splitlines() if l.strip()]
        errs = [l for l in lines if 'error' in l.lower() or l.startswith(('Traceback', 'RuntimeError', 'ValueError'))]
        show = (errs or lines)[-6:]
        where = 'the Run page (Log of)' if self.tabs.indexOf(self.log) < 0 else 'the Log tab'
        return (f"<h3>The run failed (exit {code})</h3><pre>{html.escape(chr(10).join(show))}</pre>"
                f"<p style='color:gray'>The whole log: {where}.</p>")

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, 'Board', '', 'KiCad board (*.kicad_pcb);;kicad2ems board (*.json)')
        if p:
            self.board.setText(p)

    def values(self):
        out = {}
        for k, wid in self.w.items():
            if isinstance(wid, QCheckBox):
                out[k] = wid.isChecked()
            elif isinstance(wid, QPlainTextEdit):
                out[k] = wid.toPlainText()
            else:
                out[k] = wid.text()
        return out

    def set_values(self, vals):
        for k, v in vals.items():
            wid = self.w.get(k)
            if wid is None:
                continue
            if isinstance(wid, QCheckBox):
                wid.setChecked(bool(v))
            elif isinstance(wid, QPlainTextEdit):
                wid.setPlainText('\n'.join(v) if isinstance(v, list) else str(v))
            else:
                wid.setText('' if v is None else str(v))

    def board_path(self):
        p = self.board.text().strip()
        if not p and self.win is not None:
            try:
                p = self.win.setup.values().get('board') or ''
            except Exception:
                p = ''
        return p

    # ---- the views ----
    def _views(self):
        tabs = QTabWidget()
        self.zplot = pg.PlotWidget(title='Impedance each load sees')
        self.zplot.setLogMode(x=True, y=True)
        for ax in ('bottom', 'left'):                   # log axes: decades as they are, no SI rescaling
            self.zplot.getAxis(ax).enableAutoSIPrefix(False)
        self.zplot.setLabel('bottom', 'Hz'); self.zplot.setLabel('left', '|Z| (Ω)')
        self.zplot.showGrid(x=True, y=True, alpha=0.3)
        self.zplot.addLegend(offset=(-10, 10))
        self.maps = FitImages('the drop and current maps of a run')
        self.summary = QTextBrowser()
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(5000)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        tabs.addTab(self.summary, 'Summary')
        tabs.addTab(self.zplot, 'Impedance')
        tabs.addTab(self.maps, 'DC maps')
        tabs.addTab(self.log, 'Log')
        self.tabs = tabs
        return tabs

    def say(self, text):
        self.log.appendPlainText(text)

    # ---- a run ----
    def start(self):
        if self.proc is not None:
            return
        vals = self.values()
        if getattr(self, '_transferred_unknown_voltage', False) and not str(vals.get('volts','')).strip():
            self.status.setText('Enter the supply voltage for the transferred input rail before Run')
            return
        board = self.board_path()
        if not board or not os.path.exists(board):
            self.status.setText('choose a board first (here, or in the main settings)')
            return
        if not vals.get('rail'):
            self.status.setText('name the rail (its net)')
            return
        out = self.outdir.text().strip() or self.default_out(board, vals['rail'])
        self.out = os.path.abspath(out)
        argv = pdn_argv(vals, board, self.out, self.desc)
        self.log.clear()
        self.say('$ python ' + ' '.join(argv[1:]))
        self._front(self.log)
        self.run_btn.setEnabled(False); self.stop_btn.setEnabled(True); self.busy.show()
        self.status.setText('running…')
        run_tool(self, argv, self._stdout, self._finished)

    def stop(self):
        if self.proc is not None:
            self.proc.kill()

    def _stdout(self):
        text = bytes(self.proc.readAllStandardOutput()).decode(errors='replace')
        for line in text.splitlines():
            if 'RuntimeWarning' in line:
                continue
            self.say(line)
            if line.startswith('pdn:'):
                self.status.setText(line[4:].strip()[:160])

    def _finished(self, code, _status=None):
        self.proc = None
        self.run_btn.setEnabled(True); self.stop_btn.setEnabled(False); self.busy.hide()
        res = load_result(self.out) if code == 0 else None
        if res is None:
            self.status.setText(f'the run failed (exit {code}): see the Log')
            self.summary.setHtml(self.failed_html(code))
            self._front(self.summary)
            return
        self.show_result(res)
        self.status.setText(f"done in {res['seconds'].get('total', '?')} s")
        self._front(self.summary)

    def show_result(self, res):
        self.result = res
        self.summary.setHtml(summary_html(res))
        if self.tabs.indexOf(self.zplot) < 0:               # the window's page: the Results page and the Viewer
            return                                          # have the curves and the maps
        self.maps.show_images([os.path.join(res['_dir'], f['file']) for f in res.get('figures', []) if f['side'] != 'pdn'])
        self.zplot.clear()
        p = res.get('pdn')
        if not p:
            return
        f = np.asarray(p['f'])
        shown = []
        for k, (r, z) in enumerate(p['z'].items()):
            c = COLORS[k % len(COLORS)]
            self.zplot.plot(f, np.asarray(z['mag']), pen=pg.mkPen(c, width=2), name=r)
            self.zplot.plot(f, np.asarray(z['bare']), pen=pg.mkPen(c, width=1, style=Qt.DotLine))
            shown.append(np.asarray(z['mag'], float))
        targets = sorted({t for t in [p.get('target'), *[z.get('target') for z in p['z'].values()]] if t})
        for t in targets:
            self.zplot.plot([f[0], f[-1]], [t] * 2, pen=pg.mkPen('r', width=1), name=f"target {t * 1e3:.1f} mΩ")
        if shown:                                          # the loaded curves set the range: a bare-planes curve
            data = np.concatenate(shown)                   # reaching 1e11 ohm (a tiny cavity) runs off the top (I6)
            data = data[np.isfinite(data) & (data > 0)]
            if len(data):
                lo, hi = min([data.min(), *targets]), max([data.max(), *targets])
                self.zplot.setYRange(np.log10(lo / 3), np.log10(hi * 3), padding=0)
