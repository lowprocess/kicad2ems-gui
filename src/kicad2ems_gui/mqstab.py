"""Near-field page: the MQS CLI owns options and physics; Qt runs it in a subprocess.

In the window the page is the summary alone, as the PDN page: the layout, the mesh and the fields are the Viewer's
(the same views, the same folder), the spectrum is on the Results page and the log on the Run page."""
import html
import json
import os
from pathlib import Path

from .pdntab import PdnTab, pdn_argv, QS_PIP
from .toolprocess import describe_tool, run_tool
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QTabWidget,
                               QTextBrowser, QPlainTextEdit, QPushButton)
import pyqtgraph as pg


def describe():
    """The near-field tool's description, or None (why_not() says why)."""
    return describe_tool(None,('-m','pcbqs.mqs'),'pcbqs',QS_PIP)[0]


def why_not():
    return describe_tool(None,('-m','pcbqs.mqs'),'pcbqs',QS_PIP)[1]


def mqs_argv(vals,board,out,desc,python=None,preview=False):
    argv=pdn_argv(vals,board,out,desc,python)
    argv[2]='pcbqs.mqs'
    if preview:argv.append('--preview')
    return argv


def converter_choices(candidates):
    """[(label, values)] from `pcbqs.mqs --list-converters`: one choice per converter and input net (I5: a
    regulator with several candidate inputs, VCC/VDD/VDRV on Jetson's bucks, would otherwise stop the run).
    values: the form's converter, vin and capacitors."""
    out=[]
    for c in candidates:
        for i in c.get('inputs',[]):
            caps=i.get('capacitors',[])
            label=(f"{c['converter']}: {i['vin']} (inductor {c.get('inductor','?')}, switch {c.get('switch','?')}; "
                   f"{len(caps)} capacitor{'s' if len(caps)!=1 else ''}: {', '.join(caps[:6])}{'…' if len(caps)>6 else ''})")
            out.append((label,dict(converter=c['converter'],vin=i['vin'],capacitors=','.join(caps))))
    return out


def load_result(out,preview=False):
    path=Path(out)/('mqs-preview.json' if preview else 'mqs.json')
    if not path.is_file():return None
    res=json.loads(path.read_text())
    if res.get('format')!=1:raise ValueError('Unsupported MQS result format')
    res['_dir']=str(out)
    return res


def summary_html(res):
    s=res['selection'];e=html.escape
    if res.get('preview'):
        rows=''.join(f"<tr><td>{e(l)}</td><td>{v['triangles']}</td><td>{v['max_edge_mm']:.3g}</td><td>{v['min_angle_deg']:.2f}</td></tr>" for l,v in res['layers'].items())
        return f"<h3>{e(s['converter'])}: mesh preview</h3><p>{res['triangles']:,} triangles. No matrix fill or solve.</p><table cellspacing=6><tr><th>Layer</th><th>Triangles</th><th>Max edge (mm)</th><th>Min angle (°)</th></tr>{rows}</table>"

    h=[f"<h3>{e(s['converter'])}: {e(s['vin'])} / {e(s['ground'])}</h3>",
       f"<p>Input capacitors: {e(', '.join(s['capacitors']))}; {res['triangles']:,} triangles.</p>",
       '<table cellspacing=6><tr><th>Hz</th><th>Peak A</th><th>Copper R (mΩ)</th><th>Copper L (nH)</th><th>Peak H (A/m)</th></tr>']
    for f,a,r,l,hp in zip(res['frequencies_Hz'],res['harmonic_peak_A'],res['copper_R_ohm'],res['copper_L_H'],res['peak_H_Am']):
        h.append(f'<tr><td>{f:g}</td><td>{a:.4g}</td><td>{r*1e3:.4g}</td><td>{l*1e9:.4g}</td><td>{max(hp):.4g}</td></tr>')
    h.append('</table><h4>Model assumptions</h4><ul>')
    h.extend(f'<li>{e(note)}</li>' for note in res.get('notes',[]))
    h.append('</ul>')
    return ''.join(h)


