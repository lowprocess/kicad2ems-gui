"""The Circuit page: a circuit model (pcbqs.circuit's, format 2: any circuit of parts, nodes and drives) as a
schematic to edit, and as JSON.

A model comes from a file: a study's config names it ([analysis.circuit] model = "buck.json", a path beside the
config), and the circuits to start from are examples like any other, under File > Examples > Circuits. Saving the
study writes the model back beside its config.

The page is the model's editor only. Its settings are a panel made from the circuit plugin's options, as every
analysis's are (analysispanel.AnalysisPanel: the tools' own tables, `--describe`), in the Study dock when the page
is the window's. Under them, a section Model has the values the model itself holds: its parameters and its sweep.
A run is the plugin's command on the model as edited (written into the run's folder); what
it leaves is shown where every result is: its report, tables and waveforms on the Results page, its fields in the
Viewer, its log on the Run page."""
import json,os
from pathlib import Path
from PySide6.QtCore import QTimer,Qt
from .schematicview import SchematicEditor
from .analysispanel import AnalysisPanel,config_values
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QPushButton,QComboBox,QPlainTextEdit,
                               QTabWidget,QFileDialog,QLabel,QSplitter,QScrollArea,QTableWidget,QTableWidgetItem,QHeaderView)

def _is_number(text):
    try:float(text);return True
    except (TypeError,ValueError):return False


def _plugin():
    """The circuit analysis: kicad2ems's registry's, else pcbqs's own (the page alone, without the registry)."""
    try:
        from kicad2ems.api.frontend import analyses
        a=analyses().get('circuit')
        if a is not None:return a
    except ImportError:pass
    from pcbqs.analyses import Circuit
    return Circuit()


class _Run:
    """The circuit plugin as the page's panel runs it: the model is the page's (Load model…), not an option, and a
    run is of the model as edited, written into the run's folder first."""
    def __init__(self,plugin,page):self._p,self._page=plugin,page
    def __getattr__(self,name):return getattr(self._p,name)
    def options(self):return [o for o in self._p.options() if o['key']!='model']
    def tag(self,values):return self._page.run_tag()

    def _ready(self,values,board):
        """(the model as edited, its board), or ValueError: what a run still needs."""
        page=self._page
        try:c=page.values()
        except (ValueError,KeyError) as e:raise ValueError(f'The model needs attention: {e}') from None
        on=lambda k:values.get(k) is True or str(values.get(k)).strip().lower() in ('1','true','yes','on')
        board=page.board.text().strip() or (c.get('board') or {}).get('file','') or board
        if (on('copper') or on('fields')) and not (board and Path(board).is_file()):
            raise ValueError("Choose the model's board: Import KiCad… a .kicad_pcb, or name one under Files")
        return c,board

    def missing(self,values,board,results=None):
        """What a run of the model as edited still needs (kicad2ems 2.9); nothing is written."""
        try:self._ready(values,board)
        except ValueError as e:return [dict(text=str(e),key=None)]
        return []

    def command(self,values,board,out,preview=False,results=None):
        c,board=self._ready(values,board)
        os.makedirs(out,exist_ok=True)
        model=os.path.join(out,'model-input.json');Path(model).write_text(json.dumps(c,indent=2))
        mine={o['key'] for o in self.options()}
        return self._p.command(dict({k:v for k,v in values.items() if k in mine},model=model),board,out,preview,results)


