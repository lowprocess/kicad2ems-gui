"""
The plots' colours (R-E25): light or dark. 'system' (the default) follows the desktop's colour scheme (Qt's style
hints, else the palette's window colour) and changes with it; 'light' and 'dark' hold whatever the desktop does. The
window's View menu sets it (QSettings 'view/plots').

    theme.set_choice('dark')        # every plot restyled now; new plots take it as they are made
    c = theme.colors()              # dict: bg, fg, grid, marker, fill (a label's backing, RGBA)

A plot widget whose own items carry colours (markers, a cursor's dot) has a restyle() method, which apply() calls.
"""
CHOICES = ('system', 'light', 'dark')
LIGHT = dict(bg='#ffffff', fg='#000000', grid='#cccccc', marker='#444444', fill=(255, 255, 255, 200), name='light')
DARK = dict(bg='#1e1f22', fg='#dcdcdc', grid='#4a4c50', marker='#bbbbbb', fill=(30, 31, 34, 200), name='dark')
_choice = 'system'
_watching = False


def system_dark():
    """Is the desktop's colour scheme dark? (Qt 6.5's style hints; else the palette's window colour.)"""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
    except ImportError:                                             # pragma: no cover
        return False
    app = QGuiApplication.instance()
    if app is None:
        return False
    try:
        cs = app.styleHints().colorScheme()
        if cs == Qt.ColorScheme.Dark:
            return True
        if cs == Qt.ColorScheme.Light:
            return False
    except AttributeError:
        pass
    return app.palette().window().color().lightness() < 128


def choice():
    return _choice


def dark():
    return _choice == 'dark' or (_choice == 'system' and system_dark())


def colors():
    return DARK if dark() else LIGHT


def set_choice(c):
    """'system', 'light' or 'dark' (anything else: 'system'), then apply()."""
    global _choice
    _choice = c if c in CHOICES else 'system'
    apply()


def restyle(w, c=None):
    """One pyqtgraph PlotWidget in colours c (default: the theme's): background, axes, title, legend."""
    c = c or colors()
    w.setBackground(c['bg'])
    try:
        pi = w.getPlotItem()
    except AttributeError:
        return
    for ax in pi.axes.values():
        item = ax['item']
        item.setPen(c['fg'])
        item.setTextPen(c['fg'])
    t = pi.titleLabel
    if t.text:
        t.setText(t.text, color=c['fg'])
    lg = pi.legend
    if lg is not None:
        lg.setLabelTextColor(c['fg'])
        for _, label in lg.items:
            label.setText(label.text, color=c['fg'])


def apply():
    """The theme's colours as pyqtgraph's defaults (for plots still to come), on every plot widget open and to
    each widget with a restyle() of its own; and, once there is an application, follow the desktop's scheme."""
    import pyqtgraph as pg
    c = colors()
    pg.setConfigOptions(background=c['bg'], foreground=c['fg'])
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:                                             # pragma: no cover
        return c
    app = QApplication.instance()
    if app is None:
        return c
    _watch(app)
    for w in app.allWidgets():
        if isinstance(w, pg.PlotWidget):
            restyle(w, c)
        own = getattr(w, 'restyle', None)
        if callable(own) and not isinstance(w, pg.PlotWidget):
            own()
    return c


def _watch(app):
    """Restyle when the desktop's colour scheme changes (only what 'system' follows)."""
    global _watching
    if _watching:
        return
    _watching = True
    try:
        app.styleHints().colorSchemeChanged.connect(lambda *_: _choice == 'system' and apply())
    except AttributeError:                                          # Qt before 6.5
        pass
