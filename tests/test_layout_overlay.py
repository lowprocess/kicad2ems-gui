"""Layout coordinates, holes, active/context copper and display-only component solids."""
import os
import numpy as np
import pytest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF
from kicad2ems_gui.layoutscene import layout_items
from kicad2ems_gui.volume3d import component_solids


def test_overlay_preserves_holes_and_reflects_kicad_y():
    app=QApplication.instance() or QApplication([])
    outer=[[1,2],[5,2],[5,6],[1,6],[1,2]]
    hole=[[2,3],[3,3],[3,4],[2,4],[2,3]]
    g=dict(active_copper={'F':[[outer,hole]]},inactive_copper={})
    it=layout_items(g,'F',kicad=True)[0]
    assert it.path().contains(QPointF(1.5,-2.5))
    assert not it.path().contains(QPointF(2.5,-3.5))
    assert it.path().boundingRect().top()==-6


def test_body_height_side_and_highlight():
    c=dict(ref='U1',polygon=dict(type='Polygon',coordinates=[[[0,0],[2,0],[2,1],[0,1],[0,0]]]),
           height=.75,z=1.2,side='F',active=True)
    rgba,verts,faces=component_solids(c,{'F':1.2},zs=2,lift=.05)[0]
    assert verts[:,2].min()==pytest.approx(2.45)
    assert verts[:,2].max()==pytest.approx(3.2)
    assert faces.max()<len(verts)
    c.update(side='B',z=0,active=False)
    grey,verts,_=component_solids(c,{'F':1.2,'B':0},zs=2,lift=.05)[0]
    assert verts[:,2].max()==pytest.approx(-.05)
    assert grey!=rgba
