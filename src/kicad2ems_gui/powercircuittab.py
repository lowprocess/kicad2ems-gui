"""Circuit models run with ngspice. Two kinds, told apart by the model's "format":
    2   pcbqs.circuit: any circuit of parts, nodes and drives
    1   pcbqs.power_circuit: the phase-shifted full bridge on a board's terminals, with its copper and fields

A model comes from a file: a study's config names it ([analysis.circuit] model = "buck.json", a path beside the
config), and the circuits to start from are examples like any other, under File > Examples > Circuits. Saving the
study writes the model back beside its config."""
import json,os,subprocess,sys
import numpy as np
import pyqtgraph as pg
from pathlib import Path
from PySide6.QtCore import QTimer
from .schematicview import SchematicEditor
from .toolprocess import run_tool
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QPushButton,QComboBox,
                               QCheckBox,QPlainTextEdit,QTextBrowser,QTabWidget,QFileDialog,QLabel,QSplitter,QScrollArea,QSpinBox,
                               QTableWidget,QTableWidgetItem,QHeaderView)
from PySide6.QtCore import Qt


def _is_number(text):
    try:float(text);return True
    except (TypeError,ValueError):return False


class PowerCircuitTab(QWidget):
    _panel=None                                                     # the operating settings, once in the Study dock

    def __init__(self,win=None):
        super().__init__();self.win=win;self.proc=None;self.out=None;self._syncing=False;self.general=False;self.result=None
        root=QVBoxLayout(self);settings=QWidget();form=QFormLayout(settings);self.form=form
        self.settings_toggle=QPushButton('Operating settings');self.settings_toggle.setCheckable(True);root.addWidget(self.settings_toggle)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(settings);scroll.setMinimumHeight(180);scroll.setMaximumHeight(310);root.addWidget(scroll);scroll.hide();self.settings_toggle.toggled.connect(scroll.setVisible);self._settings_scroll=scroll
        self.board=QLineEdit();self.outdir=QLineEdit();self.frequencies=QLineEdit('90000,110000');self.powers=QLineEdit('5,10,20,30');self.coupling=QLineEdit('0.4')
        for label,w in [('PCB (optional)',self.board),('Output folder',self.outdir),('Frequencies (Hz)',self.frequencies),('Receiver powers (W)',self.powers),('Coupling k',self.coupling)]:form.addRow(label,w)
        # the general model's settings: its parameters, and what it sweeps
        self.params=QTableWidget(0,2);self.params.setHorizontalHeaderLabels(['Parameter','Value']);self.params.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.params.verticalHeader().hide();self.params.setMaximumHeight(170);self.params.setToolTip("The model's parameters: its values may be expressions of them (vout/iout). A number, SI notation (22u) or an expression of the others")
        self.params.itemChanged.connect(lambda *_:self.refresh_timer.start() if not self._syncing else None)
        self.sweep=QLineEdit();self.sweep.setPlaceholderText('e.g.  parameters.vin: 9, 12, 15;  R1.resistance_ohm: 24, 48')
        self.sweep.setToolTip('What to sweep: a path of the model and its values; several, separated by semicolons, run in every combination')
        form.addRow('Parameters',self.params);form.addRow('Sweep',self.sweep)
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
        row=QHBoxLayout();root.addLayout(row);self.top_row=row
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
        for control in [self.frequencies,self.powers,self.coupling,self.receiver_C,self.load_R,self.sweep,*self.overrides.values()]:control.editingFinished.connect(self.refresh_schematic)
        self.bridge_rows=[self.frequencies,self.powers,self.coupling,self.receiver_C,self.load_R,self.model,*self.overrides.values()]
        self.model.currentTextChanged.connect(self.refresh_schematic)
        self.case=QComboBox();self.case.currentIndexChanged.connect(self.show_waveform);self.open_btn=QPushButton('Open selected case fields');self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self.open_fields);row=QHBoxLayout();row.addWidget(self.case,1);row.addWidget(self.open_btn);root.addLayout(row)
        self.model_path=None                                        # the file the model came from (a config's, a loaded one)
        if win is not None:                                         # the circuits to start from: the window's examples
            self.examples_btn=QPushButton('Examples');self.examples_btn.setToolTip('The circuits to start from: File > Examples > Circuits')
            self.examples_btn.clicked.connect(self.show_examples);self.top_row.insertWidget(0,self.examples_btn)
        try:
            self.set_model(self.template('simple'))                  # a small circuit to open on, not a board's
        except (OSError,ValueError,ImportError,KeyError,TypeError,subprocess.SubprocessError) as e:self.status.setText("Install/update pcbqs with python -m pip install 'kicad2ems[qs]': "+str(e));self.run_btn.setEnabled(False);self.schematic.setEnabled(False)

    def show_examples(self):
        """The window's menu of the circuit examples (File > Examples), here where a circuit is started."""
        menus=getattr(self.win,'example_menus',{});whose=getattr(self.win,'example_sources',{})
        menu=next((m for path,m in menus.items() if 'circuit' in whose.get(path,())),None)   # the group the circuit analysis ships
        if menu is None:self.status.setText('No circuit examples are installed (File > Examples)');return
        menu.exec(self.examples_btn.mapToGlobal(self.examples_btn.rect().bottomLeft()))

    @staticmethod
    def templates():
        """pcbqs's example circuits: {name: what it is}; none from a pcbqs without pcbqs.circuit."""
        try:
            from pcbqs.circuit import model
            return dict(model.templates())
        except (ImportError,OSError,ValueError):return {}

    @classmethod
    def template(cls,name):
        """A model to start from: one of pcbqs.circuit's examples ('simple' is its boost converter), or the
        full-bridge tool's (wpthb; a pcbqs without named templates gives its only one)."""
        names=cls.templates()
        if name=='simple' and 'boost' in names:name='boost'
        if name in names:
            from pcbqs.circuit import model
            return model.template(name)
        run=lambda *a:subprocess.run([sys.executable,'-m','pcbqs.power_circuit','--template',*a],capture_output=True,text=True,timeout=30)
        p=run(name)
        if p.returncode and 'argument --template' not in p.stderr and 'unrecognized' not in p.stderr:p.check_returncode()
        if p.returncode:p=run()                                     # older pcbqs: --template takes no name
        p.check_returncode()
        return json.loads(p.stdout)

    def new_model(self,name):
        try:self.set_model(self.template(name));self.model_path=None;self.status.setText(f'Started from the {name} template.')
        except (OSError,ValueError,subprocess.SubprocessError) as e:self.status.setText('Template unavailable: '+str(e))

    def settings_panel(self):
        """The operating settings out of the page, for the window's Study dock (its Run starts the cases then,
        so the page's Run and Stop are hidden); the PCB is the study's board unless one is named here."""
        if self._panel is None:
            self._panel=self._settings_scroll.takeWidget()
            self._settings_scroll.hide();self.settings_toggle.hide();self.run_btn.hide();self.stop_btn.hide()
            self.board.setPlaceholderText("the study's board")
        return self._panel

    def board_path(self):
        """The PCB named here, else the study's board (the window's settings)."""
        p=self.board.text().strip()
        if not p and self.win is not None and hasattr(self.win,'setup'):
            try:p=self.win.setup.values().get('board') or ''
            except (ValueError,KeyError,TypeError):p=''
        return p

    def matching_text(self,c):
        cap=f'fixed {c["secondary_C_F"]*1e9:g} nF' if c.get('secondary_C_F') is not None else 'tuned per frequency'
        load=f'fixed {c["load_ohm"]:g} Ω' if c.get('load_ohm') is not None else 'efficiency matched per frequency'
        return f'Primary C: {c["primary_C_F"]*1e9:g} nF. Receiver C: {cap}; load: {load}. Phase targets load power.'

    def show_kind(self,general):
        """The settings and views of the model's kind: the general model's parameters and sweep, or the bridge's
        operating points, overrides, copper and fields."""
        self.general=general
        for w in self.bridge_rows:self.form.setRowVisible(w,not general)
        for w in (self.params,self.sweep):self.form.setRowVisible(w,general)
        self.steps_box.setVisible(not general);self.open_btn.setVisible(not general)
        self.copper.setText("Include the board's copper between the parts' pads" if general else 'Include extracted PCB R/L in circuit')
        self.copper.setToolTip("Each pad a node of its own, joined by what the board has between them: the model's board (board.file), the PCB named above, or the study's board. "
                               'The circuit alone is settled first, then run on its board' if general else '')
        self.fields.setText('H and E fields over the board, from the run\'s currents and voltages' if general else 'Infer periodic PCB fields from terminal currents')
        self.board.setPlaceholderText("the model's board, else the study's" if general else ("the study's board" if self._panel is not None else ''))
        views=['Probes: voltages','Probes: currents','Capacitor voltages','Inductor currents','Switch and diode voltages','Switch and diode currents'] if general else \
              ['Winding currents','Bridge / coil voltages','Input filter currents','Bus voltages']
        if [self.signal_view.itemText(i) for i in range(self.signal_view.count())]!=views:
            self.signal_view.blockSignals(True);self.signal_view.clear();self.signal_view.addItems(views);self.signal_view.blockSignals(False)

    @staticmethod
    def sweep_text(sweep):
        return ';  '.join(f"{path}: "+', '.join(f'{v:g}' if isinstance(v,(int,float)) else str(v) for v in values) for path,values in sweep.items())

    @staticmethod
    def sweep_of(text):
        """'parameters.vin: 9, 12; R1.resistance_ohm: 24, 48' as the model's sweep."""
        out={}
        for item in filter(str.strip,text.split(';')):
            path,sep,values=item.partition(':')
            if not sep or not path.strip() or not values.strip():raise ValueError('Sweep: write  path: value, value, …  (several separated by ;)')
            out[path.strip()]=[float(v) if _is_number(v) else v.strip() for v in values.split(',') if v.strip()]
        return out

    def set_general(self,c,diagram=True):
        """A model of the general kind (format 2) into the page."""
        self._syncing=True
        try:
            if diagram:self.schematic.set_model(c)
            self.show_kind(True)
            self.params.setRowCount(0)
            for name,value in c.get('parameters',{}).items():
                row=self.params.rowCount();self.params.insertRow(row);key=QTableWidgetItem(name);key.setFlags(key.flags()&~Qt.ItemIsEditable)
                self.params.setItem(row,0,key);self.params.setItem(row,1,QTableWidgetItem(f'{value:g}' if isinstance(value,(int,float)) else str(value)))
            self.sweep.setText(self.sweep_text(c.get('sweep',{})))
            targets=';  '.join(f"{t['adjust']} is adjusted until {t['measure']} = {t['value']}" for t in c.get('targets',[]))
            self.matching_note.setText((c.get('description') or '')+('  —  '+targets if targets else ''))
            self.settings_toggle.setText('Operating settings — '+(c.get('name') or 'circuit'))
            self.editor.setPlainText(json.dumps(c,indent=2))
        finally:self._syncing=False
        if diagram:QTimer.singleShot(0,self.schematic.fit)

    def set_model(self,c,diagram=True):
        if c.get('format')==2:return self.set_general(c,diagram)
        self._syncing=True
        try:
            if diagram:self.schematic.set_model(c)
            self.show_kind(False)
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
        c=json.loads(self.editor.toPlainText())
        if c.get('format')==2:                                      # the general model: its parameters and its sweep
            for row in range(self.params.rowCount()):
                name,text=self.params.item(row,0).text(),self.params.item(row,1).text().strip()
                if name in c.get('parameters',{}) and text:c['parameters'][name]=float(text) if _is_number(text) else text
            sweep=self.sweep_of(self.sweep.text())
            if sweep:c['sweep']=sweep
            else:c.pop('sweep',None)
            return c
        c['frequencies_Hz']=[float(x) for x in self.frequencies.text().split(',')];c['powers_W']=[float(x) for x in self.powers.text().split(',')];c['coupling']=float(self.coupling.text());c.setdefault('switch_model',{})['type']=self.model.currentText()
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

    def load_model(self,path=None):
        """A model from a file (asked for when none is named): its libraries and its board, named beside it, found
        from where it is. True when it loaded."""
        p=path or QFileDialog.getOpenFileName(self,'Circuit model','','JSON (*.json)')[0]
        if not p:return False
        try:
            here=Path(p).resolve().parent
            c=json.loads(Path(p).read_text())
            for part in c.get('parts',[]) if c.get('format')==2 else []:
                if part.get('model',{}).get('library'):part['model']['library']=str((here/part['model']['library']).resolve())
            for model in [c.get('switch_model',{}),*[s.get('model',{}) for s in c.get('switches',[])]]:
                if model.get('library'):model['library']=str((here/model['library']).resolve())
            board=(c.get('board') or {}).get('file')
            if board and not Path(board).is_absolute():c['board']['file']=str((here/board).resolve())
            self.set_model(c);self.model_path=str(Path(p).resolve())
            return True
        except (OSError,ValueError,KeyError) as e:self.status.setText(str(e));return False

    def write_model(self,path,c=None):
        """The model as a file: its board named relative to it when it is beside it (a study's folder moves whole)."""
        c=json.loads(json.dumps(self.values() if c is None else c));here=Path(path).resolve().parent
        board=(c.get('board') or {}).get('file')
        if board and Path(board).is_absolute() and Path(board).resolve().parent==here:c['board']['file']=Path(board).name
        Path(path).write_text(json.dumps(c,indent=2))

    # ---- a study's config: [analysis.circuit] ----
    def load_settings(self,tab):
        """A config's [analysis.circuit] table (its paths already whole): the model it names, the copper and fields
        ticks, a board and a folder of its own. An empty one: the page as it opens."""
        self.board.setText(str(tab.get('board') or ''));self.outdir.setText(str(tab.get('out') or ''))
        on=lambda k:tab.get(k) is True or str(tab.get(k)).strip().lower() in ('1','true','yes','on')
        self.copper.setChecked(on('copper') or on('fields'));self.fields.setChecked(on('fields'))
        if tab.get('jobs'):self.jobs.setValue(int(tab['jobs']))
        if tab.get('model'):
            if self.load_model(str(tab['model'])):self.status.setText(f"Model: {Path(str(tab['model'])).name}")
        elif self.model_path is not None:
            try:self.set_model(self.template('simple'))
            except (OSError,ValueError,ImportError,KeyError,TypeError,subprocess.SubprocessError):pass
            self.model_path=None

    def save_settings(self,config):
        """What the config at `config` holds of the circuit, {key: value} (paths relative to it), the model written
        as a file: the one it came from, else <config>_circuit.json beside the config. {}: the page was never
        given a model and the analysis is not ticked, so the study has no circuit."""
        ticked=self.win is not None and hasattr(self.win,'study') and 'circuit' in self.win.study.ticked()
        if self.model_path is None and not ticked:return {}
        base=Path(config).resolve().parent;tab={}
        try:
            c=self.values()
            if self.model_path is None:self.model_path=str(base/(Path(config).stem+'_circuit.json'))
            self.write_model(self.model_path,c)
        except (ValueError,KeyError,OSError) as e:self.status.setText(f'The model was not saved: {e}')
        rel=lambda p:os.path.relpath(os.path.abspath(p),base).replace(os.sep,'/')
        if self.model_path:tab['model']=rel(self.model_path)
        if self.copper.isChecked():tab['copper']=True
        if self.fields.isChecked():tab['fields']=True
        for key,edit in (('board',self.board),('out',self.outdir)):
            if edit.text().strip():tab[key]=rel(edit.text().strip())
        return tab

    def open_run(self,folder):
        """A run's folder as the page's result (picked under Results of): its points, losses and waveforms."""
        path=next((Path(folder)/n for n in ('circuit.json','power-circuit.json') if (Path(folder)/n).exists()),None)
        if path is None:return False
        self.out=Path(folder)
        try:self.show_result(json.loads(path.read_text()))
        except (OSError,ValueError,KeyError) as e:self.status.setText(str(e));return False
        return True

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
        general=c.get('format')==2
        if not general:self.matching_note.setText(self.matching_text(c))
        board=self.board.text().strip() or (c.get('board') or {}).get('file','') or self.board_path() if general else self.board_path()
        if self.copper.isChecked() and not Path(board).is_file():self.status.setText('Choose a PCB for copper extraction' if not general else "Choose the model's board: Import KiCad… a .kicad_pcb, or name one under PCB");return
        self.out=Path(self.outdir.text().strip() or self.default_out(c,board)).expanduser().resolve();self.out.mkdir(parents=True,exist_ok=True)
        model=self.out/'model-input.json';model.write_text(json.dumps(c,indent=2))
        argv=['-u','-m','pcbqs.circuit' if general else 'pcbqs.power_circuit',str(model),'--out',str(self.out),'--jobs',str(self.jobs.value())]
        if self.copper.isChecked():argv+=['--copper','--board',board]
        if self.fields.isChecked():argv+=['--fields']
        self.run_btn.setEnabled(False);self.stop_btn.setEnabled(True);self.open_btn.setEnabled(False);self.log.clear();self.tabs.setCurrentWidget(self.log);self.status.setText('Running transient cases…')
        self.editor_only.setChecked(False)
        run_tool(self,[sys.executable,*argv],self.read_log,self.finished,env=dict(OPENBLAS_NUM_THREADS='8'))

    def default_out(self,c,board=''):
        """Where a run goes when no folder is named: in the window a folder per run under the study's output
        folder (as the other analyses': listed under Results of); alone, a folder where it was started."""
        general=c.get('format')==2
        if self.win is None or not hasattr(self.win,'tool_out'):return 'circuit' if general else 'power-circuit'
        tag=Path(self.model_path).stem if self.model_path else ''.join(ch if ch.isalnum() else '_' for ch in (c.get('name') or 'circuit')).strip('_')[:40] or 'circuit'
        return self.win.tool_out('circuit',self.board_path() or board or None,tag)

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
        path=next((self.out/n for n in ('circuit.json','power-circuit.json') if (self.out/n).exists()),None)
        if path is None or (code and path.name!='circuit.json'):self.status.setText('Circuit run failed; see Log');return
        self.show_result(json.loads(path.read_text()))             # a general run's failed points are in its results

    def show_general(self,res):
        """A general run's results: a row a point (its knobs, powers, efficiency and measures), then each part's
        share of the selected point's loss, its stress, and whatever the point should be read with."""
        self.editor_only.setChecked(False);self.show_kind(True)
        self.result=res;self.case.blockSignals(True);self.case.clear()
        for c in res['cases']:self.case.addItem(c['name'],c['folder'])
        self.case.blockSignals(False)
        self.show_point();self.show_waveform()
        failed=len(res.get('failed',[]))
        self.status.setText(('Completed' if res.get('complete') else 'Partial results')+(f': {failed} point{"s" if failed!=1 else ""} failed' if failed else ''))
        self.tabs.setCurrentWidget(self.summary)

    def show_point(self,*_):
        res=self.result
        if not res or res.get('format')!=2:return
        g=lambda v,fmt='.4g':format(v,fmt) if isinstance(v,(int,float)) else '–'
        cases=res['cases'];knobs=sorted({k for c in cases for k in c.get('knobs',{})});measures=sorted({k for c in cases for k in c.get('measures',{})})
        head=''.join(f'<th nowrap>{h}</th>' for h in ['Point',*[k.split('.',1)[-1] for k in knobs],'In W','Out W','Loss W','Efficiency %',*measures,'Runs','s'])
        rows=''.join('<tr>'+''.join(f'<td nowrap>{x}</td>' for x in [c['name'],*[g(c['knobs'].get(k)) for k in knobs],g(c['source_power_W']),g(c['load_power_W']),g(c['loss_W']),
                     g(100*c['efficiency'],'.2f') if c.get('efficiency') else '–',*[g(c['measures'].get(m)) for m in measures],c.get('runs','–'),g(c.get('runtime_s'),'.0f')])+'</tr>' for c in cases)
        html=f"<h3>{res.get('name') or 'Circuit'}</h3><table cellspacing=8><tr>{head}</tr>{rows}</table>"
        for f in res.get('failed',[]):html+=f"<p><b>{f['name']}: failed.</b> {f['error']}</p>"
        c=next((c for c in cases if c['folder']==self.case.currentData()),cases[0] if cases else None)
        if c:
            together={r for grp in c.get('coupled',[]) for r in grp['inductors']}
            loss=[(r,p['power_W']) for r,p in c['parts'].items() if p['type'] not in ('source','load') and r not in together]
            loss+=[(' + '.join(grp['inductors']),grp['power_W']) for grp in c.get('coupled',[])]
            if c.get('copper'):loss.append((f"board copper ({c['copper'].get('board','')})",c['copper']['loss_W']))
            if c.get('gate_drive_power_W'):loss.append(('gate drives',-c['gate_drive_power_W']))
            total=max(c['loss_W'],1e-30)
            html+=f"<h4>{c['name']}: where the {g(c['loss_W'])} W goes</h4><table cellspacing=6><tr><th>Part</th><th>W</th><th>%</th></tr>"
            html+=''.join(f"<tr><td>{r}</td><td>{g(w)}</td><td>{100*w/total:.1f}</td></tr>" for r,w in sorted(loss,key=lambda x:-x[1]) if abs(w)>1e-4*total)+'</table>'
            stress=[(r,p) for r,p in c['parts'].items() if p['type'] in ('switch','diode','capacitor','inductor')]
            html+='<h4>Stress</h4><table cellspacing=6><tr><th>Part</th><th>avg A</th><th>RMS A</th><th>peak A</th><th>peak V</th><th>avg V</th><th>ripple</th></tr>'
            html+=''.join(f"<tr><td>{r}</td><td>{g(p.get('avg_A'))}</td><td>{g(p.get('rms_A'))}</td><td>{g(p.get('peak_A'))}</td><td>{g(p.get('peak_V'))}</td><td>{g(p.get('avg_V'))}</td>"
                          f"<td>{g(p['ripple_V'])+' V' if 'ripple_V' in p else g(p['ripple_A'])+' A' if 'ripple_A' in p else '–'}</td></tr>" for r,p in stress)+'</table>'
            for note in c.get('notes',[]):html+=f'<p><b>Note.</b> {note}</p>'
            if c.get('copper') and c['copper'].get('ports'):
                html+='<h4>Board copper</h4><table cellspacing=6><tr><th>Pad</th><th>Net</th><th>to</th><th>RMS A</th></tr>'
                html+=''.join(f"<tr><td>{p['terminal'].rsplit('.',1)[0]}</td><td>{p['net']}</td><td>{p['reference'].rsplit('.',1)[0]}</td><td>{g(p.get('rms_A'))}</td></tr>" for p in c['copper']['ports'])+'</table>'
            fields=c.get('fields')
            if fields:
                html+='<h4>Fields over the board (AC RMS, the largest on each plane)</h4><table cellspacing=6><tr><th>Height mm</th><th>H A/m</th><th>E V/m</th></tr>'
                html+=''.join(f"<tr><td>{g(h)}</td><td>{g(a)}</td><td>{g(e)}</td></tr>" for h,a,e in zip(fields['heights_mm'],fields['H_ac_rms_max_A_per_m'],fields['E_ac_rms_max_V_per_m']))+'</table>'
                html+=f"<p>The copper and its vias only: no part's own field. H to {g(fields['highest_Hz']/1e6)} MHz; E from the nets' voltages.</p>"
                if fields.get('picture') and Path(fields['picture']).is_file():html+=f"<p><img src='{Path(fields['picture']).as_uri()}' width='760'></p>"
            html+=f"<p>Settled to {100*c.get('periodic_error',0):.2g} % period to period; solver tolerance {g(c.get('reltol'))}; {c.get('periods','–')} periods simulated.</p>"
        self.summary.setHtml(html)

    def general_waveform(self,folder):
        r=next(r for r in self.result['cases'] if r['folder']==folder)
        with np.load(Path(folder)/'transient.npz') as data:v={k:data[k] for k in data.files}
        try:model=json.loads((Path(folder)/'model.json').read_text())
        except (OSError,ValueError):model={}
        probes=model.get('probes',{});kinds={p['ref']:p['type'] for p in model.get('parts',[])}
        of=lambda types,suffix:[ref+suffix for ref,k in kinds.items() if k in types]
        keys,unit=[([n for n,p in probes.items() if 'voltage' in p],'V'),([n for n,p in probes.items() if 'current' in p],'A'),(of(('capacitor',),'.V'),'V'),
                   (of(('inductor',),'.I'),'A'),(of(('switch','diode'),'.V'),'V'),(of(('switch','diode'),'.I'),'A')][max(self.signal_view.currentIndex(),0)]
        T=r['period_s'];t=v['time_s'];take=t>=t[-1]-2*T;scale,name=(1e3,'ms') if T>=1e-3 else (1e6,'µs');self.waveform.clear()
        present=[k for k in keys if k in v]
        if not present:self.status.setText('This point has no '+self.signal_view.currentText().lower()+(': add probes to the model' if 'Probes' in self.signal_view.currentText() else ''))
        pens=['#e9783c','#409ad6','#6eb671','#b0306a','#7b3fa0','#6b6100','#333333','#00876a']
        for i,key in enumerate(present):self.waveform.plot((t[take]-(t[-1]-2*T))*scale,v[key][take],pen=pg.mkPen(pens[i%len(pens)],width=1.5),name=key)
        self.waveform.setLabel('bottom',f'Time in the final two periods ({name})');self.waveform.setLabel('left',unit)

    def show_result(self,res):
        if res.get('format')==2:return self.show_general(res)
        self.show_kind(False)
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
            if self.result.get('format')==2:self.show_point();return self.general_waveform(folder)
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
