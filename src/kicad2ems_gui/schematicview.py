"""Editable simulation schematic and read-only KiCad source views."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from PySide6.QtCore import Qt,QObject,QPointF,QRectF,QProcess,QTimer,Signal
from PySide6.QtGui import QColor,QPainter,QPainterPath,QPen,QBrush,QFont
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QSplitter,QLabel,
    QPushButton,QLineEdit,QComboBox,QCheckBox,QPlainTextEdit,QScrollArea,QGraphicsView,
    QGraphicsScene,QGraphicsObject,QGraphicsItem,QDialog,QDialogButtonBox,QTableWidget,
    QTableWidgetItem,QHeaderView,QFileDialog,QStackedWidget)


def _api():
    # GUI remains usable without the optional circuit package.
    from pcbqs import schematic
    return schematic


def _number(value):
    return f'{value:.17g}' if isinstance(value,(int,float)) else str(value)


def _quantity(value,unit):
    if not isinstance(value,(int,float)):return str(value)
    for exponent,prefix in [(9,'G'),(6,'M'),(3,'k'),(0,''),(-3,'m'),(-6,'µ'),(-9,'n'),(-12,'p'),(-15,'f')]:
        if abs(value)>=10**exponent:return f'{value/10**exponent:.4g} {prefix}{unit}'
    return f'{value:g} {unit}'


def _entry(value):
    if not isinstance(value,(int,float)):return str(value)
    for exponent,prefix in [(9,'G'),(6,'M'),(3,'k'),(0,''),(-3,'m'),(-6,'u'),(-9,'n'),(-12,'p'),(-15,'f')]:
        if abs(value)>=10**exponent:return f'{value/10**exponent:.12g}{prefix}'
    return f'{value:.12g}'


def _natural(text):
    import re
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r'(\d+)',text)]


class KiCadJob(QObject):
    completed=Signal(dict,object)
    failed=Signal(str)
    progress=Signal(str)

    def __init__(self,path,parent=None):
        super().__init__(parent);self.path=Path(path).expanduser().resolve();self.temp=tempfile.TemporaryDirectory(prefix='pcbqs-gui-');self.proc=None;self.stage='netlist';self.document=None;self.cancelled=False

    def start(self):
        if self.cancelled:return
        if self.path.suffix.lower()!='.kicad_sch':
            try:self.document=_api().read_netlist(self.path)
            except (OSError,ValueError) as exc:self.failed.emit(str(exc));self.cleanup();return
            self.completed.emit(self.document,{});self.cleanup();return
        exe=shutil.which('kicad-cli')
        if not exe:self.failed.emit('Install kicad-cli or import an exported KiCad XML netlist.');self.cleanup();return
        self.exe=exe;self._launch(['sch','export','netlist','--format','kicadxml','--output',str(Path(self.temp.name)/'netlist.xml'),str(self.path)])

    def _launch(self,args):
        self.proc=QProcess(self);self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.finished.connect(self._finished);self.proc.errorOccurred.connect(self._error)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(120000);self.timer.timeout.connect(self._timeout);self.timer.start()
        self.progress.emit('Reading KiCad connectivity…' if self.stage=='netlist' else 'Rendering read-only KiCad sheets…')
        self.proc.start(self.exe,args)

    def _error(self,error):
        if error==QProcess.FailedToStart:
            self.timer.stop();self.failed.emit('Could not start kicad-cli');self.cleanup()

    def _timeout(self):
        self.cancel();self.failed.emit('KiCad export timed out after 120 seconds')

    def _finished(self,code,*_):
        if self.cancelled:return
        self.timer.stop();log=bytes(self.proc.readAllStandardOutput()).decode(errors='replace');self.proc.deleteLater();self.proc=None
        if self.stage=='netlist':
            try:
                if code:raise ValueError('KiCad netlist export failed: '+log.strip())
                self.document=_api().read_netlist(Path(self.temp.name)/'netlist.xml')
                self.document.update(path=str(self.path),kind='kicad_sch',sha256=hashlib.sha256(self.path.read_bytes()).hexdigest())
            except (OSError,ValueError) as exc:self.failed.emit(str(exc));self.cleanup();return
            self.stage='svg';folder=Path(self.temp.name)/'sheets';folder.mkdir()
            self._launch(['sch','export','svg','--output',str(folder),str(self.path)])
        else:
            try:sheets={p.name:p.read_bytes() for p in sorted((Path(self.temp.name)/'sheets').glob('*.svg'))} if not code else {}
            except OSError as exc:
                sheets={};self.progress.emit('Connectivity imported; could not read source sheets: '+str(exc))
            if code:self.progress.emit('Connectivity imported; KiCad sheet rendering was unavailable: '+log.strip())
            self.completed.emit(self.document,sheets);self.cleanup()

    def cancel(self):
        self.cancelled=True
        if self.proc and self.proc.state()!=QProcess.NotRunning:
            self.proc.kill();self.proc.waitForFinished(2000)
        self.cleanup()

    def cleanup(self):
        if hasattr(self,'timer'):self.timer.stop()
        self.temp.cleanup()


class ImportReview(QDialog):
    def __init__(self,document,config,parent=None):
        super().__init__(parent);self.setWindowTitle('Review KiCad simulation import');self.resize(1100,650);self.document=document;self.config=config
        layout=QVBoxLayout(self)
        note=QLabel('Choose the components to apply. Existing parasitics are retained unless matching numeric ESR/ESL/DCR fields are supplied.\nIC logic and gate-driver behavior require explicit simulation models. DNP/excluded parts are imported disabled.');note.setWordWrap(True);layout.addWidget(note)
        controls=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Filter reference, value, net or sheet');self.search.textChanged.connect(self.filter);controls.addWidget(self.search,1)
        for label,mode in [('Existing only','existing'),('Supported passives','all'),('None','none')]:
            b=QPushButton(label);b.clicked.connect(lambda _,m=mode:self.select(m));controls.addWidget(b)
        layout.addLayout(controls)
        self.table=QTableWidget(len(document['components']),8);self.table.setHorizontalHeaderLabels(['Apply','Reference','KiCad value','Simulation value','Model','Pins → nets','Sheet','Import status']);self.table.setEditTriggers(QTableWidget.NoEditTriggers);self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents);self.table.horizontalHeader().setSectionResizeMode(5,QHeaderView.Stretch)
        self.eligible=[]
        for row,c in enumerate(document['components']):
            status,default=_api().import_status(c,config);eligible=c['supported_passive'] or (c['kind']=='mosfet' and any(s['ref']==c['ref'] for s in config.get('switches',[])));self.eligible.append(eligible)
            check=QTableWidgetItem();check.setFlags(Qt.ItemIsUserCheckable|Qt.ItemIsEnabled if eligible else Qt.NoItemFlags);check.setCheckState(Qt.Checked if default else Qt.Unchecked);self.table.setItem(row,0,check)
            existing=next((p for p in config['components'] if p['ref']==c['ref']),None)
            present=_quantity(existing['value'],dict(resistor='Ω',capacitor='F',inductor='H')[existing['type']]) if existing else '—'
            values=[c['ref'],c['value'],present,c['kind'],', '.join(f"{p['number']} ({p['name']}) → {p['net'] or 'unconnected'}" for p in c['pins']),c['sheet'],status]
            for col,value in enumerate(values,1):
                item=QTableWidgetItem(value);item.setToolTip(value);self.table.setItem(row,col,item)
        layout.addWidget(self.table,1)
        self.connections=QCheckBox('Also update existing terminal connections from KiCad pins (review against the PCB before copper extraction)');layout.addWidget(self.connections)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(115);layout.addWidget(self.details)
        self.table.itemSelectionChanged.connect(self.show_details)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def selected_refs(self):
        return [c['ref'] for i,c in enumerate(self.document['components']) if self.table.item(i,0).checkState()==Qt.Checked]

    def select(self,mode):
        for i,c in enumerate(self.document['components']):
            if mode=='existing':on=_api().import_status(c,self.config)[1]
            elif mode=='all':on=self.eligible[i] and c['supported_passive'] and not c['dnp'] and not c['exclude_from_sim']
            else:on=False
            self.table.item(i,0).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def filter(self,text):
        text=text.lower()
        for row in range(self.table.rowCount()):self.table.setRowHidden(row,not any(text in self.table.item(row,col).text().lower() for col in range(1,self.table.columnCount())))

    def show_details(self):
        row=self.table.currentRow()
        if row>=0:self.details.setPlainText(json.dumps(self.document['components'][row],indent=2))


class ZoomView(QGraphicsView):
    def __init__(self,parent=None):
        super().__init__(parent);self.setRenderHints(QPainter.Antialiasing|QPainter.TextAntialiasing);self.setDragMode(QGraphicsView.ScrollHandDrag);self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse);self.setBackgroundBrush(QColor('#ffffff'))

    def wheelEvent(self,event):
        factor=1.15 if event.angleDelta().y()>0 else 1/1.15
        if .08<self.transform().m11()*factor<5:self.scale(factor,factor)
        event.accept()

    def fit(self):
        if self.scene() and self.scene().items():self.fitInView(self.scene().itemsBoundingRect().adjusted(-45,-45,45,45),Qt.KeepAspectRatio)


class DeviceItem(QGraphicsObject):
    def __init__(self,record,scene):
        super().__init__();self.record=record;self.owner=scene;self.setFlags(QGraphicsItem.ItemIsMovable|QGraphicsItem.ItemIsSelectable|QGraphicsItem.ItemSendsGeometryChanges);self.setZValue(2)
        self.setToolTip(record['ref']+'\n'+record.get('details','')+'\n'+'\n'.join(record['endpoints']))

    def boundingRect(self):return QRectF(-105,-57,210,130)

    def pin(self,index):return self.mapToScene(QPointF(-100 if index==0 else 100,8))

    def paint(self,painter,option,widget=None):
        r=self.record;enabled=r.get('enabled',True);color=QColor('#235e85' if enabled else '#999999')
        painter.setPen(QPen(QColor('#d18a00') if self.isSelected() else color,2 if self.isSelected() else 1.2));painter.setBrush(QColor('#fff2ce') if self.isSelected() else QColor('#f2f7fb') if enabled else QColor('#f5f5f5'));painter.drawRoundedRect(QRectF(-90,-52,180,104),7,7)
        font=QFont();font.setPointSize(10);font.setBold(True);painter.setFont(font);painter.setPen(color);painter.drawText(QRectF(-85,-46,170,20),Qt.AlignHCenter,r['ref'])
        font.setBold(False);font.setPointSize(8);painter.setFont(font);painter.drawText(QRectF(-85,-27,170,18),Qt.AlignHCenter,r.get('label',''))
        painter.setPen(QPen(color,1.8));y=8;painter.drawLine(-100,y,-32,y);painter.drawLine(32,y,100,y)
        kind=r['kind'];path=QPainterPath();path.moveTo(-32,y)
        if kind=='resistor':
            for x,dy in [(-25,0),(-20,-8),(-12,8),(-4,-8),(4,8),(12,-8),(20,8),(25,0),(32,0)]:path.lineTo(x,y+dy)
            painter.drawPath(path)
        elif kind=='capacitor':
            painter.drawLine(-32,y,-7,y);painter.drawLine(7,y,32,y);painter.drawLine(-7,y-13,-7,y+13);painter.drawLine(7,y-13,7,y+13)
        elif kind in ('inductor','coil'):
            for x in [-32,-16,0,16]:path.cubicTo(x,y-19,x+16,y-19,x+16,y)
            painter.drawPath(path)
        elif kind=='switch':
            painter.drawLine(-32,y,-17,y);painter.drawLine(-17,y,18,y-13);painter.drawLine(18,y,32,y);painter.drawEllipse(QPointF(-17,y),2.3,2.3);painter.drawEllipse(QPointF(18,y),2.3,2.3)
        else:
            painter.setBrush(Qt.NoBrush);painter.drawEllipse(QPointF(0,y),20,20);painter.drawLine(-32,y,-20,y);painter.drawLine(20,y,32,y);painter.drawText(QRectF(-16,y-15,32,30),Qt.AlignCenter,'+' if kind=='supply' else '↔')
        font.setPointSize(7);painter.setFont(font);painter.drawText(QRectF(-86,30,172,16),Qt.AlignHCenter,r.get('details','')[:38])
        painter.drawText(QRectF(-104,54,102,16),Qt.AlignLeft,r['nets'][0]);painter.drawText(QRectF(2,54,102,16),Qt.AlignRight,r['nets'][1])
        if not enabled:painter.drawLine(-82,-40,82,43)

    def itemChange(self,change,value):
        if change==QGraphicsItem.ItemPositionHasChanged and not self.owner.loading:self.owner.update_connections()
        return super().itemChange(change,value)

    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        if not self.owner.loading:QTimer.singleShot(0,self.owner.positions_changed)


class CircuitScene(QGraphicsScene):
    selected=Signal(str)
    moved=Signal(dict)

    def __init__(self,parent=None):
        super().__init__(parent);self.devices={};self.links=[];self.loading=False;self.last_positions={};self.selectionChanged.connect(self._selected)

    def _selected(self):
        if self.loading:return
        items=[i for i in self.selectedItems() if isinstance(i,DeviceItem)]
        self.selected.emit(items[0].record['id'] if items else '')
        self.highlight(items[0].record['nets'] if items else [])

    def load(self,records,positions):
        self.loading=True;self.clear();self.devices={};self.links=[]
        counters={}
        for r in records:
            item=DeviceItem(r,self);self.addItem(item);self.devices[r['id']]=item
            group=r['group'];row=counters.get(group,0);counters[group]=row+1
            defaults={'input':(100,row*155),'dc':(440,row*155),'bridgeA':(790,row*300+150),'bridgeB':(1110,row*300+150),'tank':(1470,row*155),'primary':(1810,330),'receiver':(2150,row*180+330),'other':(1810,row*160+650)}
            default=(100,-180) if r['id']=='supply' else defaults.get(group,(100,row*160))
            x,y=positions.get(r['id'],default);item.setPos(x,y)
        nets={}
        for item in self.devices.values():
            for index,net in enumerate(item.record['nets']):nets.setdefault(net,[]).append((item,index))
        for index,(net,pins) in enumerate(sorted(nets.items())):
            # Named hubs make topology explicit; only the selected net is emphasized.
            x=min(p.pin(i).x() for p,i in pins)-35-(index%3)*15;y=min(p.pin(i).y() for p,i in pins)-35
            hub=self.addEllipse(-4,-4,8,8,QPen(QColor('#8199aa')),QBrush(QColor('#8199aa')));hub.setPos(x,y);hub.setZValue(-1)
            label=self.addSimpleText(net);label.setBrush(QColor('#567083'));label.setPos(x+7,y-17);label.setZValue(0)
            for item,pin in pins:
                wire=self.addPath(QPainterPath(),QPen(QColor('#a8bac8'),.8));wire.setZValue(-2);self.links.append((net,wire,item,pin,hub))
        if 'primary' in self.devices and 'secondary' in self.devices:
            a=self.devices['primary'];b=self.devices['secondary'];line=self.addLine(a.x(),a.y()+68,b.x(),b.y()+68,QPen(QColor('#9561a9'),1.5,Qt.DashLine));line.setZValue(-1)
        self.loading=False;self.update_connections();self.last_positions=self.positions();self.setSceneRect(self.itemsBoundingRect().adjusted(-100,-100,100,100))

    def positions(self):return {key:[item.x(),item.y()] for key,item in self.devices.items()}

    def positions_changed(self):
        values=self.positions()
        if values!=self.last_positions:self.last_positions=values;self.moved.emit(values)

    def update_connections(self):
        for _,wire,item,index,hub in self.links:
            a,b=hub.scenePos(),item.pin(index);path=QPainterPath(a);mid=(a.x()+b.x())/2;path.lineTo(mid,a.y());path.lineTo(mid,b.y());path.lineTo(b);wire.setPath(path)

    def highlight(self,nets):
        for net,wire,*_ in self.links:
            on=net in nets;wire.setPen(QPen(QColor('#d2860b') if on else QColor('#a8bac8'),2 if on else .8));wire.setOpacity(1 if on or not nets else .16)

    def focus(self,key):
        if key not in self.devices:return
        self.clearSelection();item=self.devices[key];item.setSelected(True)
        for view in self.views():
            if view.transform().m11()<.7:view.resetTransform();view.scale(.85,.85)
            view.centerOn(item)


def records(config):
    api=_api();out=[]
    bank_nets={api.terminal_net(config,config['bridge_terminals'][0]),api.terminal_net(config,config['primary_terminals'][0])}
    def add(key,ref,kind,label,ends,group,details='',enabled=True):
        out.append(dict(id=key,ref=ref,kind=kind,label=label,endpoints=ends,nets=[api.terminal_net(config,t) for t in ends],group=group,details=details,enabled=enabled))
    for p in config.get('components',[]):
        kind=p.get('type','resistor');unit=dict(resistor='Ω',capacitor='F',inductor='H').get(kind,'');nets=[api.terminal_net(config,p[k]) for k in ['a','b']]
        group='tank' if set(nets)==bank_nets else 'dc' if set(nets)=={'GND','VHB'} else 'input' if p['ref'].startswith('CA') or p['ref'] in ('L3','R9') else 'other'
        paras=' · '.join(f"{k.split('_')[0]} {_quantity(p[k],'H' if k.endswith('_H') else 'Ω')}" for k in ['ESR_ohm','ESL_H','DCR_ohm'] if p.get(k))
        add('part:'+p['ref'],p['ref'],kind,_quantity(p.get('value',''),unit),[p['a'],p['b']],group,paras,p.get('enabled',True))
    for p in config.get('switches',[]):
        kind=p.get('model',{}).get('type',config.get('switch_model',{}).get('type','switch'));add('switch:'+p['ref'],p['ref'],'switch',kind,[p['a'],p['b']],'bridge'+p.get('leg','A'),p.get('leg','A')+(' high-side' if p.get('high') else ' low-side'))
    add('supply','SUPPLY','supply',_number(config.get('voltage_V',0))+' V',['NET:VIN','0'],'input','Source R/L included')
    add('primary','PRIMARY','coil',_quantity(config['primary']['L_H'],'H'),config['primary_terminals'],'primary',f"k={config['coupling']:g}; winding + SRF loss")
    add('secondary','SECONDARY','coil',_quantity(config['secondary']['L_H'],'H'),['SEC:A','SEC:B'],'receiver','Coupled receiver coil')
    add('receiver_cap','CSECONDARY','capacitor',_quantity(config['secondary_C_F'],'F') if 'secondary_C_F' in config else 'Auto tuned',['SEC:B','SEC:LOAD'],'receiver','Receiver compensation')
    add('load','LOAD','resistor',_quantity(config['load_ohm'],'Ω') if 'load_ohm' in config else 'Auto matched',['SEC:LOAD','SEC:A'],'receiver','AC-equivalent receiver load')
    return out


class SchematicEditor(QWidget):
    modelChanged=Signal(dict)
    statusChanged=Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent);self.config={};self.undo_stack=[];self.redo_stack=[];self.selected_key='';self.model_provider=None;self.job=None;self.fields={};self._sheets={};self._rendered_source=None;self._loading=False
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);bar=QHBoxLayout();root.addLayout(bar)
        self.mode=QComboBox();self.mode.addItems(['Simulation schematic','KiCad source sheets','KiCad component data']);bar.addWidget(self.mode)
        for text,slot in [('Import KiCad…',self.import_file),('Add passive…',self.add_passive),('Remove',self.remove_part),('Undo',self.undo),('Redo',self.redo),('Arrange',self.arrange),('Fit',self.fit)]:
            button=QPushButton(text);button.clicked.connect(slot);bar.addWidget(button)
        self.find=QLineEdit();self.find.setPlaceholderText('Find ref / net');self.find.returnPressed.connect(self.find_ref);bar.addWidget(self.find,1)
        self.stack=QStackedWidget();root.addWidget(self.stack,1);self.mode.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.graph=QSplitter(Qt.Horizontal);self.view=ZoomView();self.scene=CircuitScene(self);self.view.setScene(self.scene);self.graph.addWidget(self.view)
        self.scene.selected.connect(self.select);self.scene.moved.connect(self.save_positions)
        self.inspector=QScrollArea();self.inspector.setWidgetResizable(True);self.inspector.setMinimumWidth(250);self.graph.addWidget(self.inspector);self.graph.setSizes([1100,300]);self.stack.addWidget(self.graph)
        source=QWidget();sl=QVBoxLayout(source);row=QHBoxLayout();self.sheet=QComboBox();self.sheet.currentTextChanged.connect(self.show_sheet);row.addWidget(self.sheet,1);load=QPushButton('Load source sheets…');load.clicked.connect(self.load_source);row.addWidget(load);sl.addLayout(row);self.source_view=ZoomView();self.source_scene=QGraphicsScene(self);self.source_view.setScene(self.source_scene);sl.addWidget(self.source_view);self.stack.addWidget(source)
        data=QWidget();dl=QVBoxLayout(data);self.source_table=QTableWidget();self.source_table.setColumnCount(5);self.source_table.setHorizontalHeaderLabels(['Ref','Value','Kind','Pins → nets','Simulation']);self.source_table.setEditTriggers(QTableWidget.NoEditTriggers);self.source_table.setSelectionBehavior(QTableWidget.SelectRows);self.source_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents);self.source_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch);self.source_table.itemSelectionChanged.connect(self.source_details);self.source_table.cellDoubleClicked.connect(self.edit_source_part);dl.addWidget(self.source_table,2);self.source_info=QPlainTextEdit();self.source_info.setReadOnly(True);dl.addWidget(self.source_info,1);self.stack.addWidget(data)
        self.note=QLabel('Select a component to edit its model, parasitics and connections. Drag to arrange; wheel to zoom.');self.note.setWordWrap(True);root.addWidget(self.note)
        self.select('')

    def base_model(self):
        return copy.deepcopy(self.model_provider() if self.model_provider else self.config)

    def set_model(self,config,reset_history=True):
        _api().validate_edit(config);records(config)
        self.config=copy.deepcopy(config)
        if reset_history:self.undo_stack.clear();self.redo_stack.clear()
        self.rebuild()

    def rebuild(self):
        self._loading=True
        try:
            source=self.config.get('schematic',{}).get('source')
            if source!=self._rendered_source:self.set_sheets({});self._rendered_source=copy.deepcopy(source)
            _api().validate_edit(self.config);self.scene.load(records(self.config),self.config.get('schematic',{}).get('positions',{}));self.refresh_source()
            if self.selected_key in self.scene.devices:self.scene.devices[self.selected_key].setSelected(True)
            self.select(self.selected_key if self.selected_key in self.scene.devices else '')
        finally:self._loading=False

    def commit(self,change,message='Simulation model updated'):
        try:
            before=self.base_model();after=copy.deepcopy(before);change(after);_api().sync_primary_bank(before,after);_api().validate_edit(after)
        except (ValueError,KeyError,TypeError,ImportError) as exc:self.message(str(exc));return False
        if before==after:return True
        self.undo_stack.append(before);self.undo_stack=self.undo_stack[-50:];self.redo_stack.clear();self.config=after;self.rebuild();self.modelChanged.emit(copy.deepcopy(after));self.message(message);return True

    def message(self,text):self.note.setText(text);self.statusChanged.emit(text)

    def undo(self):
        if not self.undo_stack:return
        try:current=self.base_model()
        except (ValueError,KeyError) as exc:self.message(str(exc));return
        self.redo_stack.append(current);self.config=self.undo_stack.pop();self.rebuild();self.modelChanged.emit(copy.deepcopy(self.config));self.message('Undid schematic edit')

    def redo(self):
        if not self.redo_stack:return
        try:current=self.base_model()
        except (ValueError,KeyError) as exc:self.message(str(exc));return
        self.undo_stack.append(current);self.config=self.redo_stack.pop();self.rebuild();self.modelChanged.emit(copy.deepcopy(self.config));self.message('Redid schematic edit')

    def save_positions(self,positions):
        if self._loading:return
        self.commit(lambda c:c.setdefault('schematic',dict(format=1)).update(positions=positions),'Schematic arrangement saved')

    def arrange(self):
        self.commit(lambda c:c.setdefault('schematic',dict(format=1)).pop('positions',None),'Arranged schematic');self.fit()

    def fit(self):
        (self.source_view if self.mode.currentIndex()==1 else self.view).fit()

    def find_ref(self):
        text=self.find.text().strip().lower()
        key=next((key for key,item in self.scene.devices.items() if item.record['ref'].lower()==text),None)
        if key:self.mode.setCurrentIndex(0);self.scene.focus(key);return
        nets=[n for item in self.scene.devices.values() for n in item.record['nets'] if text in n.lower()]
        self.scene.highlight(nets)
        if nets:self.message('Highlighted nets: '+', '.join(sorted(set(nets))))
        else:self.message('No matching component or net')

    def _part(self,c,key):
        if key.startswith('part:'):return next(p for p in c['components'] if p['ref']==key[5:])
        if key.startswith('switch:'):return next(p for p in c['switches'] if p['ref']==key[7:])
        return c.get(key)

    def select(self,key):
        self.selected_key=key;body=QWidget();form=QFormLayout(body);self.fields={};self.field_originals={};self.choice=None;self.enabled=None;self.ends={};self.virtual_extra={}
        if not key:
            info=QLabel('Select a component in the schematic, or search its reference.\n\nConnections use PCB terminal names or NET:name. The bridge/WPT workflow supplies gate drive and receiver matching.');info.setWordWrap(True);form.addRow(info);self.inspector.setWidget(body);return
        record=next((r for r in records(self.config) if r['id']==key),None)
        if record is None:self.inspector.setWidget(body);return
        form.addRow(QLabel('<b>'+record['ref']+'</b>'))
        if key.startswith('part:'):
            part=self._part(self.config,key);self.choice=QComboBox();self.choice.addItems(_api().PASSIVES);self.choice.setCurrentText(part['type']);form.addRow('Component type',self.choice)
            self.enabled=QCheckBox('Include in simulation');self.enabled.setChecked(part.get('enabled',True));form.addRow(self.enabled)
            specs=[('value','Value (Ω / F / H)'),('ESR_ohm','ESR (Ω)'),('ESL_H','ESL (H)'),('DCR_ohm','DCR (Ω)'),('leakage_ohm','Leakage (Ω)'),('bias_factor','Capacitance bias factor')];target=part;inherited={}
        elif key.startswith('switch:'):
            part=self._part(self.config,key);target=part.get('model',{});inherited=self.config.get('switch_model',{});self.choice=QComboBox();self.choice.addItems(['inherit','ideal','switch','mosfet','vdmos','subcircuit']);self.choice.setCurrentText(target.get('type','inherit'));form.addRow('Switch model',self.choice)
            self.leg=QComboBox();self.leg.addItems(['A','B']);self.leg.setCurrentText(part.get('leg','A'));form.addRow('Gate phase leg',self.leg);self.high=QCheckBox('High-side gate timing');self.high.setChecked(part.get('high',False));form.addRow(self.high)
            specs=[(k,label) for k,label in [('Ron_ohm','On resistance (Ω)'),('Roff_ohm','Off resistance (Ω)'),('Vth_V','Threshold (V)'),('Kp_A_V2','Kp (A/V²)'),('rise_s','Rise time (s)'),('fall_s','Fall time (s)'),('dead_time_s','Dead time (s)'),('gate_V','Gate drive (V)'),('gate_R_ohm','Gate resistance (Ω)'),('Cds_F','Cds (F)'),('Cgd_F','Cgd (F)'),('Cgs_F','Cgs (F)'),('diode_TT_s','Diode TT (s)'),('package_L_H','Drain package L (H)'),('source_L_H','Source package L (H)')]]
            for k in ['library','subcircuit']:
                w=QLineEdit(str(target.get(k,'')));self.virtual_extra[k]=w;form.addRow(k,w)
        elif key in ('primary','secondary'):
            target=self.config[key];inherited={};specs=[('L_H','Inductance (H)'),('R_ohm','Winding DCR (Ω)'),('SRF_Hz','Self resonance (Hz)'),('Cp_F','Self capacitance (F)'),('Rac_ref_ohm','AC loss reference (Ω)'),('loss_reference_Hz','Loss reference (Hz)'),('core_R_ohm','Core resistance (Ω)')]
            self.choice=QComboBox();self.choice.addItems(['parallel_core','dc_only','series_ac']);self.choice.setCurrentText(target.get('loss_model','series_ac'));form.addRow('Coil loss model',self.choice)
            if key=='primary':specs.append(('primary_C_F','Primary C reference (F)'));target=dict(target,primary_C_F=self.config['primary_C_F'])
        elif key=='supply':
            target=dict(self.config.get('supply',{}),voltage_V=self.config['voltage_V']);inherited={};specs=[('voltage_V','Bridge supply (V)'),('R_ohm','Source resistance (Ω)'),('L_H','Source inductance (H)'),('ramp_s','Startup ramp (s)')]
        else:
            field='secondary_C_F' if key=='receiver_cap' else 'load_ohm';target=self.config;inherited={};specs=[(field,'Value (F)' if key=='receiver_cap' else 'Load (Ω)')];form.addRow(QLabel('Blank keeps per-frequency automatic tuning/matching.'))
        for name,label in specs:
            text=_entry(target[name]) if name in target else '';w=QLineEdit(text);self.field_originals[name]=(text,target.get(name));w.setPlaceholderText('Inherited: '+_entry(inherited[name]) if name in inherited else 'Optional / default');self.fields[name]=w;form.addRow(label,w)
        if key.startswith(('part:','switch:')) or key=='primary':
            options=sorted(set(self.config.get('terminals',{}))|{'NET:'+n for r in records(self.config) for n in r['nets'] if not n.startswith('SEC:')}|{'0'},key=_natural)
            ends=record['endpoints']
            for index,pin in enumerate(['a','b']):
                w=QComboBox();w.setEditable(True);w.addItems(options);w.setCurrentText(ends[index]);self.ends[pin]=w;form.addRow('Connection '+pin.upper(),w)
        note=QLabel('Numbers accept SI notation (33n, 24u, 110m). Blank optional fields remove overrides. Primary bank edits update its reference when it was synchronized.');note.setWordWrap(True);form.addRow(note)
        apply=QPushButton('Apply component changes');apply.clicked.connect(self.apply_selected);form.addRow(apply);self.inspector.setWidget(body)

    def apply_selected(self):
        key=self.selected_key
        try:
            values={name:self.field_originals[name][1] if w.text()==self.field_originals[name][0] else _api().engineering_value(w.text()) if w.text().strip() else None for name,w in self.fields.items()};ends={p:w.currentText().strip() for p,w in self.ends.items()};choice=self.choice.currentText() if self.choice else None;enabled=self.enabled.isChecked() if self.enabled else None;extras={k:w.text().strip() for k,w in self.virtual_extra.items()};leg=self.leg.currentText() if key.startswith('switch:') else None;high=self.high.isChecked() if key.startswith('switch:') else None
            if any(v is not None and v<0 for v in values.values()):raise ValueError('Component parameters must be nonnegative')
        except ValueError as exc:self.message(str(exc));return False
        def edit(c):
            if key.startswith('part:'):
                target=self._part(c,key);target.update(type=choice);target.update(ends)
                if not enabled or 'enabled' in target:target['enabled']=enabled
                if values.get('value') is None:raise ValueError('A component value is required')
            elif key.startswith('switch:'):
                part=self._part(c,key);part.update(ends,leg=leg,high=high);target=part.setdefault('model',{})
                if choice=='inherit':target.pop('type',None)
                else:target['type']=choice
                for name,value in extras.items():
                    if value:target[name]=value
                    else:target.pop(name,None)
            elif key in ('primary','secondary'):
                target=c[key];target['loss_model']=choice
                if any(values.get(k) in (None,0) for k in ['L_H','R_ohm']):raise ValueError('Coil inductance and DCR must be positive')
                if key=='primary':c['primary_terminals']=[ends['a'],ends['b']];c['primary_C_F']=values.pop('primary_C_F')
            elif key=='supply':target=c.setdefault('supply',{});c['voltage_V']=values.pop('voltage_V')
            else:target=c
            for name,value in values.items():
                if value is None:target.pop(name,None)
                else:target[name]=value
        return self.commit(edit)

    def add_passive(self):
        dialog=QDialog(self);dialog.setWindowTitle('Add simulation passive');form=QFormLayout(dialog);ref=QLineEdit('RNEW');kind=QComboBox();kind.addItems(_api().PASSIVES);value=QLineEdit('1k');a=QLineEdit('NET:VHB');b=QLineEdit('0')
        for label,w in [('Reference',ref),('Type',kind),('Value (SI)',value),('Connection A',a),('Connection B',b)]:form.addRow(label,w)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);form.addRow(buttons);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec()!=QDialog.Accepted:return
        try:part=dict(ref=ref.text().strip(),type=kind.currentText(),value=_api().engineering_value(value.text()),a=a.text().strip(),b=b.text().strip())
        except ValueError as exc:self.message(str(exc));return
        self.selected_key='part:'+part['ref'];self.commit(lambda c:c['components'].append(part),'Added '+part['ref']);self.scene.focus(self.selected_key)

    def remove_part(self):
        key=self.selected_key
        if not key.startswith('part:'):self.message('Only explicit passive components can be removed here; bridge/coil roles are edited through their properties.');return
        self.commit(lambda c:c.update(components=[p for p in c['components'] if 'part:'+p['ref']!=key]),'Removed simulation component')

    def import_file(self):
        path,_=QFileDialog.getOpenFileName(self,'Import KiCad information','','KiCad schematic / XML netlist (*.kicad_sch *.xml);;All files (*)')
        if path:self.import_path(path)

    def import_path(self,path,view_only=False):
        try:self.base_model()
        except (ValueError,KeyError) as exc:self.message('Fix the model JSON before importing: '+str(exc));return
        if self.job:self.job.cancel();self.job.deleteLater()
        self.job=KiCadJob(path,self);self.job.progress.connect(self.message);self.job.failed.connect(self.message);self.job.completed.connect(lambda doc,sheets:self.import_ready(doc,sheets,view_only));QTimer.singleShot(0,self.job.start)

    def import_ready(self,document,sheets,view_only=False):
        if view_only:
            self.set_sheets(sheets);self.mode.setCurrentIndex(1)
            if document.get('sha256')!=self.config.get('schematic',{}).get('source',{}).get('sha256'):self.message('Source file changed; re-import to review connectivity and values.')
            return
        try:
            current=self.base_model();_api().validate_edit(current)
        except (ValueError,KeyError,TypeError,ImportError) as exc:self.message('Fix the model before applying this import: '+str(exc));return
        review=ImportReview(document,current,self)
        if review.exec()!=QDialog.Accepted:return
        refs=review.selected_refs()
        def change(c):
            imported=_api().apply_import(c,document,refs,review.connections.isChecked());c.clear();c.update(imported)
        if self.commit(change,f'Imported {len(refs)} selected components; source has {len(document["components"])} components'):
            self.set_sheets(sheets)

    def set_sheets(self,sheets):
        self._sheets=sheets;self.sheet.blockSignals(True);self.sheet.clear();self.sheet.addItems(list(sheets));self.sheet.blockSignals(False)
        if sheets:self.show_sheet(next(iter(sheets)))
        else:self.source_scene.clear()

    def show_sheet(self,name):
        if name not in self._sheets:return
        try:
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtSvgWidgets import QGraphicsSvgItem
        except ImportError:
            self.message('Qt SVG support is needed for source sheets; simulation editing is available. Install the matching PySide6-Addons package.');return
        self.source_scene.clear();item=QGraphicsSvgItem();item.renderer_ref=QSvgRenderer(self._sheets[name])
        if not item.renderer_ref.isValid():self.message('Could not render this KiCad source sheet');return
        item.setSharedRenderer(item.renderer_ref);self.source_scene.addItem(item);self.source_view.fit()

    def load_source(self):
        source=self.config.get('schematic',{}).get('source',{});path=source.get('path','')
        if not path.endswith('.kicad_sch') or not Path(path).is_file():path,_=QFileDialog.getOpenFileName(self,'Read-only KiCad sheet','','KiCad schematic (*.kicad_sch)')
        if path:self.import_path(path,view_only=True)

    def refresh_source(self):
        self.source_components=self.config.get('schematic',{}).get('source',{}).get('components',[]);self.source_table.setRowCount(len(self.source_components));configured={p['ref'] for p in [*self.config.get('components',[]),*self.config.get('switches',[])]}
        for row,c in enumerate(self.source_components):
            for col,value in enumerate([c['ref'],c['value'],c['kind'],', '.join(p['number']+' → '+(p['net'] or 'unconnected') for p in c['pins']),'Configured' if c['ref'] in configured else 'Not in simulation']):
                item=QTableWidgetItem(value);item.setToolTip(value);self.source_table.setItem(row,col,item)

    def source_details(self):
        row=self.source_table.currentRow()
        if 0<=row<len(self.source_components):self.source_info.setPlainText(json.dumps(self.source_components[row],indent=2))

    def edit_source_part(self,row,*_):
        ref=self.source_components[row]['ref'];key=next((key for key,item in self.scene.devices.items() if item.record['ref']==ref),None)
        if key:self.mode.setCurrentIndex(0);self.scene.focus(key)
        else:self.message(ref+' is not in the simulation; use Import KiCad to select supported passives.')

    def cancel_import(self):
        if self.job:self.job.cancel()
