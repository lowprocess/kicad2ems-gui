"""
The viewer's plan: the board seen from above (model mm, y up as in the 3D view): its outline, the copper of
one layer (the others faint), a solver's mesh on that layer, the ports, and the line model's sections drawn at
their width and coloured by Z0 against the ports' impedance. Hover a section to read it; click to select it
(the viewer's section list and the 3D view follow).
"""
import json, os
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainterPath, QPen, QBrush, QColor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QComboBox, QCheckBox, QLabel, QPushButton,
                               QGraphicsPathItem, QToolTip, QSizePolicy)
import pyqtgraph as pg
from kicad2ems.api.frontend import overlay as ov
from .panels import FlowLayout

COPPER = QColor(214, 140, 64)
OTHER = QColor(214, 140, 64, 45)


def _rings(geom):
    """GeoJSON-like polygon / multipolygon -> [[outer, hole, ...], ...]."""
    if geom['type'] == 'Polygon':
        return [geom['coordinates']]
    return list(geom['coordinates'])


def _path(polys):
    """A QPainterPath (odd-even fill: holes stay open) of [[outer, hole, ...], ...] rings."""
    p = QPainterPath()
    p.setFillRule(Qt.OddEvenFill)
    for rings in polys:
        for ring in rings:
            ring = np.asarray(ring, float)
            if len(ring) < 3:
                continue
            p.moveTo(*ring[0])
            for x, y in ring[1:]:
                p.lineTo(x, y)
            p.closeSubpath()
    return p


def _item(path, pen=None, brush=None, z=0):
    it = QGraphicsPathItem(path)
    pen = pen or QPen(Qt.NoPen)
    pen.setCosmetic(True)
    it.setPen(pen)
    it.setBrush(brush or QBrush(Qt.NoBrush))
    it.setZValue(z)
    return it


def section_path(e):
    """A section's outline as a QPainterPath (overlay.section_polygon)."""
    g = ov.section_polygon(e)
    if g.is_empty:
        return QPainterPath()
    polys = [g] if g.geom_type == 'Polygon' else list(g.geoms)
    return _path([[list(p.exterior.coords)] + [list(r.coords) for r in p.interiors] for p in polys])


