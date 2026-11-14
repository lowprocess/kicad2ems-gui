"""Visual edits must reach the simulation model without losing JSON or topology."""
import json,sys
import pytest
from PySide6.QtWidgets import QApplication
from kicad2ems_gui.powercircuittab import PowerCircuitTab
from kicad2ems_gui.schematicview import ImportReview,KiCadJob


def wpthb():
    import pcbqs
    from pathlib import Path
    return json.loads((Path(pcbqs.__file__).parent/'data'/'wpthb_bridge.json').read_text())


@pytest.fixture
def tab():
    A=pytest.importorskip('pcbqs.analyses',reason='pcbqs is not installed')
    app=QApplication.instance() or QApplication([]);widget=PowerCircuitTab(plugin=A.Circuit());widget.set_model(wpthb());yield widget;widget.close();app.processEvents()


def part(c,ref):
    return next(p for p in c['parts'] if p['ref']==ref)


def test_component_edit_and_undo_redo_reach_json_and_run_values(tab):
    view=tab.schematic;view.select('part:C25');view.fields['value'].setText('47n');view.fields['ESR_ohm'].setText('12m')
    assert view.apply_part()
    c=tab.values();assert part(c,'C25')['value']=='47n' and part(c,'C25')['ESR_ohm']=='12m'      # as written: SI notation
    assert part(json.loads(tab.editor.toPlainText()),'C25')['value']==part(c,'C25')['value']
    view.undo();assert part(tab.values(),'C25')['value']==33e-9
    view.redo();assert part(tab.values(),'C25')['value']=='47n'


def test_nodes_a_switch_and_the_receiver_are_edited_as_any_part(tab):
    view=tab.schematic;view.select('part:L3');view.ends['a'].setCurrentText('CUSTOM');view.fields['DCR_ohm'].setText('75m');assert view.apply_part()
    assert part(tab.values(),'L3')['nodes'][0]=='CUSTOM' and part(tab.values(),'L3')['DCR_ohm']=='75m'
    view.select('part:Q1');view.choice.setCurrentText('switch');view.fields['model.Ron_ohm'].setText('15m');assert view.apply_part()
    assert part(tab.values(),'Q1')['model']['Ron_ohm']=='15m' and part(tab.values(),'Q1')['model']['type']=='switch'
    view.select('part:CSECONDARY');view.fields['value'].setText('100n');assert view.apply_part()
    assert part(tab.values(),'CSECONDARY')['value']=='100n'


def test_invalid_json_is_not_overwritten_by_diagram_edit(tab):
    view=tab.schematic;view.select('part:C25');view.fields['value'].setText('47n');tab.editor.setPlainText('{ incomplete')
    assert not view.apply_part();assert tab.editor.toPlainText()=='{ incomplete'
    assert part(view.config,'C25')['value']==33e-9


def test_layout_round_trip_and_noop_precision(tab):
    original=tab.values();tab.schematic.select('part:PRIMARY');assert tab.schematic.apply_part()
    assert part(tab.values(),'PRIMARY')==part(original,'PRIMARY')
    tab.schematic.save_positions({'part:C25':[123.5,456]})
    c=tab.values();assert c['schematic']['positions']['part:C25']==[123.5,456]
    tab.set_model(json.loads(json.dumps(c)));assert tab.schematic.scene.devices['part:C25'].pos().x()==123.5


def test_render_and_selection_are_functional(tab):
    tab.resize(1500,1000);tab.show();QApplication.processEvents();tab.schematic.scene.focus('part:Q2');QApplication.processEvents()
    assert tab.schematic.selected_key=='part:Q2'
    assert not tab.grab().isNull()
    tab.schematic.find.setText('VHB');tab.schematic.find_ref();assert 'VHB' in tab.schematic.note.text()


