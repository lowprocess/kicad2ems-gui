"""The Circuit page: the model's editor, with its settings a panel made from the circuit plugin's options (the two
tools' own tables: the options of the other kind of model hidden), the model's own values under them, and a run
that is the plugin's command on the model as edited. pcbqs's own plugin: skipped without pcbqs."""
import json
import pytest
from kicad2ems_gui.powercircuittab import PowerCircuitTab, SWITCH_NOTE

A=pytest.importorskip('pcbqs.analyses',reason='pcbqs is not installed')


@pytest.fixture
def tab():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    t=PowerCircuitTab(plugin=A.Circuit())
    yield t
    t.close();app.processEvents()


def test_the_page_is_the_model_s_editor(tab):
    """No result tabs, no log, no case chooser of its own: the schematic and the model's JSON; its settings and
    its Run are the panel's (beside the model when the page is alone)."""
    assert [tab.model_tabs.tabText(i) for i in range(tab.model_tabs.count())]==['Schematic','Model JSON']
    for gone in ('tabs','summary','waveform','signal_view','case','editor_only','steps_box','open_btn'):
        assert not hasattr(tab,gone),gone
    assert tab.settings_panel() is tab.panel and tab.panel.isAncestorOf(tab.params) and tab.status is tab.panel.status
    assert tab.log is tab.panel.log and tab.proc is None and tab.out is None
    assert 'Model' in tab.panel.sections and tab.panel.sections['Model'].expanded


def test_the_bridge_s_operating_points_are_the_model_s(tab):
    """The full bridge: its tool's options, their fields showing the model's values; what is typed goes into the
    model. The switch model is the model's own, and the behavioural one is warned of. Overrides by group are the
    run's, not the model's."""
    tab.new_model('wpthb')
    assert not tab.general and tab.shown()==['copper','fields','field_harmonics','frequencies','powers','coupling','primary_l',
                                             'secondary_l','receiver_c','load','switch_type','override','jobs']
    assert tab.panel.w['primary_l'].text()=='24' and tab.panel.w['secondary_l'].text()=='24'    # the coils', uH
    tab.panel.w['primary_l'].setText('6.45');assert tab.values()['primary']['L_H']==pytest.approx(6.45e-6)
    tab.panel.w['primary_l'].setText('24')
    assert tab.panel.sections['Model'].isHidden() and not tab.panel.sections['Operating points'].isHidden()
    assert tab.frequencies.text()=='90000,110000' and tab.powers.text()=='5,10,20,30' and tab.coupling.text()=='0.4'
    assert tab.receiver_C.text()=='' and tab.model.currentText()=='vdmos'       # the template's, not the first listed
    tab.frequencies.setText('90000');tab.powers.setText('5,30');tab.coupling.setText('.35');tab.receiver_C.setText('100');tab.load_R.setText('2.5')
    c=json.loads(tab.editor.toPlainText());next(p for p in c['components'] if p['ref']=='L3')['DCR_ohm']=.075
    tab.editor.setPlainText(json.dumps(c));v=tab.values()
    assert v['frequencies_Hz']==[90000] and v['powers_W']==[5,30] and v['coupling']==.35
    assert v['secondary_C_F']==pytest.approx(100e-9) and v['load_ohm']==2.5 and v['switch_model']['type']=='vdmos'
    assert next(p for p in v['components'] if p['ref']=='L3')['DCR_ohm']==.075
    tab.receiver_C.clear();assert 'secondary_C_F' not in tab.values()            # none: tuned at each frequency
    tab.model.setCurrentText('switch');assert tab.values()['switch_model']['type']=='switch' and tab.status.text()==SWITCH_NOTE
    tab.model.setCurrentText('mosfet');assert tab.status.text()=='' and tab.values()['switch_model']['type']=='mosfet'
    tab.fields.setChecked(True);assert tab.copper.isChecked()
    tab.copper.setChecked(False);assert not tab.fields.isChecked()
    m=tab.values();m['secondary_C_F']=47e-9;m['load_ohm']=3.0;tab.set_model(m)   # a model with them held: shown
    assert tab.receiver_C.text()=='47' and tab.load_R.text()=='3' and 'fixed 47 nF' in tab.matching_note.text()


