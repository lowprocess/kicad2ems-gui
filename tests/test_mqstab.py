"""MQS page uses CLI schema, reads actual standard outputs, and opens arbitrary field folders."""
import json
import os
import pytest
from kicad2ems_gui import mqstab


def test_argv_preserves_comma_separated_controls():
    desc=dict(options=[dict(key='harmonics',flag='--harmonics',kind='str',default='1'),
                       dict(key='converter',flag='--converter',kind='str',default='')])
    args=mqstab.mqs_argv(dict(converter='U702',harmonics='1,2,3'),'b.json','out',desc,python='py')
    assert args==['py','-m','pcbqs.mqs','b.json','--out','out','--converter','U702','--harmonics','1,2,3']


def test_page_roundtrip_and_open(tmp_path,monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(mqstab,'describe',lambda:dict(format=1,options=[]))
    opened=[]
    class Window:
        def open_results(self,path):opened.append(path)
    page=mqstab.MqsTab(Window())
    res=dict(format=1,selection=dict(converter='U<1',vin='VIN',ground='GND',capacitors=['C1']),triangles=12,
             frequencies_Hz=[1e6],harmonic_peak_A=[1],copper_R_ohm=[.01],copper_L_H=[1e-9],peak_H_Am=[[.1,.05]],
             notes=['assumed <pulse>'],figures=[])
    (tmp_path/'mqs.json').write_text(json.dumps(res))
    page.show_result(mqstab.load_result(tmp_path))
    assert 'U<1' in page.summary.toPlainText()
    assert '&lt;pulse&gt;' in mqstab.summary_html(res)
    assert len(page.spectrum.listDataItems())==1
    page.open_fields();assert opened==[str(tmp_path)]


def test_preview_argv_and_power_integrity_handoff(monkeypatch,tmp_path):
    from PySide6.QtWidgets import QApplication, QLineEdit, QLabel
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(mqstab,'describe',lambda:dict(format=1,features=['preview'],options=[]))
    class Pdn:
        desc=dict(options=[dict(key='source',default=''),dict(key='load',default=[])])
        board=QLineEdit();status=QLabel()
        def set_values(self,vals):self.vals=vals
    class Win:
        pdn=Pdn()
        def show_panel(self,name):self.shown=name
    win=Win();page=mqstab.MqsTab(win)
    assert page.preview_btn.isEnabled()
    assert mqstab.mqs_argv({},'board','out',{},preview=True)[-1]=='--preview'
    page.result=dict(selection=dict(converter='U1',vin='VIN',ground='GND'),source_path='board.kicad_pcb',settings=dict(vin_volts=12))
    page.open_pdn()
    assert win.shown=='PDN' and win.pdn.board.text()=='board.kicad_pcb'
    assert win.pdn.vals['volts']==12 and win.pdn.vals['rail']=='VIN'
    assert win.pdn.vals['source']=='' and win.pdn.vals['load']==''
    assert 'DC loads' in win.pdn.status.text()


def test_preview_result_opens_mesh_without_field_dumps(tmp_path,monkeypatch):
    import numpy as np
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(mqstab,'describe',lambda:dict(format=1,features=['preview'],options=[]))
    ring=[[0,0],[2,0],[2,1],[0,1],[0,0]]
    board=dict(outline=dict(type='Polygon',coordinates=[ring]),stack=dict(copper=[dict(name='F',z=0,t=.035)],thickness=0),
               copper={'F':[dict(net='VIN',polygon=dict(type='Polygon',coordinates=[ring]),active=True)]},
               vias=[],ports=[],parts=[],active_nets=['VIN'],components=[])
    (tmp_path/'mqs_board.json').write_text(json.dumps(board))
    np.savez(tmp_path/'mqs_mesh_mqs.npz',kind='tris',nodes=[[0,0,0],[2,0,0],[0,1,0]],tris=[[0,1,2]])
    res=dict(format=1,preview=True,selection=dict(converter='U1',vin='VIN',ground='GND',capacitors=['C1']),
             triangles=1,layers={'F':dict(triangles=1,max_edge_mm=2.24,min_angle_deg=26.5)})
    (tmp_path/'mqs-preview.json').write_text(json.dumps(res))
    page=mqstab.MqsTab();page.out=str(tmp_path);page._preview=True;page._finished(0)
    assert page.layout.board and page.layout.mesh.currentData()=='mqs'
    assert page.tabs.currentWidget() is page.layout and page.maps.src is None
    assert 'No matrix fill or solve' in page.summary.toPlainText()


def test_converter_choices_offer_each_input_net():
    """I5: an ambiguous input net is offered as a choice per converter and net, filling converter, vin and caps."""
    found=[dict(converter='U5',inductor='L2',switch='SW5',inputs=[dict(vin='VCC',capacitors=['C1','C2']),
                                                                  dict(vin='VDRV',capacitors=['C9'])])]
    choices=mqstab.converter_choices(found)
    assert [v for _,v in choices]==[dict(converter='U5',vin='VCC',capacitors='C1,C2'),
                                    dict(converter='U5',vin='VDRV',capacitors='C9')]
    assert 'U5: VCC' in choices[0][0] and '1 capacitor:' in choices[1][0]


def test_find_converters_fills_the_form(monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(mqstab,'describe',lambda:dict(format=1,options=[
        dict(key=k,flag='--'+k,kind='str',default='',group='Converter',help=k) for k in ('converter','vin','capacitors')]))
    page=mqstab.MqsTab(None)
    page.pick_converter(mqstab.converter_choices([dict(converter='U7',inductor='L1',switch='SW',
                                                        inputs=[dict(vin='+5V',capacitors=['C3'])])]))
    v=page.values()
    assert (v['converter'],v['vin'],v['capacitors'])==('U7','+5V','C3')
