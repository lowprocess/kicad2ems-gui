"""Visual edits must reach the simulation model without losing JSON or topology."""
import json,sys
import pytest
from PySide6.QtWidgets import QApplication
from kicad2ems_gui.powercircuittab import PowerCircuitTab
from kicad2ems_gui.schematicview import ImportReview,KiCadJob


@pytest.fixture
def tab():
    app=QApplication.instance() or QApplication([]);widget=PowerCircuitTab();widget.new_model('wpthb');yield widget;widget.close();app.processEvents()


def test_component_edit_and_undo_redo_reach_json_and_run_values(tab):
    view=tab.schematic;view.select('part:C25');view.fields['value'].setText('47n');view.fields['ESR_ohm'].setText('12m')
    assert view.apply_selected()
    c=tab.values();part=next(p for p in c['components'] if p['ref']=='C25')
    assert part['value']==pytest.approx(47e-9) and part['ESR_ohm']==.012
    assert c['primary_C_F']==pytest.approx(113e-9)
    assert json.loads(tab.editor.toPlainText())['primary_C_F']==c['primary_C_F']
    view.undo();assert next(p for p in tab.values()['components'] if p['ref']=='C25')['value']==33e-9
    view.redo();assert next(p for p in tab.values()['components'] if p['ref']=='C25')['value']==pytest.approx(47e-9)


def test_connections_switch_override_and_auto_receiver_controls(tab):
    view=tab.schematic;view.select('part:L3');view.ends['a'].setCurrentText('NET:CUSTOM');view.fields['DCR_ohm'].setText('75m');assert view.apply_selected()
    assert next(p for p in tab.values()['components'] if p['ref']=='L3')['a']=='NET:CUSTOM'
    view.select('switch:Q1');view.choice.setCurrentText('switch');view.fields['Ron_ohm'].setText('15m');assert view.apply_selected()
    assert next(p for p in tab.values()['switches'] if p['ref']=='Q1')['model']['Ron_ohm']==.015
    view.select('receiver_cap');view.fields['secondary_C_F'].setText('100n');assert view.apply_selected()
    assert tab.values()['secondary_C_F']==pytest.approx(100e-9)
    assert float(tab.receiver_C.text())==pytest.approx(100)
    view.select('receiver_cap');view.fields['secondary_C_F'].clear();assert view.apply_selected();assert 'secondary_C_F' not in tab.values()


def test_invalid_json_is_not_overwritten_by_diagram_edit(tab):
    view=tab.schematic;view.select('part:C25');view.fields['value'].setText('47n');tab.editor.setPlainText('{ incomplete')
    assert not view.apply_selected();assert tab.editor.toPlainText()=='{ incomplete'
    assert next(p for p in view.config['components'] if p['ref']=='C25')['value']==33e-9


def test_layout_round_trip_top_overrides_and_noop_precision(tab):
    original=tab.values();tab.schematic.select('primary');assert tab.schematic.apply_selected()
    assert tab.values()['primary']==original['primary']
    tab.overrides['cap_ESR'].setText('20');tab.refresh_schematic()
    tab.schematic.save_positions({'part:C25':[123.5,456]})
    c=tab.values();assert c['schematic']['positions']['part:C25']==[123.5,456]
    assert all(p['ESR_ohm']==.02 for p in c['components'] if p['type']=='capacitor')
    tab.set_model(json.loads(json.dumps(c)));assert tab.schematic.scene.devices['part:C25'].pos().x()==123.5


def test_render_and_selection_are_functional(tab):
    tab.resize(1500,1000);tab.show();QApplication.processEvents();tab.schematic.scene.focus('switch:Q2');QApplication.processEvents()
    assert tab.schematic.selected_key=='switch:Q2'
    assert not tab.grab().isNull()
    tab.schematic.find.setText('VHB');tab.schematic.find_ref();assert 'VHB' in tab.schematic.note.text()


