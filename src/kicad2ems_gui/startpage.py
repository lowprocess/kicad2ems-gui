"""
The Start page: where a window with no board begins.

    StartPage(win)      open a board, a config or a results folder; the configs opened lately; and every example
                        (kicad2ems's own and those the installed analyses ship) as a tile with its board drawn,
                        by group, with a box that finds one by a word of its name or title

A tile opens its example as File > Examples does (win.open_example: copied to a folder of the user's, its board
made if it is generated). The pictures are drawn from the boards themselves, in a thread, once: kept as PNG files
under the user's cache folder ($XDG_CACHE_HOME/kicad2ems/thumbs), by example and kicad2ems version. A board that
is generated is made in the cache for it, not in the user's examples folder.
"""
import os

from PySide6.QtCore import Qt, QThread, Signal, QRectF, QPointF
from PySide6.QtGui import QImage, QPainter, QPainterPath, QColor, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QScrollArea, QFrame,
                               QSizePolicy)

from .panels import FlowLayout

TILE, PICTURE = (236, 196), (220, 128)      # a tile and its picture, px
FIRST = 5                                   # the tiles a group shows until "all" is clicked
RECENT = 4                                  # the configs opened lately that are listed


def cache_folder():
    base = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
    return os.path.join(base, 'kicad2ems', 'thumbs')


def short_title(entry):
    """An example's heading on its tile: its title up to the first comma, colon or bracket, capitalised."""
    t = (entry.get('title') or entry['name']).strip()
    for stop in (',', ':', ' (', ';'):
        t = t.split(stop)[0]
    t = t.strip() or entry['name']
    return t[:1].upper() + t[1:]


def board_image(layout, size=PICTURE):
    """A board as drawn (kicad2ems.layout.board_layout's dict), from above, as a picture: its outline, the copper
    of the layers under the top faint, the top layer's over them."""
    w, h = size
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor('#f3f4f6'))
    rings = lambda poly: [poly['coordinates']] if poly['type'] == 'Polygon' else list(poly['coordinates'])
    layers = sorted(layout['stack']['copper'], key=lambda c: c['z'])        # bottom first
    shapes = [(c['name'], [r for it in layout.get('copper', {}).get(c['name'], []) for r in rings(it['polygon'])])
              for c in layers]
    outline = rings(layout['outline']) if layout.get('outline') else []
    pts = [p for group in ([outline] + [s for _, s in shapes]) for poly in group for ring in poly for p in ring]
    if not pts:
        return img
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    k = min((w - 12) / max(x1 - x0, 1e-6), (h - 12) / max(y1 - y0, 1e-6))
    ox, oy = (w - k * (x1 - x0)) / 2, (h - k * (y1 - y0)) / 2

    def path(polys):
        pp = QPainterPath()
        pp.setFillRule(Qt.OddEvenFill)
        for poly in polys:
            for ring in poly:
                pp.addPolygon(QPolygonF([QPointF(ox + k * (x - x0), oy + k * (y1 - y)) for x, y in ring]))  # y up
                pp.closeSubpath()
        return pp
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    if outline:
        p.setPen(QPen(QColor('#9aa58a'), 1))
        p.setBrush(QColor('#e7eddc'))
        p.drawPath(path(outline))
    p.setPen(Qt.NoPen)
    for i, (name, polys) in enumerate(shapes):
        if polys:
            top = i == len(shapes) - 1
            p.setBrush(QColor(208, 138, 60, 255) if top else QColor(160, 150, 130, 70))
            p.drawPath(path(polys))
    p.end()
    return img


class _Thumbs(QThread):
    """The examples' pictures, each drawn once and kept: done(name, PNG path) as each is there."""
    done = Signal(str, str)

    def __init__(self, entries, version):
        super().__init__()
        self.entries, self.version, self.stop = list(entries), version, False

    def run(self):
        from kicad2ems.api.frontend import board_layout
        from kicad2ems import examples as X
        folder = cache_folder()
        boards = os.path.join(folder, 'boards')
        os.makedirs(boards, exist_ok=True)
        for e in self.entries:
            if self.stop:
                return
            png = os.path.join(folder, f"{e['name']}-{self.version}.png")
            if not os.path.isfile(png):
                try:
                    board = X.board_of(e['config'], needed=False)
                    if not board:
                        continue
                    path = os.path.join(os.path.dirname(e['config']), board)
                    if not os.path.isfile(path):                    # a generated board: made in the cache
                        cfg = X.prepare_example(e['name'], dest=boards)
                        path = os.path.join(os.path.dirname(cfg), board)
                    if not board_image(board_layout(path)).save(png):
                        continue
                except Exception:                                   # noqa: BLE001 (no picture: the tile's own grey)
                    continue
            self.done.emit(e['name'], png)


