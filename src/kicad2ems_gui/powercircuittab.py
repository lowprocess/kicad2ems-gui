"""Operational circuit models: ngspice transient and optional PCB field inference."""
import json,os,subprocess,sys
import numpy as np
import pyqtgraph as pg
from pathlib import Path
from PySide6.QtCore import QTimer
from .schematicview import SchematicEditor
from .toolprocess import run_tool
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QPushButton,QComboBox,
                               QCheckBox,QPlainTextEdit,QTextBrowser,QTabWidget,QFileDialog,QLabel,QSplitter,QScrollArea,QSpinBox)
from PySide6.QtCore import Qt


class PowerCircuitTab(QWidget):
    def __init__(self,win=None):
        super().__init__();self.win=win;self.proc=None;self.out=None;self._syncing=False
        root=QVBoxLayout(self);settings=QWidget();form=QFormLayout(settings)
        self.settings_toggle=QPushButton('Operating settings');self.settings_toggle.setCheckable(True);root.addWidget(self.settings_toggle)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(settings);scroll.setMinimumHeight(180);scroll.setMaximumHeight(310);root.addWidget(scroll);scroll.hide();self.settings_toggle.toggled.connect(scroll.setVisible)
        self.board=QLineEdit();self.outdir=QLineEdit();self.frequencies=QLineEdit('90000,110000');self.powers=QLineEdit('5,10,20,30');self.coupling=QLineEdit('0.4')
        for label,w in [('PCB (optional)',self.board),('Output folder',self.outdir),('Frequencies (Hz)',self.frequencies),('Receiver powers (W)',self.powers),('Coupling k',self.coupling)]:form.addRow(label,w)
        self.receiver_C=QLineEdit();self.receiver_C.setPlaceholderText('Blank: tune at each frequency')
        self.load_R=QLineEdit();self.load_R.setPlaceholderText('Blank: efficiency match at each frequency')
        form.addRow('Fixed receiver C (nF)',self.receiver_C);form.addRow('Fixed receiver load (Ω)',self.load_R)
        self.model=QComboBox();self.model.addItems(['switch','mosfet','vdmos','ideal','subcircuit']);form.addRow('Switch model',self.model)
        self.jobs=QSpinBox();self.jobs.setRange(1,max(1,os.cpu_count() or 1));self.jobs.setValue(min(4,self.jobs.maximum()))
        self.jobs.setToolTip('Independent operating points run together. PCB extraction and field export share their model.');form.addRow('Parallel circuit cases',self.jobs)
        self.copper=QCheckBox('Include extracted PCB R/L in circuit');self.fields=QCheckBox('Infer periodic PCB fields from terminal currents')
        self.fields.toggled.connect(lambda on:self.copper.setChecked(True) if on else None)
        self.copper.toggled.connect(lambda on:self.fields.setChecked(False) if not on else None)
        form.addRow(self.copper);form.addRow(self.fields)
        self.overrides={}
        for key,label in [('rise_s','Gate rise/fall override (ns)'),('dead_time_s','Dead-time override (ns)'),('Cds_F','Switch Cds override (pF)'),('cap_ESR','All-capacitor ESR override (mΩ)'),('cap_ESL','All-capacitor ESL override (nH)'),('filter_DCR','L3 DCR override (mΩ)')]:
            w=QLineEdit();w.setPlaceholderText('Blank keeps per-part JSON values');self.overrides[key]=w;form.addRow(label,w)
        self.matching_note=QLabel();root.addWidget(self.matching_note)
        row=QHBoxLayout();root.addLayout(row)
        for text,slot in [('Load model…',self.load_model),('Save model…',self.save_model),('Choose PCB…',self.choose_board)]:
            b=QPushButton(text);b.clicked.connect(slot);row.addWidget(b)
        self.run_btn=QPushButton('Run circuit cases');self.run_btn.clicked.connect(self.start);row.addWidget(self.run_btn)
        self.stop_btn=QPushButton('Stop');self.stop_btn.setEnabled(False);self.stop_btn.clicked.connect(self.stop);row.addWidget(self.stop_btn)
        self.split=QSplitter(Qt.Horizontal);root.addWidget(self.split,1)
        self.editor=QPlainTextEdit();self.editor.setPlaceholderText('Component model JSON: per-part types, ESR/ESL/DCR, coil loss/SRF, switch parameters, input filter…')
        self.schematic=SchematicEditor(self);self.schematic.model_provider=self.values
        self.model_tabs=QTabWidget();self.model_tabs.addTab(self.schematic,'Schematic');self.model_tabs.addTab(self.editor,'Model JSON')
        self.split.addWidget(self.model_tabs);self.tabs=QTabWidget();self.split.addWidget(self.tabs)
        self.summary=QTextBrowser();self.log=QPlainTextEdit();self.log.setReadOnly(True)
        self.tabs.addTab(self.summary,'Results')
        wave=QWidget();wave_layout=QVBoxLayout(wave);self.signal_view=QComboBox();self.signal_view.addItems(['Winding currents','Bridge / coil voltages','Input filter currents','Bus voltages']);wave_layout.addWidget(self.signal_view)
        # I1: the solver's own steps (edge spikes) instead of the uniform T/256-style samples, when the run saved them
        self.steps_box=QCheckBox('Solver steps (switching-edge spikes)');self.steps_box.setToolTip('Plot the signals at ngspice\'s own timesteps, as bus_spike_pp_V is measured; the default view is the uniform resampling the settled ripple uses')
        self.steps_box.toggled.connect(lambda *_:self.show_waveform());wave_layout.addWidget(self.steps_box)
        self.waveform=pg.PlotWidget();self.waveform.addLegend();self.waveform.showGrid(x=True,y=True,alpha=.2);wave_layout.addWidget(self.waveform);self.signal_view.currentIndexChanged.connect(self.show_waveform)
        self.tabs.addTab(wave,'Time-domain waveforms');self.tabs.addTab(self.log,'Log')
        self.status=QLabel('Ready. Top controls override the corresponding JSON settings when run.');root.addWidget(self.status)
        self.editor_only=QPushButton('Editor only');self.editor_only.setCheckable(True);self.editor_only.setChecked(True);row.addWidget(self.editor_only)
        self.editor_only.toggled.connect(lambda on:self.tabs.setVisible(not on));self.tabs.hide()
        self.schematic.modelChanged.connect(self.schematic_changed);self.schematic.statusChanged.connect(self.status.setText)
        self.refresh_timer=QTimer(self);self.refresh_timer.setSingleShot(True);self.refresh_timer.setInterval(250);self.refresh_timer.timeout.connect(self.refresh_schematic)
        self.editor.textChanged.connect(lambda:self.refresh_timer.start() if not self._syncing else None)
        for control in [self.frequencies,self.powers,self.coupling,self.receiver_C,self.load_R,*self.overrides.values()]:control.editingFinished.connect(self.refresh_schematic)
        self.model.currentTextChanged.connect(self.refresh_schematic)
        self.case=QComboBox();self.case.currentIndexChanged.connect(self.show_waveform);self.open_btn=QPushButton('Open selected case fields');self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self.open_fields);row=QHBoxLayout();row.addWidget(self.case,1);row.addWidget(self.open_btn);root.addLayout(row)
        try:
            p=subprocess.run([sys.executable,'-m','pcbqs.power_circuit','--template'],capture_output=True,text=True,timeout=30,check=True)
            self.set_model(json.loads(p.stdout))
        except (OSError,ValueError,ImportError,KeyError,TypeError,subprocess.SubprocessError) as e:self.status.setText("Install/update pcbqs with python -m pip install 'kicad2ems[qs]': "+str(e));self.run_btn.setEnabled(False);self.schematic.setEnabled(False)

    def matching_text(self,c):
        cap=f'fixed {c["secondary_C_F"]*1e9:g} nF' if c.get('secondary_C_F') is not None else 'tuned per frequency'
        load=f'fixed {c["load_ohm"]:g} Ω' if c.get('load_ohm') is not None else 'efficiency matched per frequency'
        return f'Primary C: {c["primary_C_F"]*1e9:g} nF. Receiver C: {cap}; load: {load}. Phase targets load power.'

    def set_model(self,c,diagram=True):
        self._syncing=True
        try:
            if diagram:self.schematic.set_model(c)
            self.receiver_C.setText(str(c['secondary_C_F']*1e9) if c.get('secondary_C_F') is not None else '')
            self.load_R.setText(str(c['load_ohm']) if c.get('load_ohm') is not None else '')
            self.matching_note.setText(self.matching_text(c))
            self.settings_toggle.setText(f'Operating settings — {c["voltage_V"]:g} V · '+', '.join(f'{f/1000:g} kHz' for f in c['frequencies_Hz'])+f' · k={c["coupling"]:g}')
            for w in self.overrides.values():w.clear()
            self.editor.setPlainText(json.dumps(c,indent=2));self.frequencies.setText(','.join(map(str,c['frequencies_Hz'])));self.powers.setText(','.join(map(str,c['powers_W'])));self.coupling.setText(str(c['coupling']));self.model.setCurrentText(c.get('switch_model',{}).get('type','switch'))
        finally:self._syncing=False
        if diagram:QTimer.singleShot(0,self.schematic.fit)

    def schematic_changed(self,c):
        self.refresh_timer.stop();self.set_model(c,diagram=False)

    def refresh_schematic(self,*_):
        if self._syncing:return
        try:self.schematic.set_model(self.values())
        except (ValueError,KeyError,TypeError,ImportError) as exc:self.status.setText('Model needs attention: '+str(exc))

    def values(self):
        c=json.loads(self.editor.toPlainText());c['frequencies_Hz']=[float(x) for x in self.frequencies.text().split(',')];c['powers_W']=[float(x) for x in self.powers.text().split(',')];c['coupling']=float(self.coupling.text());c.setdefault('switch_model',{})['type']=self.model.currentText()
        for key,w,scale in [('secondary_C_F',self.receiver_C,1e-9),('load_ohm',self.load_R,1.)]:
            if w.text().strip():c[key]=float(w.text())*scale
            else:c.pop(key,None)
        scales=dict(rise_s=1e-9,dead_time_s=1e-9,Cds_F=1e-12,cap_ESR=1e-3,cap_ESL=1e-9,filter_DCR=1e-3)
        for key,w in self.overrides.items():
            if not w.text().strip():continue
            value=float(w.text())*scales[key]
            if key in ('rise_s','dead_time_s','Cds_F'):
                c['switch_model'][key]=value
                if key=='rise_s':c['switch_model']['fall_s']=value
            else:
                for part in c['components']:
                    if key.startswith('cap_') and part['type']=='capacitor':part['ESR_ohm' if key=='cap_ESR' else 'ESL_H']=value
                    if key=='filter_DCR' and part['ref']=='L3':part['DCR_ohm']=value
        return c

    def load_model(self):
        p,_=QFileDialog.getOpenFileName(self,'Circuit model','','JSON (*.json)')
        if p:
            try:
                c=json.loads(Path(p).read_text())
                for model in [c.get('switch_model',{}),*[s.get('model',{}) for s in c.get('switches',[])]]:
                    if model.get('library'):model['library']=str((Path(p).parent/model['library']).resolve())
                self.set_model(c)
            except (OSError,ValueError,KeyError) as e:self.status.setText(str(e))

    def save_model(self):
        try:c=self.values()
        except (ValueError,KeyError) as e:self.status.setText(str(e));return
        p,_=QFileDialog.getSaveFileName(self,'Save circuit model','model.json','JSON (*.json)')
        if p:Path(p).write_text(json.dumps(c,indent=2))

    def choose_board(self):
        p,_=QFileDialog.getOpenFileName(self,'PCB layout','','PCB (*.kicad_pcb *.json)')
        if p:self.board.setText(p)

    def start(self):
        if self.proc:return
        try:c=self.values()
        except (ValueError,KeyError) as e:self.status.setText(str(e));return
        self.matching_note.setText(self.matching_text(c))
        if self.copper.isChecked() and not Path(self.board.text()).is_file():self.status.setText('Choose a PCB for copper extraction');return
        self.out=Path(self.outdir.text().strip() or 'power-circuit').expanduser().resolve();self.out.mkdir(parents=True,exist_ok=True)
        model=self.out/'model-input.json';model.write_text(json.dumps(c,indent=2))
        argv=['-u','-m','pcbqs.power_circuit',str(model),'--out',str(self.out),'--jobs',str(self.jobs.value())]
        if self.copper.isChecked():argv+=['--copper','--board',self.board.text()]
        if self.fields.isChecked():argv+=['--fields']
        self.run_btn.setEnabled(False);self.stop_btn.setEnabled(True);self.open_btn.setEnabled(False);self.log.clear();self.tabs.setCurrentWidget(self.log);self.status.setText('Running transient cases…')
        self.editor_only.setChecked(False)
        run_tool(self,[sys.executable,*argv],self.read_log,self.finished,env=dict(OPENBLAS_NUM_THREADS='8'))

    def stop(self):
        if self.proc:self.proc.terminate()
        self.schematic.cancel_import()

    def closeEvent(self,event):
        self.stop()
        if self.proc:self.proc.waitForFinished(3000)
        super().closeEvent(event)

    def read_log(self):
        if self.proc:self.log.appendPlainText(bytes(self.proc.readAllStandardOutput()).decode(errors='replace').rstrip())

    def finished(self,code,*_):
        if self.proc:self.read_log();self.proc.deleteLater();self.proc=None
        self.run_btn.setEnabled(True);self.stop_btn.setEnabled(False)
        path=self.out/'power-circuit.json'
        if code or not path.exists():self.status.setText('Circuit run failed; see Log');return
        self.show_result(json.loads(path.read_text()))

    def show_result(self,res):
        self.editor_only.setChecked(False)
        self.result=res;self.case.clear();rows=[]
        for c in res['cases']:
            num=lambda key,fmt,scale=1:format(c[key]*scale,fmt) if isinstance(c.get(key),(int,float)) else '–'
            rows.append(f'<tr><td>{c["frequency_Hz"]/1000:g}</td><td>{c["load_power_W"]:.3f}</td><td>{num("input_power_W",".3f")}</td><td>{100*c["efficiency"]:.2f}</td>'
                        f'<td>{c["phase_deg"]:.2f}</td><td>{c["primary_rms_A"]:.3f}</td><td>{num("bus_ripple_V",".2f")}</td><td>{num("bus_spike_pp_V",".2f")}</td><td>{num("runtime_s",".0f")}</td></tr>')
            self.case.addItem(f'{c["frequency_Hz"]/1000:g} kHz / {c["target_W"]:g} W',c['folder'])
        self.summary.setHtml('<h3>Operational circuit results</h3><table cellspacing=8><tr><th>kHz</th><th>Load W</th><th>Input W</th><th>Efficiency %</th><th>Phase °</th><th>Primary RMS A</th><th>VHB ripple V*</th><th>VHB spikes p-p V†</th><th>Run s</th></tr>'+''.join(rows)+'</table><p>* Settled ripple: peak to peak of the final cycle sampled at T/256, as the waveforms below are by default. † Peak to peak at every solver timestep, switching-edge spikes included (older results report this as the ripple); tick Solver steps under the waveforms to see them.</p><p>Receiver/load and unmeasured parasitics are model assumptions. See model.json and case.json for matching, settling and power checks.</p><p>Fields are band-limited copper-current inference; external coils, package filaments and environment coupling are omitted.</p>')
        self.tabs.setCurrentWidget(self.summary);self.open_btn.setEnabled(self.win is not None and any('field_inference' in c for c in res['cases']));self.status.setText('Completed' if res.get('complete') else 'Partial results')

    def show_waveform(self,*_):
        folder=self.case.currentData() if hasattr(self,'case') else None
        if not folder:return
        try:
            r=next(r for r in self.result['cases'] if r['folder']==folder)
            with np.load(Path(folder)/'transient.npz') as data:v={k:data[k] for k in data.files}
            steps=self.steps_box.isChecked() and 'steps.time_s' in v
            self.steps_box.setEnabled('steps.time_s' in v)
            if steps:v={**v,'time_s':v['steps.time_s'],**{k[6:]:x for k,x in v.items() if k.startswith('steps.')}}
            t=v['time_s'];take=t>=t[-1]-2/r['frequency_Hz'];xx=(t[take]-(t[-1]-2/r['frequency_Hz']))*1e6
            options=[(['PRIMARY.winding_I','SECONDARY.winding_I'],'A'),(['bridge.V','PRIMARY.V','SECONDARY.V'],'V'),(['L3.I','R9.I'],'A'),(['bus.V','input.V','supply.V'],'V')]
            keys,unit=options[self.signal_view.currentIndex()];self.waveform.clear()
            present=[key for key in keys if key in v]               # a board without L3/R9 still shows the rest
            if not present:self.status.setText('This case has none of: '+', '.join(keys))
            for i,key in enumerate(present):self.waveform.plot(xx,v[key][take],pen=pg.mkPen(['#e9783c','#409ad6','#6eb671'][i],width=1.5),name=key)
            self.waveform.setLabel('bottom','Time in final two periods',units='µs');self.waveform.setLabel('left',unit)
        except (OSError,ValueError,KeyError,StopIteration) as error:self.status.setText('Waveforms unavailable: '+str(error))

    def open_fields(self):
        if self.win and self.case.currentData():self.win.open_results(self.case.currentData())