def test_import_review_requires_explicit_additions_and_marks_dnp(tab):
    from PySide6.QtCore import Qt
    doc=dict(components=[dict(ref='C25',value='47n',kind='capacitor',supported_passive=True,dnp=False,exclude_from_sim=False,sheet='/',pins=[dict(number='1',name='',net='VHB'),dict(number='2',name='',net='GND')]),dict(ref='RNEW',value='1k',kind='resistor',supported_passive=True,dnp=False,exclude_from_sim=False,sheet='/',pins=[]),dict(ref='C17',value='33n',kind='capacitor',supported_passive=True,dnp=True,exclude_from_sim=False,sheet='/',pins=[])])
    dialog=ImportReview(doc,tab.values());assert dialog.selected_refs()==['C25']
    assert '33' in dialog.table.item(0,3).text() and dialog.table.item(0,2).text()=='47n'
    dialog.select('all');assert dialog.selected_refs()==['C25','RNEW']
    dialog.table.item(2,0).setCheckState(Qt.Checked);assert 'C17' in dialog.selected_refs()
    dialog.close()


def test_cancelled_import_does_not_start_or_overwrite_invalid_json(tab,tmp_path):
    from PySide6.QtTest import QSignalSpy
    job=KiCadJob(tmp_path/'cancelled.kicad_sch',tab);progress=QSignalSpy(job.progress)
    job.cancel();job.start();assert job.proc is None and progress.count()==0
    tab.editor.setPlainText('{ unfinished')
    tab.schematic.import_ready(dict(components=[]),{})
    assert tab.editor.toPlainText()=='{ unfinished' and 'Fix the model' in tab.schematic.note.text()


def test_kicad_process_import_and_cancellation(tab,tmp_path,monkeypatch):
    from pathlib import Path
    from PySide6.QtCore import QProcess,QTimer
    from PySide6.QtTest import QSignalSpy
    from kicad2ems_gui import schematicview
    source=tmp_path/'original.kicad_sch';source.write_text('original untouched')
    cli=tmp_path/'fake-kicad-cli';cli.write_text(f'#!{sys.executable}\n'+'''import sys,time
from pathlib import Path
target=Path(sys.argv[sys.argv.index('--output')+1])
if 'netlist' in sys.argv:
    target.write_text('<export><components/><nets/></export>')
else:
    (target/'sheet.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><circle cx="20" cy="20" r="10"/></svg>')
''');cli.chmod(0o755);monkeypatch.setattr(schematicview.shutil,'which',lambda _:str(cli))
    job=KiCadJob(source,tab);done=QSignalSpy(job.completed);failed=QSignalSpy(job.failed);job.start()
    assert done.wait(5000) and failed.count()==0
    document,sheets=done.at(0);assert document['path']==str(source) and list(sheets)==['sheet.svg']
    assert not Path(job.temp.name).exists() and source.read_text()=='original untouched'
    tab.schematic.set_sheets(sheets);assert len(tab.schematic.source_scene.items())==1
    tab.set_model(tab.values()) # unchanged source keeps loaded sheets
    assert tab.schematic._sheets==sheets
    cfg=tab.values();cfg['schematic']={'source':document};tab.set_model(cfg)
    assert tab.schematic._sheets=={}
    tab.schematic.set_sheets(sheets)
    assert tab.schematic.commit(lambda c:c.pop('schematic')) and tab.schematic._sheets=={}
    tab.schematic.undo();assert tab.schematic.config['schematic']['source']==document and tab.schematic._sheets=={}
    cli.write_text(f'#!{sys.executable}\nimport time\ntime.sleep(30)\n')
    job=KiCadJob(source,tab);done=QSignalSpy(job.completed);job.start();proc=job.proc
    QTimer.singleShot(50,job.cancel);stopped=QSignalSpy(proc.finished)
    assert stopped.wait(5000) and proc.state()==QProcess.NotRunning and done.count()==0
    assert not Path(job.temp.name).exists() and source.read_text()=='original untouched'