class Tile(QFrame):
    """An example: its board's picture, its heading, its name; a click opens it."""
    clicked = Signal(str)

    def __init__(self, entry):
        super().__init__()
        self.entry, self.name = entry, entry['name']
        self.words = ' '.join(str(entry.get(k) or '') for k in ('name', 'title', 'group')).lower()
        self.setObjectName('tile')
        self.setFixedSize(*TILE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{entry['name']}: {entry.get('title') or ''}")
        self.setStyleSheet('QFrame#tile { border: 1px solid palette(mid); border-radius: 6px; background: palette(base); }'
                           'QFrame#tile:hover { border: 1px solid palette(highlight); }')
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 6)
        v.setSpacing(3)
        self.picture = QLabel()
        self.picture.setFixedSize(*PICTURE)
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setStyleSheet('background: #f3f4f6; border-radius: 4px; color: #9ca3af;')
        self.picture.setText(entry['name'])
        v.addWidget(self.picture)
        head = QLabel(f"<b>{short_title(entry)}</b>")
        head.setWordWrap(True)
        v.addWidget(head)
        sub = QLabel(entry['name'])
        sub.setStyleSheet('color: gray; font-size: 11px;')
        v.addWidget(sub)
        v.addStretch(1)

    def set_picture(self, png):
        pm = QPixmap(png)
        if not pm.isNull():
            self.picture.setPixmap(pm)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.position().toPoint()):
            self.clicked.emit(self.name)
        super().mouseReleaseEvent(ev)


