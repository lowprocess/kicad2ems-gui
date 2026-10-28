"""
The Viewer: everything about the board and its fields in one page.

    3D       the board in 3D: copper, vias, a solver's mesh, plane and volume dumps in place, the far field
    Plan     the board from above: one layer's copper, a solver's mesh on it, the ports
    Cut      a cut through a field dump, with its values (time frames, phases, live while openEMS runs)
    Images   the plots a run wrote (the openEMS mesh with its side views, the model, the line model)

The line model is an overlay of 3D and Plan: its sections coloured by Z0 against the ports' impedance, listed
beside the view with their Z0, length, delay and eeff. Pick a section in the list, or click it in the plan: both
views mark it. The views a folder has nothing for are disabled.
"""
import glob, os
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QLinearGradient, QPixmap, QIcon
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QToolButton, QButtonGroup, QStackedWidget,
                               QSplitter, QTreeWidget, QTreeWidgetItem, QCheckBox, QLabel, QHeaderView, QSizePolicy)
from kicad2ems import overlay as ov
from .fieldtab import FieldsTab
from .panels import ImagePanel
from .planview import PlanView
from .volumetab import VolumeTab

VIEWS = ('3D', 'Plan', 'Cut', 'Images')
TIPS = {'3D': 'the board in 3D: copper, a solver\'s mesh, the line model, dumps in place, the far field',
        'Plan': 'the board from above: one layer, a solver\'s mesh, the line model (hover, click a section)',
        'Cut': 'a cut through a field dump, with its values',
        'Images': 'the plots the run wrote: the openEMS mesh and its side views, the model, the line model'}


class Z0Legend(QWidget):
    """The Z0 colours: blue below the ports' impedance, grey at it, red above."""
    def __init__(self):
        super().__init__()
        self.ref, self.half = 50.0, 10.0
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_range(self, ref, half):
        self.ref, self.half = ref, half
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), 12
        g = QLinearGradient(0, 0, w, 0)
        for t in (0.0, 0.5, 1.0):
            r, gg, b = ov.z0_colour(self.ref + (2 * t - 1) * self.half, self.ref, self.half)
            g.setColorAt(t, QColor.fromRgbF(r, gg, b))
        p.fillRect(0, 2, w, h, g)
        p.setPen(QColor('#333'))
        y = h + 16
        p.drawText(0, y, f"{self.ref - self.half:.0f} Ω")
        mid = f"Z0 {self.ref:.0f} Ω"
        p.drawText(int(w / 2 - p.fontMetrics().horizontalAdvance(mid) / 2), y, mid)
        right = f"{self.ref + self.half:.0f} Ω"
        p.drawText(w - p.fontMetrics().horizontalAdvance(right) - 1, y, right)


def _swatch(rgb):
    pm = QPixmap(12, 12)
    pm.fill(QColor.fromRgbF(*rgb))
    return QIcon(pm)


