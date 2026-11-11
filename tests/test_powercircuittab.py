import json
import pytest
from kicad2ems_gui.powercircuittab import PowerCircuitTab


def test_component_and_operating_overrides():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    tab=PowerCircuitTab();tab.new_model('wpthb');tab.frequencies.setText('90000,110000');tab.powers.setText('5,30');tab.coupling.setText('.4');tab.model.setCurrentText('vdmos')
    c=json.loads(tab.editor.toPlainText());next(p for p in c['components'] if p['ref']=='L3')['DCR_ohm']=.075
    next(p for p in c['components'] if p['ref']=='C19').update(type='resistor',value=100)
    tab.editor.setPlainText(json.dumps(c));v=tab.values()
    assert v['frequencies_Hz']==[90000,110000] and v['powers_W']==[5,30]
    assert v['switch_model']['type']=='vdmos'
    assert next(p for p in v['components'] if p['ref']=='L3')['DCR_ohm']==.075
    assert next(p for p in v['components'] if p['ref']=='C19')['type']=='resistor'
    tab.fields.setChecked(True);assert tab.copper.isChecked()
    tab.copper.setChecked(False);assert not tab.fields.isChecked()
    tab.close()


def test_saved_case_waveforms_are_visible(tmp_path):
    import numpy as np
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    tab=PowerCircuitTab();tab.new_model('wpthb');t=np.linspace(0,.003,301)
    np.savez(tmp_path/'transient.npz',time_s=t,**{'PRIMARY.winding_I':np.sin(2*np.pi*1000*t),'SECONDARY.winding_I':np.cos(2*np.pi*1000*t)})
    c=dict(folder=str(tmp_path),frequency_Hz=1000,target_W=5,load_power_W=5,phase_deg=30,primary_rms_A=.707,efficiency=.9)
    tab.show_result(dict(complete=True,cases=[c]))
    assert len(tab.waveform.listDataItems())==2
    assert 'Input W' in tab.summary.toHtml() and 'VHB ripple' in tab.summary.toHtml()
    tab.signal_view.setCurrentIndex(2)                      # input filter currents: none saved in this case
    assert len(tab.waveform.listDataItems())==0 and 'none of' in tab.status.text()
    tab.signal_view.setCurrentIndex(0)
    c2=dict(c,input_power_W=5.4,bus_ripple_V=3.88,runtime_s=56.0);tab.show_result(dict(complete=True,cases=[c2]))
    assert '5.400' in tab.summary.toHtml() and '3.88' in tab.summary.toHtml()
    assert len(tab.waveform.listDataItems()[0].getData()[0])>100
    tab.overrides['cap_ESR'].setText('12');tab.overrides['dead_time_s'].setText('80')
    vals=tab.values();assert vals['switch_model']['dead_time_s']==80e-9
    assert all(p['ESR_ohm']==.012 for p in vals['components'] if p['type']=='capacitor')
    tab.close()


def test_fixed_receiver_model_roundtrip():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    tab=PowerCircuitTab();tab.new_model('wpthb');c=tab.values();c.update(secondary_C_F=100e-9,load_ohm=6.45)
    tab.set_model(c);assert abs(float(tab.receiver_C.text())-100)<1e-10
    assert tab.values()['secondary_C_F']==pytest.approx(100e-9) and tab.values()['load_ohm']==6.45
    assert 'fixed' in tab.matching_note.text()
    tab.receiver_C.clear();tab.load_R.clear()
    assert 'secondary_C_F' not in tab.values() and 'load_ohm' not in tab.values()
    tab.close()


def test_solver_steps_view(tmp_path):
    """I1: with the run's solver-step signals saved (steps.*), the waveform view can show them instead of the
    uniform samples; without them the box is disabled."""
    import numpy as np
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    tab=PowerCircuitTab();t=np.linspace(0,.003,301);ts=np.sort(np.r_[t,np.linspace(.0025,.003,2001)])
    np.savez(tmp_path/'transient.npz',time_s=t,**{'bus.V':24+0*t,'steps.time_s':ts,'steps.bus.V':24+(ts>.0029)})
    c=dict(folder=str(tmp_path),frequency_Hz=1000,target_W=5,load_power_W=5,phase_deg=30,primary_rms_A=.707,efficiency=.9)
    tab.show_result(dict(complete=True,cases=[c]));tab.signal_view.setCurrentIndex(3)
    uniform=tab.waveform.listDataItems()[0].getData()
    tab.steps_box.setChecked(True)
    stepped=tab.waveform.listDataItems()[0].getData()
    assert tab.steps_box.isEnabled() and len(stepped[0])>len(uniform[0]) and stepped[1].max()==25


