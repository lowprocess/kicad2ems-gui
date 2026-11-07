"""Shared 2D layout overlay, in model mm or reflected to the field viewer's KiCad axes."""
import numpy as np
from PySide6.QtGui import QColor, QPen, QBrush
import pyqtgraph as pg
from .planview import _path, _item


def layout_items(geometry, layer, kicad=False, components=True):
    def rings(polys):
        return [[np.asarray(r,float)*[1,-1 if kicad else 1] for r in p] for p in polys]
    items=[]
    active=geometry.get('active_copper',{})
    groups=[(geometry.get('inactive_copper',geometry.get('copper',{})), '#a8adb3', '#737b82', -8)]
    if active:groups.append((active,'#46c6d2','#007c88',-7))
    for copper,fill,line,z in groups:
        polys=copper.get(layer,[])
        if polys:
            it=_item(_path(rings(polys)),QPen(QColor(line),.9),QBrush(QColor(fill)),z)
            items.append(it)
    if components:
        for c in geometry.get('components',[]):
            if c['layer']!=layer:continue
            poly=c['polygon'];polys=[poly['coordinates']] if poly['type']=='Polygon' else poly['coordinates']
            col=QColor('#ffd166' if c.get('active') else '#a7a9ad');col.setAlpha(180)
            it=_item(_path(rings(polys)),QPen(QColor('#282828'),1.2),QBrush(col),8)
            it.setToolTip(f"{c['ref']} {c.get('value','')} — {c.get('shape_source','package approximation')}")
            items.append(it)
            if not c.get('active'):continue
            coords=np.asarray(polys[0][0],float);xy=(coords.min(0)+coords.max(0))/2
            label=pg.TextItem(c['ref'],color='#151515',anchor=(.5,.5))
            label.setPos(xy[0],-xy[1] if kicad else xy[1]);label.setZValue(9);items.append(label)
    return items