def test_import_review_ticks_what_it_takes_over_and_not_the_unfitted(tab):
    from PySide6.QtCore import Qt
    doc=dict(components=[dict(ref='C25',value='47n',kind='capacitor',supported_passive=True,dnp=False,exclude_from_sim=False,sheet='/',fields={},properties={},footprint='',lib_id='Device:C',value_si=47e-9,pins=[dict(number='1',name='',net='VHB'),dict(number='2',name='',net='GND')]),
                         dict(ref='RNEW',value='1k',kind='resistor',supported_passive=True,dnp=False,exclude_from_sim=False,sheet='/',fields={},properties={},footprint='',lib_id='Device:R',value_si=1e3,pins=[dict(number='1',name='',net='VHB'),dict(number='2',name='',net='GND')]),
                         dict(ref='C17',value='33n',kind='capacitor',supported_passive=True,dnp=True,exclude_from_sim=False,sheet='/',fields={},properties={},footprint='',lib_id='Device:C',value_si=33e-9,pins=[dict(number='1',name='',net='VHB'),dict(number='2',name='',net='GND')])])
    # (the window's own has the tab as parent; a top-level one left to the interpreter's exit crashed it on Qt 6.12,
    # after every test had passed: exit 139 on Linux, 127 on Windows)
    dialog=ImportReview(doc,tab.values(),tab)
    assert dialog.selected_refs()==['C25','RNEW']                   # (pcbqs.circuit.kicad.status: a new part ticked,
                                                                    # one not fitted not)
    assert '33' in dialog.table.item(0,3).text() and dialog.table.item(0,2).text()=='47n'
    dialog.select('existing');assert dialog.selected_refs()==['C25']
    dialog.select('all');assert dialog.selected_refs()==['C25','RNEW']                   # (C17: not fitted)
    dialog.select('none');assert dialog.selected_refs()==[]
    dialog.close();dialog.deleteLater();QApplication.processEvents()


def test_cancelled_import_does_not_start_or_overwrite_invalid_json(tab,tmp_path):
    from PySide6.QtTest import QSignalSpy
    job=KiCadJob(tmp_path/'cancelled.kicad_sch',tab);progress=QSignalSpy(job.progress)
    job.cancel();job.start();assert job.proc is None and progress.count()==0
    tab.editor.setPlainText('{ unfinished')
    tab.schematic.import_ready(dict(components=[]),{})
    assert tab.editor.toPlainText()=='{ unfinished' and 'Fix the model' in tab.schematic.note.text()


