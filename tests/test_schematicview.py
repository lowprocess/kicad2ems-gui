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