class PlanView(QWidget):
    selected = Signal(object)                                       # a section id, or None
    copper_colour, other_colour = COPPER, OTHER                     # the layer shown, the others

    def __init__(self):
        super().__init__()
        self.board, self.box, self.lines, self.meshes = None, None, None, {}
        self.sel, self.hover, self._items, self._sec = None, None, [], {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = FlowLayout()
        bar.addWidget(QLabel('Layer'))
        self.layer = QComboBox()
        self.layer.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.layer.currentIndexChanged.connect(self.redraw)
        bar.addWidget(self.layer)
        self.copper = QCheckBox('copper')
        self.copper.setChecked(True)
        self.copper.toggled.connect(self.redraw)
        bar.addWidget(self.copper)
        bar.addWidget(QLabel('Mesh'))
        self.mesh = QComboBox()
        self.mesh.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.mesh.setToolTip("a solver's discretisation of this layer: openEMS's grid lines, mom25d's triangles")
        self.mesh.currentIndexChanged.connect(self.redraw)
        bar.addWidget(self.mesh)
        bar.addStretch(1)
        fit = QPushButton('Fit')
        fit.clicked.connect(self.fit)
        bar.addWidget(fit)
        lay.addLayout(bar)
        self.plot = pg.PlotWidget()
        self.plot.setBackground('w')
        self.plot.setAspectLocked(True)
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.setLabel('bottom', 'x (mm)')
        self.plot.setLabel('left', 'y (mm)')
        self.plot.scene().sigMouseMoved.connect(self._moved)
        self.plot.scene().sigMouseClicked.connect(self._clicked)
        self.plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.plot, 1)
        self.info = QLabel(' ')
        self.info.setStyleSheet('color: #444')
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.info)
        self.show_lines = True

    # ---- data ----
    def load(self, out_dir, lines=None):
        """A results folder's board (<name>_board.json), meshes and line model; False when there is no board."""
        import glob
        from kicad2ems.api.frontend import meshes
        boards = sorted(glob.glob(os.path.join(out_dir, '*_board.json')), key=os.path.getmtime) if out_dir else []
        try:
            with open(boards[-1]) as fh:
                board = json.load(fh)
        except (IndexError, OSError, ValueError):
            board = None
        return self.set_board(board, lines, meshes.find(out_dir) if out_dir else {})

    def set_board(self, board, lines=None, found_meshes=None, fit=True):
        """A board (Board.to_dict(), model mm) and its line model's drawing, without a results folder (the KiCad
        plugin's live board); False when there is no board."""
        from kicad2ems.api.frontend import meshes
        from . import volume3d as v3
        self.board = board
        self.box = v3.board_box(v3.geometry_from_board(board)) if board else None
        self.meshes = found_meshes or {}
        self.lines = lines
        keep = self.layer.currentData()
        self.layer.blockSignals(True)
        self.layer.clear()
        if self.board:
            cu = sorted(self.board['stack']['copper'], key=lambda c: -c['z'])     # top first
            for c in cu:
                self.layer.addItem(c['name'], c['name'])
        i = self.layer.findData(keep)
        self.layer.setCurrentIndex(max(i, 0))
        self.layer.blockSignals(False)
        keep = self.mesh.currentData()
        self.mesh.blockSignals(True)
        self.mesh.clear()
        self.mesh.addItem('none', None)
        for solver, p in self.meshes.items():
            self.mesh.addItem(meshes.LABELS.get(solver, solver), solver)
        self.mesh.setCurrentIndex(max(self.mesh.findData(keep), 0))
        self.mesh.setEnabled(bool(self.meshes))
        self.mesh.blockSignals(False)
        self.sel = self.hover = None
        self.redraw()
        if fit:
            self.fit()
        return self.board is not None

    def set_lines_visible(self, on):
        self.show_lines = on
        self.redraw()

    def current_layer(self):
        return self.layer.currentData()

    def z_of(self, layer):
        for c in (self.board or {}).get('stack', {}).get('copper', []):
            if c['name'] == layer:
                return c['z']
        return None

    # ---- drawing ----
    def redraw(self, *_):
        for it in self._items:
            self.plot.removeItem(it)
        self._items, self._sec = [], {}
        if not self.board:
            self.info.setText('Preview or run a board: its plan appears here')
            return
        lay = self.current_layer()
        add = lambda it: (self.plot.addItem(it), self._items.append(it))
        ol = self.board.get('outline')
        if ol:
            add(_item(_path(_rings(ol)), QPen(QColor('#555'), 1.2), QBrush(QColor(236, 240, 236)), -30))
        if self.copper.isChecked():
            for name, items in self.board['copper'].items():
                polys = [r for it in items for r in _rings(it['polygon'])]
                own = name == lay
                add(_item(_path(polys), QPen(QColor(150, 90, 30), 1) if own else QPen(Qt.NoPen),
                          QBrush(self.copper_colour if own else self.other_colour), -10 if own else -20))
        solver = self.mesh.currentData()
        if solver in self.meshes and self.box is not None and self.z_of(lay) is not None:
            seg = ov.plan_segments(self.meshes[solver], self.box, self.z_of(lay))
            if len(seg):
                colour = dict(openems='#1f4fa0', mom25d='#1d7a3a').get(solver, '#333')
                c = pg.PlotCurveItem(seg[:, 0], seg[:, 1], connect='pairs', pen=pg.mkPen(colour, width=1))
                c.setOpacity(0.55)
                c.setZValue(0)
                add(c)
        if self.lines and self.show_lines:
            ref, half = ov.reference(self.lines), ov.span(self.lines)
            for e in self.lines['elements']:
                if e.get('layer') != lay or not ov.drawn(e):
                    continue
                r, g, b = ov.section_colour(e, self.lines, ref, half)
                col = QColor.fromRgbF(r, g, b, 0.85)
                pen = QPen(col.darker(140), 1)
                if e.get('kind') == 'part':
                    pen.setStyle(Qt.DashLine)
                it = _item(section_path(e), pen, QBrush(col), 10)
                add(it)
                self._sec[e['id']] = it
        from . import volume3d as v3
        for p in self.board.get('parts', []):                       # lumped parts as their chips, true size
            if p.get('layer') != lay or not p.get('body') or not p.get('centre'):
                continue
            L, W, _ = p['body']
            cx, cy = p['centre']
            hx, hy = (L / 2, W / 2) if int(p.get('axis', 0)) == 0 else (W / 2, L / 2)
            body = [[[cx - hx, cy - hy], [cx + hx, cy - hy], [cx + hx, cy + hy], [cx - hx, cy + hy]]]
            r, g, b = v3.PART_COLOURS[v3.part_kind(p)]
            col = QColor.fromRgbF(r, g, b, 0.9)
            add(_item(_path([body]), QPen(col.darker(170), 1.2), QBrush(col), 25))
            t = pg.TextItem(p['ref'], color='#111', anchor=(0.5, 1.15))
            t.setPos(cx, cy + hy)
            t.setZValue(31)
            add(t)
        for p in self.board.get('ports', []):
            if p.get('layer') != lay or not p.get('c'):
                continue
            t = pg.TextItem(p['name'], color='w', fill=pg.mkBrush('#2f6fb0'), anchor=(0.5, 0.5))
            t.setPos(*p['c'])
            t.setZValue(30)
            add(t)
        self._mark()
        self.info.setText('hover a section to read it; click to select' if self.lines and self.show_lines
                          else ' ')

    def _mark(self):
        """Outline the selected section (thick) and the hovered one (thin)."""
        for i, it in self._sec.items():
            pen = it.pen()
            w = 3.0 if i == self.sel else (2.0 if i == self.hover else 1.0)
            pen.setWidthF(w)
            pen.setColor(QColor('#111') if i in (self.sel, self.hover) else it.brush().color().darker(140))
            it.setPen(pen)
            it.setZValue(20 if i == self.sel else 10)

    def fit(self):
        if self.box is not None:
            x0, y0, x1, y1 = self.box[:4]
            self.plot.setRange(xRange=(x0, x1), yRange=(y0, y1), padding=0.04)

    # ---- the mouse ----
    def _at(self, scene_pos):
        vb = self.plot.getPlotItem().vb
        if not self.plot.sceneBoundingRect().contains(scene_pos):
            return None
        p = vb.mapSceneToView(scene_pos)
        px = vb.viewPixelSize()[0]
        if not (self.lines and self.show_lines):
            return None
        return ov.nearest(self.lines['elements'], p.x(), p.y(), 4 * px, layer=self.current_layer())

    def _moved(self, pos):
        i = self._at(pos)
        if i != self.hover:
            self.hover = i
            self._mark()
        if i is not None:
            text = ov.describe(self.lines['elements'][i])
            self.info.setText(text)
            QToolTip.showText(self.plot.mapToGlobal(self.plot.mapFromScene(pos).toPoint()), text, self.plot)
        elif self.lines and self.show_lines:
            self.info.setText('hover a section to read it; click to select')

    def _clicked(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        self.select(self._at(ev.scenePos()), emit=True)

    def select(self, i, emit=False):
        """Select a section (None: none); on its layer (switched to if need be)."""
        if i is not None and self.lines:
            lay = self.lines['elements'][i].get('layer')
            if lay and lay != self.current_layer() and self.layer.findData(lay) >= 0:
                self.sel = i
                self.layer.setCurrentIndex(self.layer.findData(lay))     # redraws, then marks
            self.info.setText(ov.describe(self.lines['elements'][i]))
        self.sel = i
        self._mark()
        if emit:
            self.selected.emit(i)