class MqsTab(PdnTab):
    """Reuse the PDN option form and process controls, with MQS-specific results."""
    KIND='mqs'
    EMPTY=("Tick Near field under Analyses, pick the converter (Find converters lists them) and Run. The summary "
           "comes here; the layout, the mesh and the fields are in the Viewer and the spectrum is on the Results page.")

    def __init__(self,win=None):
        QWidget.__init__(self)
        self.win,self.proc,self.out,self.result=win,None,None,None
        self._preview=False
        self.desc=describe()
        layout=QHBoxLayout(self);self.split=QSplitter(Qt.Horizontal);layout.addWidget(self.split)
        self.split.addWidget(self._form());self.split.addWidget(self._views());self.split.setSizes([380,900])
        from .panels import Section
        for section in self.findChildren(Section):
            if section.title in ('Converter', 'Operating point'):
                section.set_expanded(True)
        self.outdir.setPlaceholderText('mqs_<converter> beside the board')
        self.preview_btn=QPushButton('Preview mesh')
        self.preview_btn.clicked.connect(self.preview)
        self.preview_btn.setEnabled('preview' in (self.desc or {}).get('features',[]))
        self.preview_btn.setToolTip('Build the selected crop mesh without filling matrices or solving')
        self.run_btn.parentWidget().layout().insertWidget(0,self.preview_btn)
        self.find_btn=QPushButton('Find converters')
        self.find_btn.setToolTip('List the board\'s converters and their candidate input nets, and pick one')
        self.find_btn.clicked.connect(self.find_converters)
        self.find_btn.setEnabled(self.desc is not None)
        self.run_btn.parentWidget().layout().insertWidget(0,self.find_btn)
        self._finding=None
        self.run_btn.setToolTip('Solve the converter input loop and scan its magnetic near field')
        if self.desc is None:
            self.run_btn.setEnabled(False);self.say(why_not())

    def run_buttons(self):
        return [self.run_btn,self.stop_btn,self.preview_btn]          # Find converters stays: it fills the form

    def extra_tabs(self):
        return [self.layout,self.spectrum,self.maps,self.log]

    def summary_only(self):
        """The summary alone; the hand-over of the input rail goes with the settings (the Study dock), and the
        Viewer shows a finished run's fields without being asked."""
        super().summary_only()
        self.open_btn.hide()
        self.pdn_btn.setText('Copy the input rail to Power integrity')
        self.pdn_btn.setToolTip("The converter's input net, its ground and its voltage into Power integrity's "
                                "settings, after a run or a mesh preview; the source and the loads are yours to give")
        self._form_foot.layout().insertWidget(0,self.pdn_btn)

    def _views(self):
        self.tabs=QTabWidget()
        from .planview import PlanView
        self.layout=PlanView()
        from .fieldtab import FieldsTab
        self.summary=QTextBrowser();self.maps=FieldsTab(self.win)
        self.spectrum=pg.PlotWidget(title='Peak magnetic field per harmonic')
        self.spectrum.setLogMode(x=True,y=True)
        self.spectrum.setLabel('bottom','Hz');self.spectrum.setLabel('left','Peak |H|, A/m')
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(5000)
        self.tabs.addTab(self.layout,'Layout / mesh')
        self.tabs.addTab(self.summary,'Summary');self.tabs.addTab(self.spectrum,'Spectrum')
        self.tabs.addTab(self.maps,'Field overlay');self.tabs.addTab(self.log,'Log')
        box=QWidget();layout=QVBoxLayout(box);layout.addWidget(self.tabs)
        self.open_btn=QPushButton('Open fields in Viewer');self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self.open_fields);layout.addWidget(self.open_btn)
        self.pdn_btn=QPushButton('Use board and rail in Power Integrity')
        self.pdn_btn.clicked.connect(self.open_pdn);self.pdn_btn.setEnabled(False);layout.addWidget(self.pdn_btn)
        return box

    def preview(self):
        self.start(preview=True)

    @staticmethod
    def same_board(a,b):
        return bool(a) and bool(b) and os.path.abspath(a)==os.path.abspath(b)

    def find_converters(self):
        """Run `pcbqs.mqs --list-converters` and offer each converter / input net (I5)."""
        import sys
        if self.proc is not None:return
        board=self.board_path()
        if not board or not os.path.isfile(board):
            self.status.setText('Choose a board first');return
        ground=self.values().get('ground') or 'GND'
        self._finding=[]
        argv=[sys.executable,'-m','pcbqs.mqs',board,'--list-converters','--ground',ground]
        self.say('$ python '+' '.join(argv[1:]));self.status.setText('Finding converters…');self.busy.show()
        self.run_btn.setEnabled(False);self.find_btn.setEnabled(False)
        def output():
            self._finding.append(bytes(self.proc.readAllStandardOutput()).decode(errors='replace'))
        def finished(code,_status=None):
            if self.proc is not None:
                output();self.proc.deleteLater();self.proc=None
            self.busy.hide();self.run_btn.setEnabled(True);self.find_btn.setEnabled(True)
            text=''.join(self._finding)
            try:
                found=json.loads(text[text.index('['):]) if code==0 else None
            except ValueError:
                found=None
            if found is None:
                self.say(text);self.status.setText(f'Finding converters failed (exit {code}); see Log');return
            self.pick_converter(converter_choices(found))
        run_tool(self,argv,output,finished)

    def pick_converter(self,choices):
        if not choices:
            self.status.setText('No converter found (an inductor on an IC\'s switch net, with input capacitors)');return
        from PySide6.QtWidgets import QInputDialog
        labels=[label for label,_ in choices]
        if len(choices)==1:
            pick=labels[0]
        else:
            pick,ok=QInputDialog.getItem(self,'Converters','Converter and input net:',labels,0,False)
            if not ok:return
        values=dict(choices)[pick]
        self.set_values(values)
        self.status.setText(f"{values['converter']} on {values['vin']}: set; Run or Preview mesh")

    def start(self,checked=False,preview=False):
        if self.proc is not None:return
        board=self.board_path()
        if not board or not os.path.isfile(board):
            self.status.setText('Choose a board first');return
        vals=self.values();ref=vals.get('converter') or 'auto'
        self._preview=preview
        named=self.outdir.text().strip()
        self.out=os.path.abspath((os.path.join(named,'preview') if preview else named) if named
                                 else self.default_out(board,ref,preview))
        argv=mqs_argv(vals,board,self.out,self.desc,preview=preview)
        self.log.clear();self.say('$ python '+' '.join(argv[1:]));self._front(self.log)
        self.run_btn.setEnabled(False);self.preview_btn.setEnabled(False);self.stop_btn.setEnabled(True);self.busy.show()
        self.open_btn.setEnabled(False);self.status.setText('Running…')
        run_tool(self,argv,self._stdout,self._finished)

    def _stdout(self):
        text=bytes(self.proc.readAllStandardOutput()).decode(errors='replace')
        self.say(text.rstrip())
        lines=[s for s in text.splitlines() if s.startswith('mqs:')]
        if lines:self.status.setText(lines[-1][4:].strip())

    def _finished(self,code,_status=None):
        if self.proc is not None:
            self._stdout();self.proc.deleteLater();self.proc=None
        self.run_btn.setEnabled(True);self.preview_btn.setEnabled('preview' in (self.desc or {}).get('features',[]));self.stop_btn.setEnabled(False);self.busy.hide()
        try:res=load_result(self.out,preview=self._preview) if code==0 else None
        except (OSError,ValueError,KeyError) as exc:
            self.say(str(exc));res=None
        if res is None:
            tail=self.log.toPlainText()[-400:]
            hint=('; use Find converters' if 'candidates' in tail or 'ambiguous input supply' in tail else '')
            self.status.setText(f'Run failed (exit {code}){hint}; see Log')
            self.summary.setHtml(self.failed_html(code));self._front(self.summary);return
        self.show_result(res);self._front(self.layout if self._preview and self.tabs.indexOf(self.layout)>=0 else self.summary)
        self.status.setText('Mesh preview ready' if self._preview else 'Done')

    def show_result(self,res):
        self.result=res;self.summary.setHtml(summary_html(res))
        self.pdn_btn.setEnabled(self.win is not None and hasattr(self.win,'pdn'))
        if self.tabs.indexOf(self.layout)<0:return                    # the window's page: the Viewer has the rest
        self.layout.load(res['_dir'])
        if self.layout.mesh.findData('mqs')>=0:self.layout.mesh.setCurrentIndex(self.layout.mesh.findData('mqs'))
        self.open_btn.setText('Open layout in Viewer' if res.get('preview') else 'Open fields in Viewer')
        self.open_btn.setEnabled(self.win is not None)
        self.pdn_btn.setEnabled(self.win is not None and hasattr(self.win,'pdn'))
        if res.get('preview'):
            self.spectrum.clear();self.maps.load(res['_dir'])
            return
        self.maps.load(res['_dir'])
        self.spectrum.clear()
        self.spectrum.plot(res['frequencies_Hz'],[max(row) for row in res['peak_H_Am']],pen='b',symbol='o')
        self.open_btn.setEnabled(self.win is not None)

    def open_fields(self):
        if self.win is not None and self.result is not None:
            self.win.open_results(self.result['_dir'])

    def open_pdn(self):
        if self.win is None or self.result is None or not hasattr(self.win,'pdn'):return
        r=self.result;s=r['selection'];pdn=self.win.pdn
        src=r.get('source_path') or self.board_path()
        if self._panel is None or not self.same_board(src,pdn.board_path()):   # the study's board: already its
            pdn.board.setText(src)
        vals={o['key']:o['default'] for o in (pdn.desc or {}).get('options',[])}
        vals.update(rail=s['vin'],ground=s['ground'],ground_source=s['converter'],load='')
        voltage=r.get('settings',{}).get('vin_volts',0)
        vals['volts']=voltage if voltage else ''
        pdn._transferred_unknown_voltage=not bool(voltage)
        pdn.set_values(vals)
        pdn.status.setText('Board and input rail shared. Set source, supply voltage and DC loads before Run.')
        self.win.show_panel('PDN')