def test_rotating_a_part(tab):
    """R (or the menu, or Rotate) turns the selected part from how it stands: its pins and wires follow, the angle
    stays with the model, Undo turns it back, Arrange leaves every part to the generator again."""
    view=tab.schematic;sc=view.scene;view.select('part:L3')
    start=sc.devices['part:L3'].rot
    assert start in (0,180) and not sc.devices['part:L3'].chosen     # the generator's: along the flow, either way
    view.rotate_part('part:L3',90)
    item=sc.devices['part:L3']                                       # rebuilt
    assert item.rot==(start+90)%360 and item.chosen and item.facing(0)[0]==0 and item.facing(1)==tuple(-v for v in item.facing(0))
    assert abs(item.pin(0).x()-item.pos().x())<1e-6
    assert tab.values()['schematic']['rotations']=={'part:L3':(start+90)%360}
    assert sc.devices['part:L3'].isSelected()
    for net,wire,(a,i),(b,j),label in sc.links:                       # every wire starts and ends on its pins
        path=wire.path();assert path.elementCount()>=4
        ends={(round(path.elementAt(0).x),round(path.elementAt(0).y)),(round(path.elementAt(path.elementCount()-1).x),round(path.elementAt(path.elementCount()-1).y))}
        assert ends=={(round(a.pin(i).x()),round(a.pin(i).y())),(round(b.pin(j).x()),round(b.pin(j).y()))}
    view.undo();assert sc.devices['part:L3'].rot==start and 'rotations' not in tab.values().get('schematic',{})
    view.rotate_part('part:L3',180);assert sc.devices['part:L3'].rot==(start+180)%360
    view.rotate_part('part:L3',0);assert not sc.devices['part:L3'].chosen and 'rotations' not in tab.values()['schematic']
    view.rotate_part('switch:Q2',270);view.arrange()
    assert not any(d.chosen for d in sc.devices.values()) and 'rotations' not in tab.values()['schematic']
    tab.set_model(dict(tab.values(),schematic=dict(format=1,rotations={'part:C25':90})))
    assert sc.devices['part:C25'].rot==90 and sc.devices['part:C25'].chosen     # a saved model's angle, when loaded


def test_generated_orientation(tab):
    """The generator: coils stand up, a part faces the parts it connects to (no wire round its own card), and
    ground is drawn downward whichever way its pin points."""
    view=tab.schematic;sc=view.scene
    assert sc.devices['primary'].rot in (90,270) and sc.devices['secondary'].rot in (90,270)
    assert sc.devices['load'].rot in (90,270)                         # the load too, across the output
    assert sc.devices['part:R9'].rot in (0,180)
    # a part put to the left of the only part it is wired to turns its wired pin to the right
    pos=sc.positions();sup=sc.devices['supply'];k=sup.record['nets'].index('VIN')
    other=next(d for key,d in sc.devices.items() if key!='supply' and 'VIN' in d.record['nets'])
    ox,oy=other.x(),other.y()                                         # (the parts are rebuilt at every edit)
    pos['supply']=[ox-400,oy];view.save_positions(pos)
    assert sc.devices['supply'].facing(k)==(1,0)
    pos['supply']=[ox+400,oy];view.save_positions(pos)
    assert sc.devices['supply'].facing(k)==(-1,0)


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def general(name):
    from pcbqs.circuit import model as M
    from kicad2ems_gui.schematicview import SchematicEditor
    ed=SchematicEditor();ed.set_model(M.template(name));return ed,M


def test_general_model_columns_follow_the_power_path(qapp):
    """A general model's parts are placed by where they sit between the source and the load, whatever they are
    called: a part to ground stands up in its net's column, a part between two nets lies between them."""
    from kicad2ems_gui.schematicview import records
    ed,M=general('boost')
    by={r['ref']:r for r in records(ed.config)}
    assert [by[r]['group'] for r in ('V1','C1','L1','Q1','D1','C2','R1')]==['c00','c01','c02','c03','c04','c05','c06']
    assert [by[r]['stand'] for r in ('V1','C1','L1','Q1','D1','C2','R1')]==[True,True,False,True,False,True,True]
    assert [by[r]['kind'] for r in ('V1','L1','Q1','D1','R1')]==['supply','inductor','switch','diode','load']
    assert by['L1']['label']=='47 µH' and by['R1']['label']=='48 Ω' and by['Q1']['label']=='pwm' and by['V1']['glyph']=='+'
    m=M.template('boost')                                           # the same circuit under other names: the same columns
    names={p['ref']:f"X{i}" for i,p in enumerate(m['parts'])};nets={'in':'n1','sw':'n2','out':'n3'}
    for p in m['parts']:p['ref']=names[p['ref']];p['nodes']=[nets.get(n,n) for n in p['nodes']]
    m['probes']={};m['measures']={};m['targets']=[]
    assert [r['group'] for r in records(m)]==[by[r]['group'] for r in names]
    ed,M=general('flyback')
    by={r['ref']:r for r in records(ed.config)}
    assert by['LP']['kind']==by['LS']['kind']=='coil' and by['LP']['coupled']==[('part:LS','k=0.98')]
    assert by['LS']['group']>by['Q1']['group']>by['LP']['group'] and by['R1']['group']==max(r['group'] for r in by.values())
    assert len(ed.scene.couplings)==1
    ed,M=general('bridge_rectifier')
    assert next(r for r in records(ed.config) if r['ref']=='V1')['glyph']=='~'


