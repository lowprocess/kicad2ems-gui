"""MQS page uses CLI schema, reads actual standard outputs, and opens arbitrary field folders."""
import json
import os
import pytest
from kicad2ems_gui import mqstab


def test_argv_preserves_comma_separated_controls():
    desc=dict(options=[dict(key='harmonics',flag='--harmonics',kind='str',default='1'),
                       dict(key='converter',flag='--converter',kind='str',default='')])
    args=mqstab.mqs_argv(dict(converter='U702',harmonics='1,2,3'),'b.json','out',desc,python='py')
    assert args==['py','-m','mom25d.mqs','b.json','--out','out','--converter','U702','--harmonics','1,2,3']


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
