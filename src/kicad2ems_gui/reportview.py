"""
An analysis's report on the Results page (Analysis.report: a title, a line, sections of text and tables, notes,
pictures): as a page to read, or as its tables to sort, copy and export. The helpers need no Qt.

    to_html(report)                 the page
    tables(report)                  [(title, table)]: the sections that hold one
    cell(value, format)             a cell as it is shown; to_csv(table) a table as CSV text
    view = ReportView(); view.set_report(report); view.set_mode('Tables')
"""
import html

MODES = ('Report', 'Tables')


def cell(v, fmt=None):
    """A cell as it is shown: a number by its column's format (None: '.4g'), anything else as it is."""
    if v is None or v == '':
        return ''
    if isinstance(v, bool):
        return 'yes' if v else 'no'
    if isinstance(v, (int, float)):
        try:
            return format(int(v) if fmt == 'd' else v, fmt or '.4g')
        except (ValueError, TypeError):
            return f"{v:.4g}"
    return str(v)


def tables(report):
    """[(title, table)] of the report's sections that hold a table (an untitled one: 'Table n')."""
    out = []
    for s in (report or {}).get('sections', []):
        if s.get('table') and s['table'].get('columns'):
            out.append((s.get('title') or f"Table {len(out) + 1}", s['table']))
    return out


def _formats(table):
    return list(table.get('formats') or []) + [None] * len(table['columns'])


def to_csv(table):
    q = lambda t: '"' + str(t).replace('"', "'") + '"'
    f = _formats(table)
    rows = [','.join(q(c) for c in table['columns'])]
    for r in table['rows']:
        rows.append(','.join('' if v in ('', None) else q(v) if isinstance(v, str) else cell(v, f[k]).replace(',', '')
                             for k, v in enumerate(r)))
    return '\n'.join(rows) + '\n'


def _table_html(table):
    e, f = html.escape, _formats(table)
    num = [all(isinstance(r[k], (int, float)) or r[k] in ('', None) for r in table['rows']) and
           any(isinstance(r[k], (int, float)) for r in table['rows']) for k in range(len(table['columns']))]
    h = ["<table border=0 cellspacing=6><tr>" + ''.join(
        f"<th align={'right' if num[k] else 'left'}>{e(str(c))}</th>" for k, c in enumerate(table['columns'])) + "</tr>"]
    for r in table['rows']:
        h.append("<tr>" + ''.join(f"<td align={'right' if num[k] else 'left'}>{e(cell(v, f[k]))}</td>"
                                  for k, v in enumerate(r)) + "</tr>")
    h.append("</table>")
    return ''.join(h)


def to_html(report, width=820):
    """The report as a page: its title, each section (its heading, text, table and notes), the notes, the
    pictures, the footer."""
    if not report:
        return ''
    e = html.escape
    h = [f"<h3>{e(report.get('title') or '')}</h3>"]
    for s in report.get('sections', []):
        if s.get('title'):
            h.append(f"<h4>{e(s['title'])}</h4>")
        if s.get('text'):
            h.append(f"<p>{e(s['text'])}</p>")
        if s.get('table') and s['table'].get('columns'):
            h.append(_table_html(s['table']))
        if s.get('notes'):
            h.append("<ul>" + ''.join(f"<li>{e(str(n))}</li>" for n in s['notes']) + "</ul>")
    if report.get('notes'):
        h.append("<h4>Notes</h4><ul>" + ''.join(f"<li>{e(str(n))}</li>" for n in report['notes']) + "</ul>")
    for p in report.get('images') or []:
        h.append(f"<p><img src='{e(str(p))}' width={int(width)}></p>")
    if report.get('footer'):
        h.append(f"<p style='color:gray'>{e(report['footer'])}</p>")
    return '\n'.join(h)


try:                                                    # the view itself (Qt); the helpers above need none
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QTextBrowser, QTableWidget,
                                   QTableWidgetItem, QComboBox, QPushButton, QLabel, QFileDialog, QApplication,
                                   QAbstractItemView, QHeaderView)
except ImportError:                                     # pragma: no cover
    QWidget = QTableWidgetItem = object


class _Cell(QTableWidgetItem):
    """A cell that sorts by its value: numbers as numbers (the empty ones last), text as text."""
    def __init__(self, value, text):
        super().__init__(text)
        self.value = value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def _key(self):
        v = self.value
        return (0, v, '') if isinstance(v, (int, float)) and not isinstance(v, bool) else \
            (2, 0, '') if v in ('', None) else (1, 0, str(v).lower())

    def __lt__(self, other):
        return self._key() < other._key() if isinstance(other, _Cell) else super().__lt__(other)


