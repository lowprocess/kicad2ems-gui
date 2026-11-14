"""The Circuit page: the model's editor, with its settings a panel made from the circuit plugin's options
(pcbqs.circuit's own table), the model's own values under them, and a run that is the plugin's command on the model
as edited. pcbqs's own plugin: skipped without pcbqs."""
import json
import pytest
from kicad2ems_gui.powercircuittab import PowerCircuitTab

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


def test_a_general_model_s_parameters_and_sweep(tab):
    """A model (the page opens on pcbqs.circuit's boost converter): its tool's options, and in Model its parameters
    and its sweep, which are the model's. The full-bridge tool's model (format 1) is no longer one."""
    assert tab.shown()==['copper','fields','set','jobs','parameters','sweep']
    assert not tab.panel.sections['Model'].isHidden() and 'Operating points' not in tab.panel.sections
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
    with pytest.raises(ValueError,match='wpthb_bridge'):tab.set_model(dict(format=1,components=[]))


def test_a_run_is_the_plugin_s_command_on_the_model_as_edited(tab,tmp_path,monkeypatch):
    """Run: the model as edited written into the run's folder, pcbqs.circuit with the options set; the board's
    copper needs a board (the model's own, the one named, else said)."""
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
    bridge=tmp_path/'bridge.json';bridge.write_text(json.dumps(dict(format=1,components=[])))    # the old tool's model
    assert not tab.load_model(str(bridge)) and 'wpthb_bridge' in tab.status.text() and tab.model_path is None

    class Win:                                                      # the window's part: the study's output folder
        def tool_out(self,kind,board,name,preview=False):return str(tmp_path/'out'/f'{kind}_{name}')
    tab.panel.win=Win();tab.model_path=str(tmp_path/'m.json')
    assert tab.panel.default_out(None,tab.run_tag())==str(tmp_path/'out'/'circuit_m')
    run=tmp_path/'run';run.mkdir();(run/'circuit.json').write_text(json.dumps(dict(format=2,name='Ran',cases=[],failed=[],complete=True)))
    assert tab.open_run(str(run)) and tab.out==str(run) and not tab.open_run(str(tmp_path))
    old=tmp_path/'bridge-run';old.mkdir();(old/'power-circuit.json').write_text(json.dumps(dict(format=1,complete=True,cases=[])))
    assert not tab.open_run(str(old)) and tab.out==str(run)         # the old full-bridge tool's run: not a result now


def test_a_study_whose_model_will_not_load_keeps_it(tab,tmp_path):
    """A config that names the old full-bridge tool's model (format 1, under the window's own <config>_circuit.json):
    refused, the page starts from its template, and saving the study leaves that file as it was and the config naming
    it. Opened after another study, nothing of that one's is written into it. Started anew, the study's model goes
    in a file of its own, the old one kept."""
    other=tmp_path/'a_circuit.json';tab.write_model(str(other),tab.values());tab.load_settings(dict(model=str(other)))
    assert tab.model_path==str(other)
    old=tmp_path/'s_circuit.json';old.write_text(json.dumps(dict(format=1,components=[dict(ref='Q1')])));before=old.read_text()
    kept=other.read_text()
    tab.load_settings(dict(model=str(old)))
    assert tab.model_path is None and tab.refused==str(old) and 'left as it is' in tab.status.text()
    assert tab.values()['name'].startswith('Boost converter')
    assert tab.save_settings(str(tmp_path/'s.toml'))['model']=='s_circuit.json'
    assert old.read_text()==before and other.read_text()==kept
    tab.new_model('boost')                                          # started anew: its own file, the old one kept
    class Study:
        def ticked(self):return ['circuit']
    tab.win=type('Win',(),dict(study=Study()))()                   # (the window's study asks for the circuit)
    assert tab.save_settings(str(tmp_path/'s.toml'))['model']=='s_circuit-2.json' and old.read_text()==before
    tab.win=None


def test_a_proposal_with_no_model_sets_the_one_on_the_page(tab,tmp_path):
    """kicad2ems-fem's coils (Set lines, no model): the page's model stays, with its file, and takes the settings."""
    mine=tmp_path/'m.json';m=tab.values();m['name']='Mine';mine.write_text(json.dumps(m))
    tab.load_settings(dict(model=str(mine)))
    tab.load_settings(dict(set='C1.value=2.2e-05'),keep_model=True)
    assert tab.values()['name']=='Mine' and tab.model_path==str(mine) and tab.panel.values()['set']=='C1.value=2.2e-05'


def test_a_json_edit_is_a_change_and_an_undo_step(tab):
    """A keystroke in Model JSON marks the study changed (it had not: no save prompt), and once the schematic follows
    it the model before is an undo step (the schematic's history had been wiped by each JSON edit)."""
    edits = []
    tab.panel.changed.connect(lambda: edits.append(1))
    c = json.loads(tab.editor.toPlainText())
    c.setdefault('parameters', {})['extra_param'] = 1.0
    tab.editor.setPlainText(json.dumps(c, indent=2))
    assert edits
    before = len(tab.schematic.undo_stack)
    tab.refresh_schematic()
    assert len(tab.schematic.undo_stack) == before + 1 and tab.schematic.config['parameters']['extra_param'] == 1.0
    tab.schematic.undo()
    assert 'extra_param' not in tab.schematic.config.get('parameters', {})