class Viewer(QWidget):
    view_changed = Signal(str)

    def __init__(self, win=None):
        super().__init__()
        self.win, self.out, self.lines = win, None, None
        self.cuts, self.volume, self.plan = FieldsTab(win), VolumeTab(win), PlanView()
        self.images = ImagePanel('the plots of a preview or a run: the openEMS mesh, the model, the line model')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.buttons, group = {}, QButtonGroup(self)
        group.setExclusive(True)
        for name in VIEWS:
            b = QToolButton()
            b.setText(name)
            b.setCheckable(True)
            b.setToolTip(TIPS[name])
            b.setMinimumWidth(56)
            b.clicked.connect(lambda _=False, n=name: self.set_view(n))
            group.addButton(b)
            bar.addWidget(b)
            self.buttons[name] = b
        bar.addSpacing(12)
        self.lines_on = QCheckBox('Line model')
        self.lines_on.setChecked(True)
        self.lines_on.setToolTip("the line model's sections over the board, coloured by Z0")
        self.lines_on.toggled.connect(self._lines_toggled)
        bar.addWidget(self.lines_on)
        bar.addStretch(1)
        self.note = QLabel('')
        self.note.setStyleSheet('color: gray')
        bar.addWidget(self.note)
        lay.addLayout(bar)

        self.stack = QStackedWidget()
        self.views = {'3D': self.volume, 'Plan': self.plan, 'Cut': self.cuts, 'Images': self.images}
        for w in self.views.values():
            self.stack.addWidget(w)
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(4, 0, 0, 0)
        sl.addWidget(QLabel('<b>Line model</b>'))
        self.legend = Z0Legend()
        sl.addWidget(self.legend)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['section', 'Z0 (Ω)', 'mm', 'ps', 'εeff'])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.tree.header().setStretchLastSection(False)
        self.tree.setColumnWidth(0, 170)
        for c in range(1, 5):
            self.tree.header().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._tree_picked)
        sl.addWidget(self.tree, 1)
        self.detail = QLabel(' ')
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sl.addWidget(self.detail)
        self.side = side
        self.split = QSplitter()
        self.split.setObjectName('viewer')
        self.split.addWidget(self.stack)
        self.split.addWidget(side)
        self.split.setStretchFactor(0, 1)
        self.split.setCollapsible(0, False)
        self.split.setSizes([880, 380])
        lay.addWidget(self.split, 1)
        self.plan.selected.connect(lambda i: self.select(i, source='plan'))
        self._items = {}
        self.set_view('3D' if self.volume.gl is not None else 'Plan')
        self._fit()

    # ---- data ----
    def load(self, out_dir):
        """A results folder in every view; the first view with something in it shown unless the one shown still
        has. False: nothing to show."""
        self.out = out_dir
        self.lines = ov.load_lines(out_dir)
        self.volume.set_lines(self.lines)
        three = self.volume.load(out_dir)
        plan = self.plan.load(out_dir, self.lines)
        self.cuts.load(out_dir)
        imgs = [p for p in sorted(glob.glob(os.path.join(out_dir, '*.png')))
                if p.endswith(('_model.png', '_mesh.png', '_tlines.png'))]
        self.images.show_images(imgs)
        self._fill_tree()
        self.detail.setText(' ')                                    # a new folder: nothing selected
        has = {'3D': self.volume.gl is not None and bool(three or plan), 'Plan': plan,
               'Cut': bool(self.cuts.srcs), 'Images': bool(imgs)}
        for n, b in self.buttons.items():
            b.setEnabled(has[n])
        cur = self.view()
        if not has.get(cur):
            vol = bool(self.volume.srcs) if self.volume.gl is not None else False     # volume or plane dumps
            order = ['3D', 'Plan', 'Cut', 'Images'] if (vol or not self.cuts.srcs) else ['Cut', '3D', 'Plan', 'Images']
            nxt = next((n for n in order if has[n]), cur)
            self.set_view(nxt)
        self._fit()
        return any(has.values())

    def follow(self, out_dir):
        """A running simulation's newest field frames (the Cut view's live mode)."""
        self.cuts.follow(out_dir)

    def _fill_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items = {}
        d = self.lines
        if d:
            ref, half = ov.reference(d), ov.span(d)
            self.legend.set_range(ref, half)
            els, used = d['elements'], set()

            def row(parent, e):
                z0 = e.get('z0')
                it = QTreeWidgetItem([e.get('label') or e.get('kind', ''), f"{z0:.1f}" if z0 else '',
                                      f"{e['length']:.2f}" if e.get('length') is not None else '',
                                      f"{e['delay_ps']:.1f}" if e.get('delay_ps') else '',
                                      f"{e['eeff']:.2f}" if e.get('eeff') else ''])
                it.setIcon(0, _swatch(ov.z0_colour(z0, ref, half)))
                it.setData(0, Qt.UserRole, e['id'])
                it.setToolTip(0, ov.describe(e))
                parent.addChild(it)
                self._items.setdefault(e['id'], it)
            for p in d.get('paths', []):
                top = QTreeWidgetItem([f"{p['port']} → {p.get('to') or 'end'}"])
                self.tree.addTopLevelItem(top)
                for i in p['ids']:
                    if els[i].get('kind') != 'coupling':
                        row(top, els[i])
                        used.add(i)
                top.setExpanded(True)
            rest = [e for e in els if e['id'] not in used and e.get('kind') != 'coupling']
            if rest:
                top = QTreeWidgetItem(['other pieces'])
                self.tree.addTopLevelItem(top)
                for e in rest:
                    row(top, e)
        self.tree.blockSignals(False)

    # ---- views ----
    def set_view(self, name):
        self.stack.setCurrentWidget(self.views[name])
        for n, b in self.buttons.items():
            b.setChecked(n == name)
        self._fit()
        self.view_changed.emit(name)

    def view(self):
        return next(n for n, w in self.views.items() if self.stack.currentWidget() is w)

    def _fit(self):
        """The section list where it means something: a line model, shown, in the 3D or plan view."""
        on = bool(self.lines) and self.lines_on.isChecked() and self.view() in ('3D', 'Plan')
        self.side.setVisible(on)
        self.lines_on.setVisible(bool(self.lines) and self.view() in ('3D', 'Plan'))
        n = len([e for e in (self.lines or {}).get('elements', []) if e.get('kind') != 'coupling'])
        self.note.setText(f"{n} line-model sections" if self.lines else ('no line model' if self.out else ''))

    def _lines_toggled(self, on):
        self.plan.set_lines_visible(on)
        if self.volume.gl is not None:
            self.volume.lines_on.setChecked(on)
        self._fit()

    # ---- the selected section ----
    def _tree_picked(self):
        its = self.tree.selectedItems()
        i = its[0].data(0, Qt.UserRole) if its else None
        if i is not None:
            self.select(i, source='tree')

    def select(self, i, source=None):
        """Select a section in every view (i None: none)."""
        if source != 'plan':
            self.plan.select(i)
        self.volume.select(i)
        if source != 'tree':
            self.tree.blockSignals(True)
            self.tree.clearSelection()
            if i in self._items:
                self._items[i].setSelected(True)
                self.tree.scrollToItem(self._items[i])
            self.tree.blockSignals(False)
        self.detail.setText(ov.describe(self.lines['elements'][i]) if (i is not None and self.lines) else ' ')

    @property
    def selected(self):
        return self.plan.sel

