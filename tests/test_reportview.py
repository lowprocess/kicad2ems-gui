"""An analysis's report on the Results page (reportview.py): the page to read, its tables to sort, copy and export."""
import os

import pytest

from kicad2ems_gui import reportview as RV

REPORT = dict(
    title='Hottest copper 84.2 °C', summary='Thermal: hottest copper 84.2 °C',
    sections=[dict(title='', text='0.8 W in <all> of it out.'),
              dict(title='Parts', table=dict(columns=['part', 'loss (W)', 'part °C'], formats=[None, '.3g', '.1f'],
                                             rows=[['L1', 0.48, 82.54], ['Q2', 0.2, 80.6], ['C2', 0.000133, 76.8], ['J1', '', '']])),
              dict(title='Layers', table=dict(columns=['layer', 'hottest °C'], rows=[['B.Cu', 74.66], ['F.Cu', 84.2]]),
                   notes=['the top layer']),
              dict(title='Nothing', table=dict(columns=[], rows=[]))],
    notes=['V1: a source, not on the board'], images=[], footer='6,068 unknowns')


def test_cells_tables_and_csv():
    assert RV.cell(0.48, '.3g') == '0.48' and RV.cell(82.54, '.1f') == '82.5' and RV.cell(7, 'd') == '7'
    assert RV.cell(1234.5678) == '1235' and RV.cell('') == '' and RV.cell(None) == '' and RV.cell('L1', '.1f') == 'L1'
    assert RV.cell(True) == 'yes' and RV.cell(7.0, 'd') == '7'
    assert [t for t, _ in RV.tables(REPORT)] == ['Parts', 'Layers'] and RV.tables(None) == []
    assert RV.to_csv(RV.tables(REPORT)[0][1]).splitlines() == ['"part","loss (W)","part °C"', '"L1",0.48,82.5',
                                                               '"Q2",0.2,80.6', '"C2",0.000133,76.8', '"J1",,']


def test_the_page():
    h = RV.to_html(REPORT)
    assert '<h3>Hottest copper 84.2 °C</h3>' in h and '&lt;all&gt;' in h and '<h4>Parts</h4>' in h
    assert '<td align=right>82.5</td>' in h and '<td align=left>L1</td>' in h            # numbers to the right
    assert '<li>the top layer</li>' in h and '<h4>Notes</h4>' in h and 'V1: a source' in h and '6,068 unknowns' in h
    assert RV.to_html(None) == ''
    assert "<img src='/x/a.png'" in RV.to_html(dict(REPORT, images=['/x/a.png']))


def test_the_tables(tmp_path):
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    v = RV.ReportView()
    v.set_report(REPORT)
    assert v.mode() == 'Report' and 'Hottest copper' in v.page.toPlainText() and v.has_tables()
    v.set_mode('Tables')
    assert v.mode() == 'Tables' and [v.which.itemText(i) for i in range(v.which.count())] == ['Parts', 'Layers']
    g = v.grid
    col = lambda c: [g.item(r, c).text() for r in range(g.rowCount())]
    assert col(0) == ['L1', 'Q2', 'C2', 'J1'] and col(1) == ['0.48', '0.2', '0.000133', '']    # as the report has them
    g.sortItems(1, Qt.AscendingOrder)                               # by loss: as numbers, the empty one last
    assert col(0) == ['C2', 'Q2', 'L1', 'J1']
    g.sortItems(0, Qt.AscendingOrder)                               # by part: as text
    assert col(0) == ['C2', 'J1', 'L1', 'Q2']
    assert v._text(selected=False).splitlines()[:2] == ['part\tloss (W)\tpart °C', 'C2\t0.000133\t76.8']
    v.copy()
    assert app.clipboard().text().startswith('part\tloss (W)')
    assert v.export_csv(str(tmp_path / 't.csv')) and (tmp_path / 't.csv').read_text().startswith('"part","loss (W)"')
    v.which.setCurrentIndex(1)
    assert col(0) == ['B.Cu', 'F.Cu'] and v.table()[0] == 'Layers'
    v.set_report(dict(REPORT, sections=REPORT['sections'][2:]))     # another result: the table of that title kept
    assert v.which.currentText() == 'Layers'
    v.set_report(None)
    assert not v.has_tables() and g.rowCount() == 0 and not v.export_csv(str(tmp_path / 'none.csv'))
