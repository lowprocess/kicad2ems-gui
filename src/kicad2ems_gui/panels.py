"""
GUI building blocks: a collapsible settings section, an image panel (model, mesh, line model, convergence plots), a
row of controls that wraps when narrow.
"""
import os
from PySide6.QtCore import Qt, QRect, QPoint, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QToolButton, QLabel, QScrollArea, QSizePolicy,
                               QFrame, QLayout)


class Section(QWidget):
    """A titled group that folds open and closed: a header (arrow, title, how many of its settings are set) and
    the content widget. Collapsed when made."""
    def __init__(self, title, content, expanded=False, extra=None):
        """extra: a widget at the right of the header (a help button)."""
        super().__init__()
        self.title = title
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.head = QToolButton()
        self.head.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.head.setCheckable(True)
        self.head.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.head.setStyleSheet('QToolButton { border: none; font-weight: bold; padding: 4px; text-align: left; }')
        self.head.toggled.connect(self.set_expanded)
        if extra is None:
            lay.addWidget(self.head)
        else:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 4, 0)
            row.addWidget(self.head, 1)
            row.addWidget(extra)
            lay.addLayout(row)
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(8, 4, 4, 6)
        fl.addWidget(content)
        self.body = frame
        lay.addWidget(frame)
        self.set_count(0)
        self.head.setChecked(expanded)
        self.set_expanded(expanded)

    def set_expanded(self, on):
        self.head.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.body.setVisible(on)
        if self.head.isChecked() != on:
            self.head.setChecked(on)

    @property
    def expanded(self):
        return self.head.isChecked()

    def set_count(self, n):
        """n: how many settings of the section differ from their defaults (shown in the header)."""
        self.head.setText(f"{self.title}" + (f"  ({n} set)" if n else ''))


class ImagePanel(QWidget):
    """Plots written by a run (PNG), stacked and scaled to the panel's width; a note when there are none."""
    def __init__(self, empty='nothing yet'):
        super().__init__()
        self.paths, self.empty = [], empty
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.inner = QVBoxLayout()
        w = QWidget()
        w.setLayout(self.inner)
        scroll = QScrollArea()
        scroll.setWidget(w)
        scroll.setWidgetResizable(True)
        lay.addWidget(scroll)
        self.show_images([])

    def show_images(self, paths):
        self.paths = [p for p in paths if p and os.path.exists(p)]
        while self.inner.count():
            it = self.inner.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not self.paths:
            note = QLabel(self.empty)
            note.setStyleSheet('color: gray')
            self.inner.addWidget(note)
        for p in self.paths:
            lab = QLabel()
            pm = QPixmap(p)
            lab.setPixmap(pm.scaledToWidth(min(pm.width(), 1400), Qt.SmoothTransformation))
            lab.setToolTip(p)
            self.inner.addWidget(lab)
        self.inner.addStretch(1)


class FlowLayout(QLayout):
    """A row of controls that wraps onto more lines when the panel is narrow (Qt's flow layout example). A drop-in
    for a QHBoxLayout of controls: addWidget takes (and ignores) a stretch, addStretch / addSpacing do nothing."""
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items, self._sp = [], spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def addWidget(self, w, stretch=0, alignment=None):
        super().addWidget(w)

    def addStretch(self, *_):
        pass

    def addSpacing(self, *_):
        pass

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, False)

    def sizeHint(self):
        w = sum(it.sizeHint().width() + self._sp for it in self._visible())
        h = max([it.sizeHint().height() for it in self._visible()] or [0])
        return QSize(w, h)

    def minimumSize(self):
        s = QSize()
        for it in self._visible():
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _visible(self):
        return [it for it in self._items if not (it.widget() and it.widget().isHidden())]

    def _place(self, rect, test):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line = r.x(), r.y(), 0
        for it in self._visible():
            hint = it.sizeHint()
            nxt = x + hint.width() + self._sp
            if nxt - self._sp > r.right() and line > 0:
                x, y, line = r.x(), y + line + self._sp, 0
                nxt = x + hint.width() + self._sp
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x, line = nxt, max(line, hint.height())
        return y + line - rect.y() + m.bottom()