class StartPage(QWidget):
    def __init__(self, win=None, entries=None):
        super().__init__()
        self.win = win
        self.setObjectName('start')
        self.setStyleSheet('QWidget#start { background: palette(base); }')
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 16, 24, 12)
        v.setSpacing(10)
        v.addWidget(QLabel("<span style='font-size:20px; font-weight:600'>Start</span>"
                           "<span style='color:gray'>&nbsp;&nbsp;&nbsp;open a board, or begin from an example</span>"))
        row = FlowLayout()
        self.buttons = {}
        for text, slot, tip in (
                ('Open a KiCad board…', self._board, 'Choose a .kicad_pcb: a new study of that board'),
                ('Open a config…', self._config, 'Open a saved study (a .toml config)'),
                ('Open a results folder…', self._results, "A run's output folder: its results in the pages")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            if not self.buttons:                                    # the first: what most begin with
                b.setDefault(True)
                b.setStyleSheet('QPushButton { font-weight: 600; padding: 6px 16px; }')
            else:
                b.setStyleSheet('QPushButton { padding: 6px 12px; }')
            row.addWidget(b)
            self.buttons[text] = b
        self.recent = QLabel()
        self.recent.setTextFormat(Qt.RichText)
        self.recent.linkActivated.connect(self._open_recent)
        row.addWidget(self.recent)
        self.find = QLineEdit()
        self.find.setPlaceholderText('Find an example…')
        self.find.setClearButtonEnabled(True)
        self.find.setFixedWidth(220)
        self.find.textChanged.connect(self.filter)
        row.addWidget(self.find)
        holder = QWidget()
        holder.setLayout(row)
        v.addWidget(holder)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName('start-inner')
        inner.setStyleSheet('QWidget#start-inner { background: palette(base); }')
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        sc.setWidget(inner)
        v.addWidget(sc, 1)
        self.tiles, self.groups, self.open_groups, self._thread = {}, [], set(), None
        self.none = QLabel('no example matches')
        self.none.setStyleSheet('color: gray')
        self.set_examples(self._index() if entries is None else entries)
        self.refresh_recent()

    @staticmethod
    def _index():
        try:
            from kicad2ems.api.frontend import example_index
            return example_index()
        except Exception:                                           # noqa: BLE001 (a plugin's fault: no examples)
            return []

    # ---- the examples ----
    def set_examples(self, entries):
        """The tiles, by the examples' top group, in the index's order."""
        while self.body.count():
            it = self.body.takeAt(0)
            if it.widget() is not None and it.widget() is not self.none:
                it.widget().deleteLater()
        self.tiles, self.groups = {}, []
        by = {}
        for e in entries:
            by.setdefault((e.get('group') or 'Other').split('/')[0].strip(), []).append(e)
        for group, es in by.items():
            head = QLabel()
            head.setTextFormat(Qt.RichText)
            head.linkActivated.connect(lambda _href, g=group: self.toggle(g))
            self.body.addWidget(head)
            box = QWidget()
            flow = FlowLayout()
            flow.setSpacing(12)
            box.setLayout(flow)
            box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            tiles = []
            for e in es:
                t = Tile(e)
                t.clicked.connect(self._open_example)
                flow.addWidget(t)
                tiles.append(t)
                self.tiles[e['name']] = t
            self.body.addWidget(box)
            self.groups.append((group, head, box, tiles))
        self.body.addWidget(self.none)
        self.body.addStretch(1)
        self.filter(self.find.text())

    def toggle(self, group):
        """All of a group's tiles, or its first few."""
        (self.open_groups.discard if group in self.open_groups else self.open_groups.add)(group)
        self.filter(self.find.text())

    def filter(self, text=''):
        """The tiles that have every word of `text` in their name, title or group; none typed: each group's first
        few, or all of one that was opened."""
        words = text.lower().split()
        shown = 0
        for group, head, box, tiles in self.groups:
            match = [t for t in tiles if all(w in t.words for w in words)]
            keep = match if (words or group in self.open_groups) else match[:FIRST]
            for t in tiles:
                t.setVisible(t in keep)
            more = len(match) > len(keep) or group in self.open_groups
            head.setText(f"<span style='font-size:14px; font-weight:600'>{group}</span><span style='color:gray'>&nbsp;&nbsp;"
                         f"{len(match)} example{'s' if len(match) != 1 else ''}"
                         + (f" · <a href='#'>{'fewer' if group in self.open_groups else 'all'}</a>" if more and not words else '')
                         + "</span>")
            head.setVisible(bool(match))
            box.setVisible(bool(match))
            shown += len(match)
        self.none.setVisible(not shown)

    def visible_tiles(self):
        return [n for n, t in self.tiles.items() if not t.isHidden()]

    def start_pictures(self):
        """The tiles' pictures, drawn in a thread (once: they are kept in the cache folder)."""
        if self._thread is not None or not self.tiles:
            return
        try:
            from kicad2ems import __version__ as version
        except Exception:                                           # noqa: BLE001
            version = '0'
        self._thread = _Thumbs([t.entry for t in self.tiles.values()], version)
        self._thread.done.connect(lambda name, png: name in self.tiles and self.tiles[name].set_picture(png))
        self._thread.start()

    def stop_pictures(self):
        if self._thread is not None and self._thread.isRunning():
            self._thread.stop = True
            self._thread.wait(20000)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.refresh_recent()
        self.start_pictures()

    # ---- what the buttons do: the window's own actions ----
    def refresh_recent(self):
        paths = self.win.recent()[:RECENT] if self.win is not None and hasattr(self.win, 'recent') else []
        self._recent = paths
        self.recent.setText("<span style='color:gray'>Recent:</span>&nbsp; " + ' &nbsp;·&nbsp; '.join(
            f"<a href='{i}'>{os.path.basename(p)}</a>" for i, p in enumerate(paths)) if paths else '')
        self.recent.setToolTip('\n'.join(paths))

    def _open_recent(self, href):
        if self.win is not None and href.isdigit() and int(href) < len(self._recent):
            self.win._open(self._recent[int(href)])

    def _open_example(self, name):
        if self.win is not None:
            self.win.open_example(name)

    def _board(self):
        if self.win is not None:
            self.win.setup._browse('board', False)

    def _config(self):
        if self.win is not None:
            self.win.setup.load()

    def _results(self):
        if self.win is not None:
            self.win.results._load()
