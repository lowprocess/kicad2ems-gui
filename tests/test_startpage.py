"""The Start page (startpage.py): a window with no board begins there; the examples as tiles by group, found by a
word; a board's picture drawn from its layout; the page out of the way once a board is chosen."""
import os

import pytest

pytest.importorskip('PySide6')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from kicad2ems_gui import startpage as SP                              # noqa: E402
from k2e_fixtures import ROOT                                          # noqa: E402

ENTRIES = [dict(name=f"rf_{k}", config='', group='RF structures/Filters', title=f"{k} filter, 2 GHz (FR4)", source='kicad2ems')
           for k in ('hairpin', 'interdig', 'combline', 'steplpf', 'stubnotch', 'openloop', 'pcoupled')] + \
          [dict(name='antenna_patch', config='', group='Antennas/Patches', title='inset-fed patch, 2.45 GHz', source='kicad2ems'),
           dict(name='circuit_buck', config='', group='Circuits/DC-DC converters', title='Buck converter: 12 V to 5 V', source='circuit')]


@pytest.fixture
def app():
    from kicad2ems_gui import application
    return application()


def test_tiles_by_group_and_found_by_a_word(app):
    page = SP.StartPage(None, ENTRIES)
    assert [g for g, *_ in page.groups] == ['RF structures', 'Antennas', 'Circuits'] and len(page.tiles) == 9
    assert SP.short_title(ENTRIES[0]) == 'Hairpin filter' and SP.short_title(ENTRIES[-1]) == 'Buck converter'
    rf = [n for n in page.visible_tiles() if n.startswith('rf_')]
    assert len(rf) == SP.FIRST and 'all' in page.groups[0][1].text() and '7 examples' in page.groups[0][1].text()
    page.toggle('RF structures')                                        # all of them, and back
    assert len([n for n in page.visible_tiles() if n.startswith('rf_')]) == 7 and 'fewer' in page.groups[0][1].text()
    page.toggle('RF structures')
    page.find.setText('buck 12')                                        # every word, in a name, a title or a group
    assert page.visible_tiles() == ['circuit_buck'] and page.groups[0][1].isHidden() and page.none.isHidden()
    page.find.setText('filters')
    assert len(page.visible_tiles()) == 7                               # (the group's name: all seven, not five)
    page.find.setText('zzz')
    assert page.visible_tiles() == [] and not page.none.isHidden()
    opened = []
    page.find.setText('')
    tile = page.tiles['antenna_patch']
    tile.clicked.connect(opened.append)                                 # (the page's own slot opens it in the window)
    tile.clicked.emit('antenna_patch')
    assert opened == ['antenna_patch'] and tile.toolTip() == 'antenna_patch: inset-fed patch, 2.45 GHz'


def test_a_board_s_picture_is_its_copper_from_above(app, tmp_path):
    from kicad2ems.api.frontend import board_layout
    img = SP.board_image(board_layout(os.path.join(ROOT, 'examples', 'rf_bus.kicad_pcb')))
    assert (img.width(), img.height()) == SP.PICTURE
    colours = {img.pixelColor(x, y).name() for x in range(0, img.width(), 3) for y in range(0, img.height(), 3)}
    assert '#d08a3c' in colours and '#f3f4f6' in colours and len(colours) > 3      # the traces, the page, the board
    png = tmp_path / 'p.png'
    assert img.save(str(png))
    tile = SP.Tile(ENTRIES[0])
    assert tile.picture.pixmap().isNull() and tile.picture.text() == 'rf_hairpin'    # until its picture is there
    tile.set_picture(str(png))
    assert not tile.picture.pixmap().isNull()


def test_the_window_begins_on_the_start_page(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    from PySide6.QtCore import QSettings
    from kicad2ems_gui import application
    from kicad2ems_gui.app import MainWindow
    app = application()
    QSettings('kicad2ems', 'gui').clear()
    monkeypatch.setattr(SP.StartPage, 'start_pictures', lambda self: None)       # (no thread in this test)
    w = MainWindow()
    w.system.stop()
    w.meters.stop()
    w.show()
    app.processEvents()
    start = w.docks['Start']
    assert start.widget() is w.start_page and start in w.work.tabifiedDockWidgets(w.docks['Viewer']) and start.in_front()
    assert len(w.start_page.tiles) > 5 and set(w.start_page.buttons) == {'Open a KiCad board…', 'Open a config…', 'Open a results folder…'}
    pages = [w.docks[n] for n in ('Results', 'Report', 'Tables', 'Run')]
    assert all(d.isHidden() for d in pages)                             # the workspace is the page's: nothing to show yet
    board = os.path.join(ROOT, 'examples', 'rf_bus.kicad_pcb')
    w.setup.set_values(dict(board=board, out=str(tmp_path / 'out')))    # a board chosen: the page out of the way
    w.update_needed()
    app.processEvents()
    assert start.isHidden() and w.docks['Viewer'].in_front()
    assert not any(d.isHidden() for d in pages)                         # and the result pages back
    w.show_panel('Start')                                               # View brings it back, and it stays
    w.update_needed()
    app.processEvents()
    assert start.in_front()
    w.setup.dirty = False
    w.setup.new()                                                       # the study emptied: the page again
    start.hide()
    w.update_needed()
    app.processEvents()
    assert start.in_front() and all(d.isHidden() for d in pages)
    w.show_panel('Run')                                                 # a page asked for by hand (View): there
    app.processEvents()
    assert not w.docks['Run'].isHidden() and w.docks['Report'].isHidden()
    w._start_leaves(hide=False)                                         # a result opened: its pages back, the page stays
    app.processEvents()
    assert not any(d.isHidden() for d in pages) and not start.isHidden() and w._aside is None
    cfg = tmp_path / 'a.toml'
    cfg.write_text(f'board = "{board}"\n')
    w.remember(str(cfg))                                                # a config opened lately: listed
    assert 'a.toml' in w.start_page.recent.text() and w.start_page._recent == [str(cfg)]
    w.setup.dirty = False
    w.close()
    QSettings('kicad2ems', 'gui').clear()