def test_a_general_model_s_parameters_and_sweep(tab):
    """A general model (the page opens on pcbqs.circuit's boost converter): its tool's options, and in Model its
    parameters and its sweep, which are the model's."""
    assert tab.general and tab.shown()==['copper','fields','set','jobs','parameters','sweep']
    assert not tab.panel.sections['Model'].isHidden() and tab.panel.sections['Operating points'].isHidden()
    assert tab.panel.forms['Board'].isRowVisible(tab.copper) and not tab.panel.forms['Board'].isRowVisible(tab.panel.w['field_harmonics'])
    c=tab.values()
    assert c['format']==2
    names=[tab.params.item(r,0).text() for r in range(tab.params.rowCount())]
    assert names==list(c['parameters']) and 'adjusted until' in tab.matching_note.text()
    tab.params.item(names.index('vin'),1).setText('9');tab.sweep.setText('parameters.vin: 9, 12;  R1.resistance_ohm: 24, 48')
    v=tab.values()
    assert v['parameters']['vin']==9 and v['sweep']=={'parameters.vin':[9,12],'R1.resistance_ohm':[24,48]}
    tab.sweep.setText('vin 9');
    with pytest.raises(ValueError,match='Sweep: write'):tab.values()
    tab.sweep.clear();assert 'sweep' not in tab.values()
    tab.new_model('wpthb');assert not tab.general and tab.shown()[3]=='frequencies'
    tab.new_model('boost');assert tab.general and tab.frequencies.text()=='90000,110000'      # hidden: not this model's


def test_a_run_is_the_plugin_s_command_on_the_model_as_edited(tab,tmp_path,monkeypatch):
    """Run: the model as edited written into the run's folder, the tool of its kind with the options of its kind;
    the board's copper needs a board (the model's own, the one named, else said)."""
    import kicad2ems_gui.analysispanel as panel
    ran=[]
    monkeypatch.setattr(panel,'run_tool',lambda p,argv,*a,**k:ran.append(argv))
    tab.outdir.setText(str(tmp_path/'out'))
    tab.params.item(0,1).setText('123456');tab.start()
    assert ran[-1][1:5]==['-u','-m','pcbqs.circuit',str(tmp_path/'out'/'model-input.json')] and '--copper' not in ran[-1]
    assert 123456 in json.loads((tmp_path/'out'/'model-input.json').read_text())['parameters'].values()
    assert ran[-1][5:]==['--out',str(tmp_path/'out'),'--jobs','4']
    tab.panel.w['set'].setPlainText('drives.pwm.duty=0.4');tab.fields.setChecked(True);tab.start()
    assert ran[-1][7:]==['--copper','--fields','--set','drives.pwm.duty=0.4','--jobs','4','--board',ran[-1][-1]] and ran[-1][-1].endswith('06_boost.kicad_pcb')
    other=tmp_path/'mine.kicad_pcb';other.write_text('(kicad_pcb)');tab.board.setText(str(other));tab.start()
    assert ran[-1][-1]==str(other)
    tab.board.clear();c=tab.values();c.pop('board');tab.set_model(c);n=len(ran);tab.start()
    assert len(ran)==n and 'Import KiCad' in tab.status.text()      # no board to take the copper from: said, not run
    tab.fields.setChecked(False);tab.copper.setChecked(False)
    tab.new_model('wpthb');tab.frequencies.setText('90000');tab.panel.w['override'].setPlainText('tank.ESR_ohm=0.004\nfilter.DCR_ohm=0.01')
    tab.panel.w['set'].setPlainText('x=1');tab.start()               # the other tool's --set: not this one's
    assert ran[-1][3]=='pcbqs.power_circuit' and ran[-1][7:]==['--override','tank.ESR_ohm=0.004','--override','filter.DCR_ohm=0.01','--jobs','4']
    sent=json.loads((tmp_path/'out'/'model-input.json').read_text())
    assert sent['frequencies_Hz']==[90000] and next(p for p in sent['components'] if p['ref']=='C25')['ESR_ohm']!=.004
    tab.editor.setPlainText('{ not json');n=len(ran);tab.start()
    assert len(ran)==n and tab.status.text().startswith('The model needs attention')