class ReportView(QWidget):
    """The report to read (a page) or its tables one at a time: sorted by a click on a column, copied (the
    selection, or all of it, tab-separated: it pastes into a spreadsheet), exported as CSV."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.report, self._tables = None, []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.page = QTextBrowser()
        self.page.setOpenExternalLinks(True)
        self.stack.addWidget(self.page)
        tw = QWidget()
        tl = QVBoxLayout(tw)
        tl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel('Table'))
        self.which = QComboBox()
        self.which.setMinimumWidth(260)
        self.which.currentIndexChanged.connect(self._show_table)
        row.addWidget(self.which)
        for text, tip, slot in (('Copy', 'the selected cells, or the whole table: tab-separated, with its header',
                                 self.copy), ('Export CSV…', 'this table as a CSV file', self.export_csv)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=slot: f())
            row.addWidget(b)
        self.hint = QLabel('click a column to sort by it')
        self.hint.setStyleSheet('color: gray')
        row.addWidget(self.hint)
        row.addStretch(1)
        tl.addLayout(row)
        self.grid = QTableWidget(0, 0)
        self.grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.grid.setAlternatingRowColors(True)
        self.grid.verticalHeader().hide()
        self.grid.setSortingEnabled(True)
        tl.addWidget(self.grid, 1)
        self.stack.addWidget(tw)
        lay.addWidget(self.stack)

    def set_report(self, report):
        """The report shown (None: none); the table chosen stays when the new report has one of its title."""
        self.report = report
        self._tables = tables(report)
        if report is None:                                          # nothing to read yet: say where it comes from
            self.page.setHtml("<p style='color:gray'>No report yet. An analysis's result (a rail's drop, a circuit, the "
                              "temperature, crosstalk) is written up here when it has run; the S-parameter run's "
                              "report opens from the toolbar (Report).</p>")
        else:
            self.page.setHtml(to_html(report, width=max(400, self.page.viewport().width() - 40)))
        keep = self.which.currentText()
        self.which.blockSignals(True)
        self.which.clear()
        self.which.addItems([t for t, _ in self._tables])
        i = self.which.findText(keep)
        self.which.setCurrentIndex(max(i, 0) if self._tables else -1)
        self.which.blockSignals(False)
        self._show_table()

    def has_tables(self):
        return bool(self._tables)

    def mode(self):
        return MODES[self.stack.currentIndex()]

    def set_mode(self, mode):
        self.stack.setCurrentIndex(MODES.index(mode) if mode in MODES else 0)

    def table(self):
        """The table shown: (title, table), or None."""
        i = self.which.currentIndex()
        return self._tables[i] if 0 <= i < len(self._tables) else None

    def _show_table(self, *_):
        g, t = self.grid, self.table()
        g.setSortingEnabled(False)
        g.clear()
        if t is None:
            g.setRowCount(0)
            g.setColumnCount(0)
            return
        table = t[1]
        f = _formats(table)
        g.setColumnCount(len(table['columns']))
        g.setRowCount(len(table['rows']))
        g.setHorizontalHeaderLabels([str(c) for c in table['columns']])
        for r, row in enumerate(table['rows']):
            for k, v in enumerate(row):
                g.setItem(r, k, _Cell(v, cell(v, f[k])))
        g.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        g.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)    # as the report has it, until a click
        g.setSortingEnabled(True)

    def _text(self, selected=True):
        """The table as tab-separated lines, as it is sorted: the selected cells' block, else all of it."""
        g = self.grid
        rows, cols = range(g.rowCount()), range(g.columnCount())
        picked = g.selectedIndexes() if selected else []
        if len(picked) > 1:
            rows = sorted({i.row() for i in picked})
            cols = sorted({i.column() for i in picked})
        lines = ['\t'.join(g.horizontalHeaderItem(c).text() for c in cols)]
        lines += ['\t'.join(g.item(r, c).text() if g.item(r, c) else '' for c in cols) for r in rows]
        return '\n'.join(lines)

    def copy(self):
        QApplication.clipboard().setText(self._text())

    def export_csv(self, path=None):
        t = self.table()
        if t is None:
            return False
        if path is None:
            name = ''.join(c if c.isalnum() else '_' for c in t[0]).strip('_') or 'table'
            path, _ = QFileDialog.getSaveFileName(self, 'Export the table', f"{name}.csv", 'CSV (*.csv)')
        if not path:
            return False
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(to_csv(t[1]))
        return True