def test_no_wire_of_any_example_passes_through_a_part(qapp):
    from PySide6.QtCore import QPointF
    from pcbqs.circuit import model as M
    for name in M.templates():
        ed,_=general(name);sc=ed.scene
        cards=[it.card().translated(it.pos()) for it in sc.devices.values()]
        for net,wire,*_ in sc.links:
            path=wire.path();pts=[QPointF(path.elementAt(k).x,path.elementAt(k).y) for k in range(path.elementCount())]
            assert len(pts)>=2 and not sc.crosses(pts,cards),(name,net)
            assert all(abs(u.x()-v.x())<.01 or abs(u.y()-v.y())<.01 for u,v in zip(pts,pts[1:])),(name,net)   # square corners


def test_general_model_parts_are_edited_added_and_removed(qapp):
    ed,M=general('buck')
    ed.select('part:L1')
    assert set(ed.fields)=={'value','DCR_ohm','SRF_Hz','Cp_F','core_R_ohm'} and ed.fields['value'].text()=='22u'
    ed.fields['value'].setText('33u');ed.fields['DCR_ohm'].setText('');ed.ends['b'].setCurrentText('sw')
    assert not ed.apply_selected() and "both nodes are 'sw'" in ed.note.text()      # said, and not applied
    ed.ends['b'].setCurrentText('out');assert ed.apply_selected()
    l1=next(p for p in ed.config['parts'] if p['ref']=='L1')
    assert l1['value']=='33u' and 'DCR_ohm' not in l1
    ed.select('part:Q1')
    assert ed.drive.currentText()=='pwm' and ed.fields['model.Ron_ohm'].text()=='30m'
    ed.fields['model.Cds_F'].setText('300p');ed.invert.setChecked(True);assert ed.apply_selected()
    q1=next(p for p in ed.config['parts'] if p['ref']=='Q1')
    assert q1['model']['Cds_F']=='300p' and q1['invert'] is True and q1['model']['type']=='switch'
    ed.select('part:R1');ed.fields['resistance_ohm'].setText('vout/(2*iout)');assert ed.apply_selected()
    assert ed.scene.devices['part:R1'].record['label']=='1.25 Ω'    # the number behind the expression
    ed.fields['resistance_ohm'].setText('vout/ix');assert not ed.apply_selected() and "unknown name 'ix'" in ed.note.text()
    n=len(ed.config['parts'])
    ed.insert_part('capacitor','C9','100n','out','0');ed.insert_part('switch','Q9','0.01','sw','0')
    assert len(ed.config['parts'])==n+2 and next(p for p in ed.config['parts'] if p['ref']=='Q9')['drive']=='pwm'
    ed.insert_part('capacitor','C9','1u','out','0');assert 'used twice' in ed.note.text() and len(ed.config['parts'])==n+2
    ed.select('part:C9');ed.remove_part();ed.undo()
    assert any(p['ref']=='C9' for p in ed.config['parts'])
    ed,M=general('flyback');ed.select('part:LS');ed.remove_part()
    assert ed.config['couplings']==[] and not ed.scene.couplings
    ed.import_file();assert 'board-terminal model' in ed.note.text()