def test_opens_on_the_simple_template():
    """A small circuit to start from, not a board's: a boost converter, in the general model; the examples and
    the board's bridge are a choice away, and the settings follow the model's kind."""
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    tab=PowerCircuitTab()
    c=tab.values()
    assert c['format']==2 and c['name'].startswith('Boost converter') and [p['ref'] for p in c['parts']]==['V1','C1','L1','Q1','D1','C2','R1']
    assert tab.start_from.currentData()=='boost' and tab.start_from.count()==11 and tab.start_from.itemData(tab.start_from.count()-1)=='wpthb'
    sc=tab.schematic.scene
    assert set(sc.devices)=={'part:'+r for r in ('V1','C1','L1','Q1','D1','C2','R1')}
    assert tab.form.isRowVisible(tab.params) and not tab.form.isRowVisible(tab.frequencies) and not tab.form.isRowVisible(tab.copper)
    assert 'drives.pwm.duty is adjusted until vout_avg' in tab.matching_note.text()
    tab.new_model('wpthb')
    assert any(p['ref']=='C25' for p in tab.values()['components'])
    assert not tab.form.isRowVisible(tab.params) and tab.form.isRowVisible(tab.frequencies) and tab.signal_view.itemText(0)=='Winding currents'
    tab.new_model('flyback')
    assert tab.values()['couplings'][0]['inductors']==['LP','LS'] and tab.signal_view.itemText(0)=='Probes: voltages'
    tab.close()


def test_parameters_and_sweep_of_a_general_model():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    tab=PowerCircuitTab()
    names=[tab.params.item(r,0).text() for r in range(tab.params.rowCount())]
    assert names==['fsw','vin','vout','pout'] and tab.sweep.text()==''
    tab.params.item(names.index('vin'),1).setText('9');tab.params.item(names.index('fsw'),1).setText('250k')
    tab.sweep.setText('R1.resistance_ohm: 48, 96;  parameters.vout: 20, 2*vin')
    v=tab.values()
    assert v['parameters']['vin']==9 and v['parameters']['fsw']=='250k'
    assert v['sweep']=={'R1.resistance_ohm':[48,96],'parameters.vout':[20,'2*vin']}
    tab.refresh_schematic()                                         # the schematic shows the numbers behind them
    assert tab.schematic.scene.devices['part:V1'].record['label']=='9 V'
    tab.sweep.setText('R1.resistance_ohm 48')
    with pytest.raises(ValueError,match='Sweep'):tab.values()
    tab.new_model('buck_synchronous')
    assert tab.sweep.text()=='I1.current_A: 0.5, 2, 4'
    tab.close()


def test_general_results_table_loss_and_waveforms(tmp_path):
    import numpy as np
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    tab=PowerCircuitTab();T=5e-6;t=np.linspace(0,8*T,8*64+1)
    np.savez(tmp_path/'transient.npz',time_s=t,**{'vout':24+0*t,'il':1+.3*np.sin(2*np.pi*t/T),'L1.I':1+0*t,'C2.V':24+0*t,'Q1.V':12+0*t,'D1.V':-12+0*t,'Q1.I':0*t,'D1.I':0*t})
    (tmp_path/'model.json').write_text(json.dumps(tab.values()))
    parts=dict(V1=dict(type='source',power_W=-12.3),L1=dict(type='inductor',power_W=.055,avg_A=1.03,rms_A=1.05,peak_A=1.35,ripple_A=.65),
               Q1=dict(type='switch',power_W=.02,avg_A=.53,rms_A=.75,peak_A=4.5,peak_V=24.4),D1=dict(type='diode',power_W=.23,avg_A=.5,rms_A=.73,peak_A=3.8,peak_V=24),
               C2=dict(type='capacitor',power_W=.002,avg_V=24,ripple_V=.065,rms_A=.53),R1=dict(type='load',power_W=11.99,avg_V=24,avg_A=.5))
    case=dict(name='run',folder=str(tmp_path),period_s=T,sweep={},knobs={'drives.pwm.duty':.5142},measures=dict(vout_avg=23.98,il_ripple=.649),
              source_power_W=12.3,load_power_W=11.99,loss_W=.31,efficiency=.9749,gate_drive_power_W=0.0,parts=parts,coupled=[],
              notes=['Q1: a peak of 5e+05 V is a solver spike'],periodic_error=2e-4,reltol=1e-4,runs=8,periods=3400,runtime_s=25.)
    tab.show_result(dict(format=2,name='Boost',complete=True,cases=[case],failed=[dict(name='vin=3',error='vout_avg cannot reach 24')]))
    text=tab.summary.toPlainText()
    assert 'pwm.duty' in text and '97.49' in text and '0.5142' in text and 'where the 0.31 W goes' in text
    assert text.index('D1')<text.index('L1')<text.index('Q1')        # the loss table: the largest first
    assert 'solver spike' in text and 'vin=3: failed.' in text and 'cannot reach 24' in text
    assert tab.status.text()=='Completed: 1 point failed' and tab.case.count()==1
    assert [i.name() for i in tab.waveform.listDataItems()]==['vout']
    x,y=tab.waveform.listDataItems()[0].getData();assert x[-1]==pytest.approx(10.0) and len(x)==129     # two periods, in µs
    tab.signal_view.setCurrentIndex(1);assert [i.name() for i in tab.waveform.listDataItems()]==['il']
    tab.signal_view.setCurrentIndex(3);assert [i.name() for i in tab.waveform.listDataItems()]==['L1.I']
    tab.signal_view.setCurrentIndex(4);assert [i.name() for i in tab.waveform.listDataItems()]==['Q1.V','D1.V']
    tab.close()
