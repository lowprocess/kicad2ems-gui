"""The PDN page's helpers (no Qt): the tool's description, its command line, a result read back and summarised; and
the page in the window (offscreen) showing a run's result."""
import json, os, sys
import pytest
from kicad2ems_gui import pdntab, toolprocess

DESC = dict(format=1, options=[
    dict(key='rail', flag='--rail', kind='str', default='', help='', group='Rail'),
    dict(key='volts', flag='--volts', kind='float', default=3.3, help='', group='Rail'),
    dict(key='load', flag='--load', kind='list', default=[], help='', group='Rail'),
    dict(key='no_pdn', flag='--no-pdn', kind='bool', default=False, help='', group='PDN')])


def test_argv_passes_what_was_set():
    argv = pdntab.pdn_argv(dict(rail='+3V3', volts='3.3', load='U1=2\nU2=0.5, U3=1', no_pdn=True), 'b.kicad_pcb', 'out',
                           DESC, python='py')
    assert argv[:6] == ['py', '-m', 'pcbqs.pdn', 'b.kicad_pcb', '--out', 'out']
    assert argv[6:] == ['--rail', '+3V3', '--load', 'U1=2', '--load', 'U2=0.5', '--load', 'U3=1', '--no-pdn']


def _result():
    return dict(format=1, rail='+3V3', nets=['+3V3', 'OUT'], ground=['GND'], volts=3.3, assumed_loads=True,
                tree=[dict(ref='R1', kind='R', R=0.001, a='+3V3', b='OUT', defaulted=False)], source=['L1'],
                loads={'U1': dict(I=2.0, V=3.28, drop=0.02, power_drop=0.015, ground_rise=0.005)},
                series={'R1': dict(I=2.0, drop=0.002)}, loss_W=0.04, vias=dict(power=[dict(x=1, y=2, I=0.3)], ground=[]),
                vertices=dict(power=100, ground=200), seconds=dict(dc=1.0, total=2.0), notes=['a note'],
                figures=[], pdn=dict(f=[1e4, 1e6, 1e8], target=0.066,
                                     z={'U1': dict(mag=[0.01, 0.005, 0.2], deg=[0, 0, 80], bare=[10, 1, 0.3], over=[[1e8, 1e8]])},
                                     cavities=[dict(rail='In2.Cu', ground='In1.Cu', d=0.2, er=4.3, area=1000, C=1e-9)],
                                     parts={'C1': dict(role='decap', mount_nH=0.6, node=None, rail='1 via(s)', gnd='1 via(s)',
                                                       element=dict(C=1e-7, ESR=0.02, ESL=3.5e-10), defaulted=True)},
                                     vertices=500))


def test_summary_says_what_matters(tmp_path):
    (tmp_path / 'pdn.json').write_text(json.dumps(_result()))
    res = pdntab.load_result(str(tmp_path))
    h = pdntab.summary_html(res)
    assert 'assumed' in h and 'R1' in h and '20.00' in h            # the load's 20 mV drop
    assert 'In2.Cu over In1.Cu' in h and '100 MHz – 100 MHz' in h and 'ESR/ESL by package' in h and 'a note' in h
    assert pdntab.load_result(str(tmp_path / 'none')) is None


def test_page_shows_a_result(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    toolprocess._DESCRIPTIONS[(sys.executable, '-m', 'pcbqs.pdn')] = (DESC, '')
    page = pdntab.PdnTab()
    page.set_values(dict(rail='+3V3', load=['U1=2']))
    assert page.values()['rail'] == '+3V3' and page.values()['load'] == 'U1=2'
    r = _result(); r['_dir'] = str(tmp_path)
    page.show_result(r)
    assert 'U1' in page.summary.toPlainText()
    assert len(page.zplot.listDataItems()) == 3                      # U1, its bare planes, the target


def test_transferred_unknown_supply_requires_explicit_voltage(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(pdntab,'describe',lambda:DESC)
    page=pdntab.PdnTab();page._transferred_unknown_voltage=True
    page.set_values(dict(rail='VCC',volts=''))
    board=tmp_path/'board.json';board.write_text('{}');page.board.setText(str(board))
    page.start()
    assert page.proc is None and 'supply voltage' in page.status.text()


def test_summary_shows_a_series_inductor():
    res = _result()
    res['tree'].append(dict(ref='L3', kind='inductor', R=0.03, L=5.6e-6, a='OUT', b='VHB', defaulted=False))
    h = pdntab.summary_html(res)
    assert 'L (µH)' in h and '>5.6<' in h and 'inductor' in h


def test_list_options_keep_commas_inside_an_item():
    """--cap REF=C,ESR,ESL carries commas: only a comma that starts a new REF= separates two items."""
    desc = dict(options=[dict(key='cap', flag='--cap', kind='list', default=[]),
                         dict(key='load', flag='--load', kind='list', default=[])])
    argv = pdntab.pdn_argv(dict(cap='CA1=47e-6,0.02,1e-9,CA2=1e-6\nC19=47e-6,0.49', load='U1=2, U2=3'), 'b', 'o', desc)
    assert argv[6:] == ['--cap', 'CA1=47e-6,0.02,1e-9', '--cap', 'CA2=1e-6', '--cap', 'C19=47e-6,0.49',
                        '--load', 'U1=2', '--load', 'U2=3']