@pytest.mark.skipif(sys.platform=='win32',reason='its stand-in for kicad-cli is a #! script, which Windows does not run')
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
    assert not sc.devices['part:L3'].chosen                           # the generator's
    view.rotate_part('part:L3',90)
    item=sc.devices['part:L3']                                       # rebuilt
    assert item.rot==(start+90)%360 and item.chosen and item.facing(1)==tuple(-v for v in item.facing(0))
    assert tab.values()['schematic']['rotations']=={'part:L3':(start+90)%360}
    assert sc.devices['part:L3'].isSelected()
    for net,wire,(a,i),(b,j),label in sc.links:                       # every wire starts and ends on its pins
        path=wire.path();assert path.elementCount()>=4
        ends={(round(path.elementAt(0).x),round(path.elementAt(0).y)),(round(path.elementAt(path.elementCount()-1).x),round(path.elementAt(path.elementCount()-1).y))}
        assert ends=={(round(a.pin(i).x()),round(a.pin(i).y())),(round(b.pin(j).x()),round(b.pin(j).y()))}
    view.undo();assert sc.devices['part:L3'].rot==start and 'rotations' not in tab.values().get('schematic',{})
    view.rotate_part('part:L3',180);assert sc.devices['part:L3'].rot==(start+180)%360
    view.rotate_part('part:L3',0);assert not sc.devices['part:L3'].chosen and 'rotations' not in tab.values()['schematic']
    view.rotate_part('part:Q2',270);view.arrange()
    assert not any(d.chosen for d in sc.devices.values()) and 'rotations' not in tab.values()['schematic']
    tab.set_model(dict(tab.values(),schematic=dict(format=1,rotations={'part:C25':90})))
    assert sc.devices['part:C25'].rot==90 and sc.devices['part:C25'].chosen     # a saved model's angle, when loaded


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
    assert not ed.apply_part() and "both nodes are 'sw'" in ed.note.text()      # said, and not applied
    ed.ends['b'].setCurrentText('out');assert ed.apply_part()
    l1=next(p for p in ed.config['parts'] if p['ref']=='L1')
    assert l1['value']=='33u' and 'DCR_ohm' not in l1
    ed.select('part:Q1')
    assert ed.drive.currentText()=='pwm' and ed.fields['model.Ron_ohm'].text()=='30m'
    ed.fields['model.Cds_F'].setText('300p');ed.invert.setChecked(True);assert ed.apply_part()
    q1=next(p for p in ed.config['parts'] if p['ref']=='Q1')
    assert q1['model']['Cds_F']=='300p' and q1['invert'] is True and q1['model']['type']=='switch'
    ed.select('part:R1');ed.fields['resistance_ohm'].setText('vout/(2*iout)');assert ed.apply_part()
    assert ed.scene.devices['part:R1'].record['label']=='1.25 Ω'    # the number behind the expression
    ed.fields['resistance_ohm'].setText('vout/ix');assert not ed.apply_part() and "unknown name 'ix'" in ed.note.text()
    n=len(ed.config['parts'])
    ed.insert_part('capacitor','C9','100n','out','0');ed.insert_part('switch','Q9','0.01','sw','0')
    assert len(ed.config['parts'])==n+2 and next(p for p in ed.config['parts'] if p['ref']=='Q9')['drive']=='pwm'
    ed.insert_part('capacitor','C9','1u','out','0');assert 'used twice' in ed.note.text() and len(ed.config['parts'])==n+2
    ed.select('part:C9');ed.remove_part();ed.undo()
    assert any(p['ref']=='C9' for p in ed.config['parts'])
    ed,M=general('flyback');ed.select('part:LS');ed.remove_part()
    assert ed.config['couplings']==[] and not ed.scene.couplings


def test_a_board_is_imported_into_a_general_model(qapp):
    """Import KiCad… with a .kicad_pcb: the footprints with their values and their pads' nets, reviewed, then the
    model's parts; the board becomes the model's."""
    pytest.importorskip('kicad2ems')
    from kicad2ems_gui.schematicview import ImportReview
    ed,M=general('buck')
    board=ed.config['board']['file']
    model=M.template('buck');model['parts']=[p for p in model['parts'] if p['ref']!='D1']
    next(p for p in model['parts'] if p['ref']=='C2')['value']='10u'
    model.pop('board');ed.set_model(model)
    assert 'part:D1' not in ed.scene.devices
    asked=[]
    def review(document,current):
        dialog=ImportReview(document,current,ed);asked.append(dialog)
        rows={dialog.table.item(r,1).text():r for r in range(dialog.table.rowCount())}
        assert dialog.table.item(rows['D1'],7).text()=='New diode' and dialog.table.item(rows['D1'],0).checkState().name=='Checked'
        assert dialog.table.item(rows['C2'],3).text()=='10u' and 'brought up to date' in dialog.table.item(rows['C2'],7).text()
        assert dialog.table.item(rows['J1'],7).text().startswith('Not taken over') and not dialog.eligible[rows['J1']]
        dialog.select('none');assert dialog.selected_refs()==[]
        dialog.select('existing');assert 'D1' not in dialog.selected_refs() and 'C2' in dialog.selected_refs()
        dialog.select('all');return dialog.selected_refs(),dialog.connections.isChecked()
    ed.review=review
    ed.import_path(board)
    assert len(asked)==1 and 'Imported 5 selected components' in ed.note.text()
    d1=next(p for p in ed.config['parts'] if p['ref']=='D1')
    assert d1['type']=='diode' and d1['nodes']==['GND','sw'] and 'part:D1' in ed.scene.devices
    assert next(p for p in ed.config['parts'] if p['ref']=='C2')['value']==pytest.approx(47e-6)
    assert ed.config['board']['file']==board
    ed.undo();assert 'part:D1' not in ed.scene.devices
