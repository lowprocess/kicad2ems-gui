import json
import pytest
from kicad2ems_gui.powercircuittab import PowerCircuitTab


def test_component_and_operating_overrides():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    tab=PowerCircuitTab();tab.frequencies.setText('90000,110000');tab.powers.setText('5,30');tab.coupling.setText('.4');tab.model.setCurrentText('vdmos')
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
    tab=PowerCircuitTab();t=np.linspace(0,.003,301)
    np.savez(tmp_path/'transient.npz',time_s=t,**{'PRIMARY.winding_I':np.sin(2*np.pi*1000*t),'SECONDARY.winding_I':np.cos(2*np.pi*1000*t)})
    c=dict(folder=str(tmp_path),frequency_Hz=1000,target_W=5,load_power_W=5,phase_deg=30,primary_rms_A=.707,efficiency=.9)
    tab.show_result(dict(complete=True,cases=[c]))
    assert len(tab.waveform.listDataItems())==2
    assert len(tab.waveform.listDataItems()[0].getData()[0])>100
    tab.overrides['cap_ESR'].setText('12');tab.overrides['dead_time_s'].setText('80')
    vals=tab.values();assert vals['switch_model']['dead_time_s']==80e-9
    assert all(p['ESR_ohm']==.012 for p in vals['components'] if p['type']=='capacitor')
    tab.close()


def test_fixed_receiver_model_roundtrip():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    tab=PowerCircuitTab();c=tab.values();c.update(secondary_C_F=100e-9,load_ohm=6.45)
    tab.set_model(c);assert abs(float(tab.receiver_C.text())-100)<1e-10
    assert tab.values()['secondary_C_F']==pytest.approx(100e-9) and tab.values()['load_ohm']==6.45
    assert 'fixed' in tab.matching_note.text()
    tab.receiver_C.clear();tab.load_R.clear()
    assert 'secondary_C_F' not in tab.values() and 'load_ohm' not in tab.values()
    tab.close()