def test_a_study_s_config_holds_the_circuit(tab,tmp_path):
    """[analysis.circuit] of a config: the model it names loaded (its board found beside it), the options it sets;
    saved back: the model written beside the config, its board named relative to it, the options that are set. A
    run alone goes beside where it was started, in the window under the study's output folder."""
    assert tab.save_settings(str(tmp_path/'s.toml'))=={}           # never given a model, not asked: no circuit
    model=tab.values();model['name']='Mine';model['board']=dict(file='b.kicad_pcb')
    (tmp_path/'m.json').write_text(json.dumps(model));(tmp_path/'b.kicad_pcb').write_text('')
    tab.load_settings(dict(model=str(tmp_path/'m.json'),fields=True,out=str(tmp_path/'o'),jobs=2,set=['drives.pwm.duty=0.4']))
    c=tab.values()
    assert c['name']=='Mine' and c['board']['file']==str(tmp_path/'b.kicad_pcb') and tab.model_path==str(tmp_path/'m.json')
    assert tab.copper.isChecked() and tab.fields.isChecked() and tab.outdir.text()==str(tmp_path/'o')
    assert tab.status.text()=='Model: m.json' and tab.run_tag()=='m'
    tab.params.item(0,1).setText('123456')                         # an edit: saved with the study
    assert tab.save_settings(str(tmp_path/'s.toml'))==dict(model='m.json',copper=True,fields=True,out='o',jobs=2,set=['drives.pwm.duty=0.4'])
    saved=json.loads((tmp_path/'m.json').read_text())
    assert saved['board']['file']=='b.kicad_pcb' and 123456 in saved['parameters'].values()
    tab.load_settings({})                                           # a study without a circuit: the page as it opens
    assert tab.model_path is None and tab.values()['name'].startswith('Boost converter') and not tab.copper.isChecked()
    assert tab.panel.values()['set']=='' and tab.run_tag().startswith('Boost')
    assert not tab.load_model(str(tmp_path/'none.json')) and 'none.json' in tab.status.text()
    bridge=tmp_path/'bridge.json';bridge.write_text(json.dumps(PowerCircuitTab.template('wpthb')))
    tab.load_settings(dict(model=str(bridge),override=['tank.ESR_ohm=0.004'],frequencies='1,2'))     # the model's own: not a config's
    assert tab.frequencies.text()=='90000,110000' and tab.panel.values()['override']=='tank.ESR_ohm=0.004'
    tab.powers.setText('7')
    assert tab.save_settings(str(tmp_path/'s.toml'))==dict(model='bridge.json',override=['tank.ESR_ohm=0.004'])
    assert json.loads(bridge.read_text())['powers_W']==[7.0]        # in the model, where it belongs
    tab.load_settings({})
    assert tab.general and tab.model_path is None

    class Win:                                                      # the window's part: the study's output folder
        def tool_out(self,kind,board,name,preview=False):return str(tmp_path/'out'/f'{kind}_{name}')
    tab.panel.win=Win();tab.model_path=str(tmp_path/'m.json')
    assert tab.panel.default_out(None,tab.run_tag())==str(tmp_path/'out'/'circuit_m')
    run=tmp_path/'run';run.mkdir();(run/'circuit.json').write_text(json.dumps(dict(format=2,name='Ran',cases=[],failed=[],complete=True)))
    assert tab.open_run(str(run)) and tab.out==str(run) and not tab.open_run(str(tmp_path))
    old=tmp_path/'bridge-run';old.mkdir();(old/'power-circuit.json').write_text(json.dumps(dict(format=1,complete=True,cases=[])))
    assert tab.open_run(str(old)) and tab.out==str(old)             # the full bridge's run: a circuit result too
