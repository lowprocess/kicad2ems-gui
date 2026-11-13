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
from . import meshpick as mp

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


PICKED = '#1f6feb'                          # what a setting has picked on the board: blue, against the copper's orange


class PlanView(QWidget):
    selected = Signal(object)                                       # a section id, or None
    copper_colour, other_colour = COPPER, OTHER                     # the layer shown, the others

    def __init__(self):
        super().__init__()
        self.board, self.box, self.lines, self.meshes = None, None, None, {}
        self.sel, self.hover, self._items, self._sec = None, None, [], {}
        self._pick, self.picked, self._under = None, [], None       # (kind, callback): a click names a net or a part
        self._behind = None                                         # what a pick's board as drawn stands in front of
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
        self.solved = QCheckBox('solved')
        self.solved.setStyleSheet(f'QCheckBox {{ color: {mp.SOLVED_COLOUR}; }}')
        self.solved.toggled.connect(self.redraw)
        bar.addWidget(self.solved)
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
            with open(boards[-1], encoding='utf-8') as fh:
                board = json.load(fh)
        except (IndexError, OSError, ValueError):
            board = None
        return self.set_board(board, lines, meshes.find(out_dir) if out_dir else {})

    def set_board(self, board, lines=None, found_meshes=None, fit=True):
        """A board (Board.to_dict(), model mm) and its line model's drawing, without a results folder (the KiCad
        plugin's live board); False when there is no board."""
        from kicad2ems.api.frontend import meshes
        from . import volume3d as v3
        if self._behind is not None and not (board or {}).get('layout_of'):
            self._behind = (board, lines, found_meshes)             # a pick is on the board as drawn: this after it
            return board is not None
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
        for solver in mp.solvers(self.meshes):
            self.mesh.addItem(meshes.LABELS.get(solver, solver), solver)
        self.mesh.setCurrentIndex(max(self.mesh.findData(keep), 0))
        self.mesh.setEnabled(bool(self.meshes))
        self.mesh.blockSignals(False)
        self._solved_state()
        self.sel = self.hover = None
        self.redraw()
        if fit:
            self.fit()
        return self.board is not None

    def _solved_state(self):
        """The "solved" tick box: usable where a run of the solver picked wrote the mesh it solved on."""
        from kicad2ems.api.frontend import meshes
        solver = self.mesh.currentData()
        self.solved.setEnabled(mp.solved(self.meshes, solver) is not None)
        self.solved.setToolTip(mp.tip(self.meshes, solver, meshes.counts))

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
        if 'active_nets' in self.board:
            from .layoutscene import layout_items
            from .volume3d import geometry_from_board
            g=geometry_from_board(self.board)
            if self.copper.isChecked():
                for it in layout_items(g,lay,components=False):add(it)
            for it in layout_items({'components':g.get('components',[])},lay):add(it)
        elif self.copper.isChecked():
            for name, items in self.board['copper'].items():
                polys = [r for it in items for r in _rings(it['polygon'])]
                own = name == lay
                add(_item(_path(polys), QPen(QColor(150, 90, 30), 1) if own else QPen(Qt.NoPen),
                          QBrush(self.copper_colour if own else self.other_colour), -10 if own else -20))
        solver = self.mesh.currentData()
        self._solved_state()
        if solver and self.box is not None and self.z_of(lay) is not None:
            drawn = [(mp.shown(self.meshes, solver), dict(openems='#1f4fa0', mom25d='#1d7a3a').get(solver, '#333'),
                      1.0, 0.55, 0)]
            if self.solved.isChecked() and mp.solved(self.meshes, solver):      # the run's, in pink over it
                drawn.append((mp.solved(self.meshes, solver), mp.SOLVED_COLOUR, 1.3, 0.85, 1))
            for path, colour, width, alpha, z in drawn:
                seg = ov.plan_segments(path, self.box, self.z_of(lay)) if path else []
                if len(seg):
                    c = pg.PlotCurveItem(seg[:, 0], seg[:, 1], connect='pairs', pen=pg.mkPen(colour, width=width))
                    c.setOpacity(alpha)
                    c.setZValue(z)
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
        # the footprints of a board as drawn (kicad2ems.layout), outlined and named; what a setting has picked,
        # marked blue: a net's copper on this layer, a part's box
        for fp in self.board.get('footprints', []):
            if fp['layer'] != lay and not fp.get('through'):
                continue
            x0, y0, x1, y1 = fp['box']
            on = fp['ref'] in self.picked
            box = [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]]
            add(_item(_path([box]), QPen(QColor(PICKED if on else '#8a8f98'), 3.0 if on else 0.6, Qt.SolidLine if on
                                         else Qt.DotLine), QBrush(QColor(31, 111, 235, 90) if on else Qt.NoBrush), 26))
            if on or (x1 - x0) * (y1 - y0) > 4.0:                   # a name on the larger ones, and the picked
                t = pg.TextItem(fp['ref'], color='#0b2a66' if on else '#5b6068', anchor=(0.5, 0.5))
                t.setPos((x0 + x1) / 2, (y0 + y1) / 2)
                t.setZValue(32)
                add(t)
        if self.picked:
            polys = [r for it in self.board.get('copper', {}).get(lay, []) if it.get('net') in self.picked
                     for r in _rings(it['polygon'])]
            if polys:
                add(_item(_path(polys), QPen(QColor('#ffffff'), 1.0), QBrush(QColor(PICKED)), 24))
        self._mark()
        if 'active_nets' in self.board:
            self.info.setText('Cyan: simulated copper · grey: layout context · gold: selected components (package approximations)')
            return
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
        if i is not None and not self._pick:
            text = ov.describe(self.lines['elements'][i])
            self.info.setText(text)
            QToolTip.showText(self.plot.mapToGlobal(self.plot.mapFromScene(pos).toPoint()), text, self.plot)
            return
        net, part = self.under(pos)
        if net is not None or part is not None:                     # the board's own: what is under the cursor
            self.info.setText(' · '.join(x for x in (f"net {net or '(none)'}" if net is not None else '',
                                                    f"part {part}" if part else '') if x)
                              + ('   (click: ' + self._pick[2] + ')' if self._pick else ''))
        elif self._pick:
            self.info.setText(f"click {self._pick[2]}")
        elif self.lines and self.show_lines:
            self.info.setText('hover a section to read it; click to select')

    def under(self, scene_pos):
        """(the net, the part) under a point of the scene on the layer shown, each None where there is none."""
        if not self.board or not self.plot.sceneBoundingRect().contains(scene_pos):
            return None, None
        from kicad2ems.api.frontend import net_at, part_at
        p = self.plot.getPlotItem().vb.mapSceneToView(scene_pos)
        lay = self.current_layer()
        try:
            return net_at(self.board, lay, p.x(), p.y()), part_at(self.board, lay, p.x(), p.y())
        except Exception:                                           # noqa: BLE001 (a board dict without polygons)
            return None, None

    def _clicked(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        if self._pick:                                              # a setting is being picked: the net or the part
            net, part = self.under(ev.scenePos())
            name = part if self._pick[0].startswith('part') else net
            if name:
                self._pick[1](name)
            return
        self.select(self._at(ev.scenePos()), emit=True)

    def start_pick(self, kind, callback, picked=(), layout=None):
        """Clicks name a net ('net', 'nets') or a part ('part', 'parts') to callback(name) until end_pick();
        picked: the names already chosen, drawn marked. layout: the board as drawn (kicad2ems.layout), shown for
        the pick in place of a run's board (which has only the nets it simulated, and no parts) and put back
        after."""
        what = {'net': 'a trace or a pour: its net', 'nets': 'traces: their nets (again: taken out)',
                'part': "a part's pads", 'parts': "parts' pads (again: taken out)"}.get(kind, kind)
        self._pick, self.picked = (kind, callback, what), list(picked)
        if layout is not None and self.board is not layout:
            behind = self._behind if self._behind is not None else (self.board, self.lines, self.meshes)
            self._behind = None
            self.set_board(layout, None, {}, fit=self.board is None)    # (a run's board: the view stays where it is)
            self._behind = behind
        else:
            self.redraw()
        self.plot.setCursor(Qt.CrossCursor)
        self.info.setText(f"click {what}")

    def end_pick(self):
        self._pick, self.picked = None, []
        self.plot.unsetCursor()
        if self._behind is not None:                                # the run's board back
            behind, self._behind = self._behind, None
            if behind[0] is not None:
                self.set_board(*behind, fit=False)
                return
        self.redraw()

    def set_picked(self, names):
        self.picked = list(names)
        self.redraw()

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