class PowerCircuitTab(QWidget):
    def __init__(self,win=None,plugin=None):
        super().__init__();self.win=win;self._syncing=False;self.asked=None
        root=QVBoxLayout(self)
        self.matching_note=QLabel();self.matching_note.setWordWrap(True);root.addWidget(self.matching_note)
        row=QHBoxLayout();root.addLayout(row);self.top_row=row
        for text,slot in [('Load model…',self.load_model),('Save model…',self.save_model),('Choose PCB…',self.choose_board)]:
            b=QPushButton(text);b.clicked.connect(slot);row.addWidget(b)
        self.split=QSplitter(Qt.Horizontal);root.addWidget(self.split,1)
        self.editor=QPlainTextEdit();self.editor.setPlaceholderText('Component model JSON: per-part types, ESR/ESL/DCR, coil loss/SRF, switch parameters, input filter…')
        self.schematic=SchematicEditor(self);self.schematic.model_provider=self.values
        self.model_tabs=QTabWidget();self.model_tabs.addTab(self.schematic,'Schematic');self.model_tabs.addTab(self.editor,'Model JSON')
        self.split.addWidget(self.model_tabs)
        # its settings: the plugin's options as a panel (the Study dock's, in the window), and the model's own values
        self.plugin=plugin or _plugin()
        self.panel=AnalysisPanel(_Run(self.plugin,self),win)
        self.board,self.outdir,self.status,self.log=self.panel.board,self.panel.outdir,self.panel.status,self.panel.log
        self.run_btn,self.stop_btn=self.panel.run_btn,self.panel.stop_btn
        self.board.setPlaceholderText("the model's board, else the study's" if win is not None else "the model's board")
        w=self.panel.w
        self.copper,self.fields,self.jobs=w.get('copper'),w.get('fields'),w.get('jobs')
        if self.copper is not None and self.fields is not None:     # the fields are of the copper's currents
            self.fields.toggled.connect(lambda on:self.copper.setChecked(True) if on else None)
            self.copper.toggled.connect(lambda on:self.fields.setChecked(False) if not on else None)
        # the model's own values: its parameters, and what it sweeps
        self.params=QTableWidget(0,2);self.params.setHorizontalHeaderLabels(['Parameter','Value']);self.params.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.params.verticalHeader().hide();self.params.setMaximumHeight(170);self.params.setToolTip("The model's parameters: its values may be expressions of them (vout/iout). A number, SI notation (22u) or an expression of the others")
        self.sweep=QLineEdit();self.sweep.setPlaceholderText('e.g.  parameters.vin: 9, 12, 15;  R1.resistance_ohm: 24, 48')
        self.sweep.setToolTip('What to sweep: a path of the model and its values; several, separated by semicolons, run in every combination')
        form=self.panel.forms.get('Model')
        if form is None:
            holder=QWidget();form=QFormLayout(holder);form.setContentsMargins(0,0,0,0);form.setRowWrapPolicy(QFormLayout.WrapLongRows)
            self.panel.add_section('Model',holder,form)
        form.insertRow(0,'Parameters',self.params);form.insertRow(1,'Sweep',self.sweep);self.model_form=form
        self.panel.sections['Model'].set_expanded(True)
        self.refresh_timer=QTimer(self);self.refresh_timer.setSingleShot(True);self.refresh_timer.setInterval(250);self.refresh_timer.timeout.connect(self.refresh_schematic)
        self.params.itemChanged.connect(lambda *_:self._model_edited())
        self.sweep.textEdited.connect(lambda *_:self.panel._edited());self.sweep.editingFinished.connect(self.refresh_schematic)
        self.schematic.modelChanged.connect(self.schematic_changed)      # (the schematic has its own note line)
        self.editor.textChanged.connect(lambda:self.refresh_timer.start() if not self._syncing else None)
        self.model_path=None                                        # the file the model came from (a config's, a loaded one)
        if win is not None:                                         # the circuits to start from: the window's examples
            self.examples_btn=QPushButton('Examples');self.examples_btn.setToolTip('The circuits to start from: File > Examples > Circuits')
            self.examples_btn.clicked.connect(self.show_examples);self.top_row.insertWidget(0,self.examples_btn)
        else:                                                       # alone: its settings and its Run beside the model
            self._scroll=QScrollArea();self._scroll.setWidgetResizable(True);self._scroll.setWidget(self.panel);self.split.addWidget(self._scroll)
        try:
            self.set_model(self.template('simple'))                  # a small circuit to open on, not a board's
        except (OSError,ValueError,ImportError,KeyError,TypeError) as e:self.status.setText("Install/update pcbqs with python -m pip install 'kicad2ems[qs]': "+str(e));self.run_btn.setEnabled(False)

    # ---- the run: the panel's (the plugin's command, its log and status) ----
    proc=property(lambda self:self.panel.proc)
    out=property(lambda self:self.panel.out,lambda self,v:setattr(self.panel,'out',v))

    def settings_panel(self):
        """The settings out of the page, for the window's Study dock (its Run starts the run then)."""
        return self.panel

    def start(self,preview=False):
        self.panel.asked=self.asked
        self.panel.start()

    def stop(self):
        self.panel.stop()
        self.schematic.cancel_import()

    def closeEvent(self,event):
        self.stop()
        if self.proc:self.proc.waitForFinished(3000)
        super().closeEvent(event)

    def run_tag(self):
        """A run's name: the model file's, else the model's own."""
        if self.model_path:return Path(self.model_path).stem
        try:name=json.loads(self.editor.toPlainText()).get('name') or 'circuit'
        except ValueError:name='circuit'
        return ''.join(ch if ch.isalnum() else '_' for ch in name).strip('_')[:40] or 'circuit'

    def open_run(self,folder):
        """A run's folder is the one shown (picked under Results of): what the others may start from. False: it
        holds no circuit result."""
        if not self.plugin.owns(str(folder)):return False
        self.panel.out=str(folder);self.panel.show_result(str(folder))
        return True

    def board_path(self):
        """The PCB named here, else the study's board (the window's settings)."""
        return self.panel.board_path()

    def show_examples(self):
        """The window's menu of the circuit examples (File > Examples), here where a circuit is started."""
        menus=getattr(self.win,'example_menus',{});whose=getattr(self.win,'example_sources',{})
        menu=next((m for path,m in menus.items() if 'circuit' in whose.get(path,())),None)   # the group the circuit analysis ships
        if menu is None:self.status.setText('No circuit examples are installed (File > Examples)');return
        menu.exec(self.examples_btn.mapToGlobal(self.examples_btn.rect().bottomLeft()))

    # ---- the models to start from ----
    @staticmethod
    def templates():
        """pcbqs's example circuits: {name: what it is}; none from a pcbqs without pcbqs.circuit."""
        try:
            from pcbqs.circuit import model
            return dict(model.templates())
        except (ImportError,OSError,ValueError):return {}

    @classmethod
    def template(cls,name):
        """A model to start from: one of pcbqs.circuit's examples ('simple' is its boost converter)."""
        names=cls.templates()
        if name=='simple' and 'boost' in names:name='boost'
        if name not in names:raise ValueError(f'no circuit template {name!r} (pcbqs.circuit has {", ".join(names) or "none"})')
        from pcbqs.circuit import model
        return model.template(name)

    def new_model(self,name):
        try:self.set_model(self.template(name));self.model_path=None;self.status.setText(f'Started from the {name} template.')
        except (OSError,ValueError,ImportError) as e:self.status.setText('Template unavailable: '+str(e))

    def shown(self):
        """The settings the page shows: the options' keys, and the model's parameters and sweep."""
        return [o['key'] for o in self.panel.options]+['parameters','sweep']

    def _model_edited(self):
        if not self._syncing:
            self.refresh_timer.start();self.panel._edited()

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

    # ---- the model ----
    def set_model(self,c,diagram=True):
        """A model into the page; a ValueError for one that is not a circuit model (format 2)."""
        if c.get('format')!=2:
            raise ValueError("not a circuit model (format 2): the full-bridge tool's (format 1) is no longer; pcbqs's "
                             "data/wpthb_bridge.json is that bridge as a circuit model")
        self._syncing=True
        try:
            if diagram:self.schematic.set_model(c)
            self.params.setRowCount(0)
            for name,value in c.get('parameters',{}).items():
                row=self.params.rowCount();self.params.insertRow(row);key=QTableWidgetItem(name);key.setFlags(key.flags()&~Qt.ItemIsEditable)
                self.params.setItem(row,0,key);self.params.setItem(row,1,QTableWidgetItem(f'{value:g}' if isinstance(value,(int,float)) else str(value)))
            self.sweep.setText(self.sweep_text(c.get('sweep',{})))
            targets=';  '.join(f"{t['adjust']} is adjusted until {t['measure']} = {t['value']}" for t in c.get('targets',[]))
            self.matching_note.setText((c.get('description') or '')+('  —  '+targets if targets else ''))
            self.editor.setPlainText(json.dumps(c,indent=2))
        finally:self._syncing=False
        if diagram:QTimer.singleShot(0,self.schematic.fit)

    def schematic_changed(self,c):
        self.refresh_timer.stop();self.set_model(c,diagram=False);self.panel._edited()

    def refresh_schematic(self,*_):
        if self._syncing:return
        try:self.schematic.set_model(self.values())
        except (ValueError,KeyError,TypeError,ImportError) as exc:self.status.setText('Model needs attention: '+str(exc))

    def values(self):
        """The model as edited: the JSON, with its parameters and sweep as typed in their fields."""
        c=json.loads(self.editor.toPlainText())
        for row in range(self.params.rowCount()):
            name,text=self.params.item(row,0).text(),self.params.item(row,1).text().strip()
            if name in c.get('parameters',{}) and text:c['parameters'][name]=float(text) if _is_number(text) else text
        sweep=self.sweep_of(self.sweep.text())
        if sweep:c['sweep']=sweep
        else:c.pop('sweep',None)
        return c
    def load_model(self,path=None):
        """A model from a file (asked for when none is named): its libraries and its board, named beside it, found
        from where it is. True when it loaded."""
        p=path or QFileDialog.getOpenFileName(self,'Circuit model','','JSON (*.json)')[0]
        if not p:return False
        try:
            here=Path(p).resolve().parent
            c=json.loads(Path(p).read_text())
            for part in c.get('parts',[]):
                if part.get('model',{}).get('library'):part['model']['library']=str((here/part['model']['library']).resolve())
            board=(c.get('board') or {}).get('file')
            if board and not Path(board).is_absolute():c['board']['file']=str((here/board).resolve())
            self.set_model(c);self.model_path=str(Path(p).resolve())
            return True
        except (OSError,ValueError,KeyError) as e:self.status.setText(f'{Path(p).name}: {e}');return False

    def write_model(self,path,c=None):
        """The model as a file: its board named relative to it when it is beside it (a study's folder moves whole)."""
        c=json.loads(json.dumps(self.values() if c is None else c));here=Path(path).resolve().parent
        board=(c.get('board') or {}).get('file')
        if board and Path(board).is_absolute() and Path(board).resolve().parent==here:c['board']['file']=Path(board).name
        Path(path).write_text(json.dumps(c,indent=2))

    def save_model(self):
        try:c=self.values()
        except (ValueError,KeyError) as e:self.status.setText(str(e));return
        p,_=QFileDialog.getSaveFileName(self,'Save circuit model','model.json','JSON (*.json)')
        if p:Path(p).write_text(json.dumps(c,indent=2))

    def choose_board(self):
        p,_=QFileDialog.getOpenFileName(self,'PCB layout','','PCB (*.kicad_pcb *.json)')
        if p:self.board.setText(p)

    # ---- a study's config: [analysis.circuit] ----
    def load_settings(self,tab):
        """A config's [analysis.circuit] table (its paths already whole): the model it names, the options it sets
        (the copper and fields ticks, the engine), a board and a folder of its own. An empty one: the page as it
        opens."""
        tab=dict(tab)
        self.panel.reset();self.panel.set_own(tab.pop('board',None),tab.pop('out',None))
        model=tab.pop('model',None)
        on=lambda k:tab.get(k) is True or str(tab.get(k)).strip().lower() in ('1','true','yes','on')
        if on('fields'):tab['copper']=True
        if model:
            if self.load_model(str(model)):self.status.setText(f"Model: {Path(str(model)).name}")
        elif self.model_path is not None:
            try:self.set_model(self.template('simple'))
            except (OSError,ValueError,ImportError,KeyError,TypeError):pass
            self.model_path=None
        else:                                                       # the model stays: its values back in their fields
            try:self.set_model(json.loads(self.editor.toPlainText()),diagram=False)
            except (ValueError,KeyError):pass
        self.panel.set_values(tab)

    def save_settings(self,config):
        """What the config at `config` holds of the circuit, {key: value} (paths relative to it), the model written
        as a file: the one it came from, else <config>_circuit.json beside the config. {}: the page was never
        given a model and the analysis is not asked, so the study has no circuit."""
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
        mine={o['key'] for o in self.panel.options}
        tab.update({k:v for k,v in config_values(self.panel,str(base)).items() if k in ('board','out') or k in mine})
        return tab
