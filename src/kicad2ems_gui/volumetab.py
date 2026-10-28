"""
The 3D field panel: a volume dump as a translucent voxel cloud over the board (copper, vias, the board's box),
in an OpenGL view you orbit (drag), zoom (wheel) and pan (middle drag, or Ctrl + drag). A frequency-domain dump
plays one period of Re(F e^jphi), a time-domain one its frames; *Save GIF / MP4* writes the animation as seen
from the current camera. Needs PyOpenGL (pip install PyOpenGL; the gui extra has it).
"""
import os
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QFormLayout, QComboBox, QCheckBox, QSlider,
                               QPushButton, QLabel, QDoubleSpinBox, QFileDialog, QMessageBox, QSpinBox)

from . import volume3d as v3

N_PHASE = 24


def gl_module():
    """pyqtgraph.opengl, or None (and why) when PyOpenGL is missing."""
    try:
        import pyqtgraph.opengl as gl
        return gl, ''
    except Exception as e:                                          # ImportError: no PyOpenGL
        return None, f"{type(e).__name__}: {e}"


_COPPER_SHADER = None


def copper_shader():
    """A shader for the copper slabs: pyqtgraph's 'shaded' inputs, brighter: ambient 0.5, a key light from the upper
    front of the view (two-sided: a wall seen from inside the slab is lit too) and a small highlight, so the top
    faces stay copper-coloured and the walls and edges shade as the view turns."""
    global _COPPER_SHADER
    if _COPPER_SHADER is None:
        from pyqtgraph.opengl import shaders as S
        _COPPER_SHADER = S.ShaderProgram('kicad2ems_copper', [S.VertexShader("""
            uniform mat4 u_mvp;
            uniform mat3 u_normal;
            attribute vec4 a_position;
            attribute vec3 a_normal;
            attribute vec4 a_color;
            varying vec4 v_color;
            varying vec3 v_normal;
            void main() {
                v_normal = normalize(u_normal * a_normal);
                v_color = a_color;
                gl_Position = u_mvp * a_position;
            }
        """), S.FragmentShader("""
            #ifdef GL_ES
            precision mediump float;
            #endif
            varying vec4 v_color;
            varying vec3 v_normal;
            void main() {
                vec3 n = normalize(v_normal);
                vec3 l = normalize(vec3(-0.35, 0.55, 1.0));
                float d = abs(dot(n, l));
                float s = pow(max(dot(reflect(-l, n), vec3(0.0, 0.0, 1.0)), 0.0), 24.0);
                vec3 rgb = v_color.rgb * (0.5 + 0.55 * d) + vec3(0.25) * s;
                gl_FragColor = vec4(min(rgb, vec3(1.0)), v_color.a);
            }
        """)])
    return _COPPER_SHADER


def _view_class(gl):
    """GLViewWidget that reports each new OpenGL context (after the first paint is set up)."""
    class View(gl.GLViewWidget):
        on_init = None

        def initializeGL(self):
            super().initializeGL()
            if self.on_init is not None:
                QTimer.singleShot(0, self.on_init)
    return View


class FrameSlider(QWidget):
    """The frame (a time step or a frequency) as a slider with the frame's label beside it; the methods of the
    QComboBox it replaced (currentIndex, setCurrentIndex, addItems, clear, count, currentIndexChanged)."""
    from PySide6.QtCore import Signal
    currentIndexChanged = Signal(int)

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.label = QLabel('')
        self.label.setMinimumWidth(90)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self.labels = []
        self.slider.valueChanged.connect(self._moved)

    def _moved(self, i):
        self.label.setText(self.labels[i] if 0 <= i < len(self.labels) else '')
        if not self.signalsBlocked():
            self.currentIndexChanged.emit(i)

    def clear(self):
        self.labels = []
        self.slider.blockSignals(True)
        self.slider.setRange(0, 0)
        self.slider.blockSignals(False)
        self.label.setText('')

    def addItems(self, labels):
        self.labels += list(labels)
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, len(self.labels) - 1))
        self.slider.blockSignals(False)
        self._moved(self.slider.value()) if not self.signalsBlocked() else self.label.setText(
            self.labels[self.slider.value()] if self.labels else '')
        self.slider.setEnabled(len(self.labels) > 1)

    def count(self):
        return len(self.labels)

    def currentText(self):
        i = self.currentIndex()
        return self.labels[i] if i >= 0 else ''

    def currentIndex(self):
        return self.slider.value() if self.labels else -1

    def setCurrentIndex(self, i):
        if not self.labels:
            return
        i = max(0, min(int(i), len(self.labels) - 1))
        if i == self.slider.value():
            self.label.setText(self.labels[i])
            return
        self.slider.blockSignals(self.signalsBlocked())
        self.slider.setValue(i)
        self.slider.blockSignals(False)
        self.label.setText(self.labels[i])



class VolumeTab(QWidget):
    def __init__(self, win=None):
        super().__init__()
        self.win, self.srcs, self.src, self.vol, self.items = win, [], None, None, {}
        self.board, self.mesh_files = None, {}                      # <name>_board.json's geometry; meshes.find()
        self.ant = None                                             # (antenna results, sphere) of the folder
        self._frames, self._key, self.k = [], None, 0
        self.lines, self.sel = None, None                           # the line model (overlay.load_lines), a section
        lay = QHBoxLayout(self)
        self.gl, why = gl_module()
        if self.gl is None:
            note = QLabel(f"The 3D field view needs PyOpenGL: pip install PyOpenGL (into the Python of the GUI)\n({why})")
            note.setAlignment(Qt.AlignCenter)
            note.setStyleSheet('color: gray')
            lay.addWidget(note)
            return
        side = QVBoxLayout()
        self.dump = QComboBox()
        self.frame = FrameSlider()
        self.comp = QComboBox()
        self.comp.addItems(['|F|', 'Fx', 'Fy', 'Fz'])
        self.cmap = QComboBox()
        self.cmap.addItems(['turbo', 'inferno', 'plasma', 'viridis', 'hot'])
        self.envelope = QCheckBox('envelope (no animation)')
        self.whole = QCheckBox('one colour range for every frame')
        self.whole.setToolTip("the colour range over the whole dump (every time step, or every frequency), so a "
                              "field that grows and decays shows it; off: each frame its own range (a frequency "
                              "domain dump's period always shares one)")
        self._ranges = {}                                           # (dump, settings) -> the whole dump's top
        self.log = QCheckBox('log scale')
        self.log.setChecked(True)
        self.decades = QDoubleSpinBox()
        self.decades.setRange(0.5, 5)
        self.decades.setSingleStep(0.5)
        self.decades.setValue(1.5)
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(80)
        self.gamma = QSlider(Qt.Horizontal)
        self.gamma.setRange(5, 40)                                  # gamma x 10
        self.gamma.setValue(12)
        self.zscale = QDoubleSpinBox()
        self.zscale.setRange(1, 20)
        self.zscale.setValue(2)
        self.zscale.setSuffix(' x')
        self.clip = QDoubleSpinBox()
        self.clip.setRange(90, 100)
        self.clip.setDecimals(2)
        self.clip.setSingleStep(0.1)
        self.clip.setValue(99.5)
        self.clip.setSuffix(' %')
        self.clip.setToolTip('the top of the colour range: this percentile of the values (a port gap takes it all at 100 %)')
        self.res = QSpinBox()
        self.res.setRange(48, 256)
        self.res.setValue(128)
        self.res.setSuffix(' voxels')
        self.copper = QCheckBox('copper')
        self.copper.setChecked(True)
        self.cu_t = QDoubleSpinBox()
        self.cu_t.setRange(0, 5)
        self.cu_t.setDecimals(2)
        self.cu_t.setSingleStep(0.05)
        self.cu_t.setSpecialValueText('flat')
        self.cu_t.setSuffix(' mm')
        self.cu_t.setToolTip('the copper drawn as shaded slabs this thick (on screen; real copper is ~35 um): '
                             'its edges catch the light; 0: flat, unshaded')
        self._cu_t_auto = True
        self.boxc = QCheckBox('board box and vias')
        self.boxc.setChecked(True)
        self.mesh = QComboBox()
        self.far = QComboBox()
        self.far.setToolTip("the far-field gain pattern (antenna mode) at a recorded frequency, over the board: "
                            "its distance from the board's centre is the gain, 30 dB of range")
        self.far_size = QDoubleSpinBox()
        self.far_size.setRange(0.2, 5)
        self.far_size.setSingleStep(0.1)
        self.far_size.setValue(0.5)
        self.far_size.setSuffix(' x board')
        self.far_up = QDoubleSpinBox()
        self.far_up.setRange(-500, 500)
        self.far_up.setSingleStep(1)
        self.far_up.setSuffix(' mm')
        self.far_up.setToolTip("how far above the board's top surface the pattern's centre is drawn (on screen)")
        from .steering import SteeringBar
        self.steer = SteeringBar(compact=True)                      # the Results page's, linked (app.py)
        self.steer.steered.connect(lambda *_: self._far_on())
        self.mesh.setToolTip("a solver's discretisation of the board (written by a preview or a run): openEMS's "
                             "grid lines, mom25d's triangles")
        # the controls: one folding section per subject, shown when the folder has something for it (a field
        # dump, a far field), in a side panel the splitter can narrow or close
        from .panels import Section
        self.play_btn = QPushButton('Play')
        self.play_btn.setCheckable(True)
        self.play_btn.toggled.connect(self._play)
        self.fps = QSpinBox()                                       # as the Cut view's
        self.fps.setRange(1, 60)
        self.fps.setValue(12)
        self.fps.setToolTip('frames per second of Play and of saved animations')
        self.fps.valueChanged.connect(lambda v: self.timer.setInterval(int(1000 / v)))
        self.every = QSpinBox()
        self.every.setRange(1, 1000)
        self.every.setToolTip('Time domain: every n-th time step, for Play and saved animations (set for a long '
                              'dump to about 120 frames)')
        saves = QHBoxLayout()
        for ext in ('gif', 'mp4'):
            b = QPushButton(f"Save {ext.upper()}")
            b.clicked.connect(lambda _=False, e=ext: self.save_dialog(e))
            saves.addWidget(b)
        self.lines_on = QCheckBox('line model (coloured by Z0)')
        self.lines_on.setChecked(True)
        self.lines_on.setToolTip("the line model's sections on their layers; pick one in the section list")
        self.lines_on.toggled.connect(lambda *_: self._board())
        self.relief = QDoubleSpinBox()
        self.relief.setRange(0, 20)
        self.relief.setDecimals(2)
        self.relief.setSingleStep(0.1)
        self.relief.setSuffix(' mm')
        self.relief.setSpecialValueText('flat')
        self.relief.setToolTip("the line model's tallest section on screen (the highest Z0); the lowest Z0 stands a "
                               "quarter as high, so each step in height is a step in impedance. 0: flat")
        self.relief.valueChanged.connect(self._relief_set)
        self._relief_auto = True
        self.parts_on = QCheckBox('parts at true size (R / C / L)')
        self.parts_on.setChecked(True)
        self.parts_on.setToolTip('lumped parts as their chips (0201, 0402, 0603, ... from the footprint name): '
                                 'resistors green, capacitors cyan, inductors pink, with their value')
        self.parts_on.toggled.connect(lambda *_: self._board())
        groups = (('Field', True, (('Dump', self.dump), ('Frame', self.frame), ('Show', self.comp),
                                   ('Colours', self.cmap), ('', self.envelope), ('', self.whole), ('', self.log),
                                   ('Decades', self.decades), ('Range top', self.clip), ('Opacity', self.opacity),
                                   ('Fade (gamma)', self.gamma), ('Resolution', self.res), ('fps', self.fps),
                                   ('Every n-th frame', self.every), ('', self.play_btn),
                                   ('', saves))),
                  ('Board', True, (('Height scale', self.zscale), ('', self.copper), ('Copper shown', self.cu_t),
                                   ('', self.boxc), ('Mesh', self.mesh), ('', self.lines_on),
                                   ('Z0 relief', self.relief), ('', self.parts_on))),
                  ('Far field', True, (('Pattern', self.far), ('Size', self.far_size), ('Height', self.far_up),
                                       ('', self.steer))))
        self.sections = {}
        for title, open_, rows in groups:
            box = QWidget()
            f = QFormLayout(box)
            f.setContentsMargins(0, 0, 0, 0)
            f.setRowWrapPolicy(QFormLayout.WrapLongRows)
            f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            for label, w in rows:
                f.addRow(label, w)
            self.sections[title] = Section(title, box, expanded=open_)
            side.addWidget(self.sections[title])
        reset = QPushButton('Reset view')
        reset.clicked.connect(self.reset_camera)
        side.insertWidget(0, reset)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color: gray')
        side.addWidget(self.status)
        side.addStretch(1)
        sw = QWidget()
        sw.setLayout(side)
        from PySide6.QtWidgets import QScrollArea, QSplitter
        scroll = QScrollArea()
        scroll.setWidget(sw)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(200)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view = _view_class(self.gl)()
        self.view.on_init = self._new_context
        self.view.setBackgroundColor('w')
        self.split = QSplitter()
        self.split.setObjectName('viewer3d')
        self.split.addWidget(scroll)
        self.split.addWidget(self.view)
        self.split.setStretchFactor(1, 1)
        self.split.setCollapsible(1, False)
        self.split.setSizes([270, 900])
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.split)
        self._fit_sections()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.dump.currentIndexChanged.connect(self._pick)
        self.frame.currentIndexChanged.connect(self._rebuild)
        self.res.valueChanged.connect(self._rebuild)
        for w in (self.comp, self.cmap):
            w.currentIndexChanged.connect(self._recolour)
        for w in (self.envelope, self.whole, self.log, self.copper, self.boxc):
            w.toggled.connect(self._recolour)
        self.cu_t.valueChanged.connect(self._cu_t_set)
        self.mesh.currentIndexChanged.connect(lambda *_: self._board())
        self.far.currentIndexChanged.connect(lambda *_: (self._board(), self.reset_camera()))
        self.far_size.valueChanged.connect(lambda *_: self._board())
        self.far_up.valueChanged.connect(lambda *_: (self._board(), self.reset_camera()))
        for w in (self.decades, self.zscale, self.clip):
            w.valueChanged.connect(self._recolour)
        for w in (self.opacity, self.gamma):
            w.valueChanged.connect(self._recolour)

    def _new_context(self):
        """The view has a new OpenGL context (first shown, or moved: a dock tabbed, floated or docked again, which
        re-creates it): items made in the old one hold its shaders and buffers, so make them anew."""
        for it in list(self.view.items):
            self.view.removeItem(it)
        self.items = {}
        if self._frames:
            self._show(self.k)
            self._board()

    @property
    def geometry(self):
        """The board drawn: the dump's geometry, else the folder's <name>_board.json."""
        return self.src.geometry if self.src is not None else self.board

    # ---- data ----
    def load(self, out_dir):
        """A results folder: its volume dumps, its board and the solvers' meshes (a preview writes those). False:
        nothing to show, or no OpenGL."""
        if self.gl is None:
            return False
        import glob
        from kicad2ems.fields.frames import find_dumps
        from kicad2ems import meshes
        self.srcs = [s for s in find_dumps(out_dir) if v3.is_volume(s) or v3.is_plane(s)]
        boards = sorted(glob.glob(os.path.join(out_dir, '*_board.json')), key=os.path.getmtime)
        try:
            self.board = v3.geometry_from_board(boards[-1]) if boards else None
        except (OSError, ValueError, KeyError):
            self.board = None
        self.mesh_files = meshes.find(out_dir)
        self._load_far(out_dir)
        keep = self.mesh.currentData()
        self.mesh.blockSignals(True)
        self.mesh.clear()
        self.mesh.addItem('none', None)
        for solver, path in self.mesh_files.items():
            self.mesh.addItem(f"{meshes.LABELS.get(solver, solver)}: {meshes.counts(path)}", solver)
        i = self.mesh.findData(keep)
        self.mesh.setCurrentIndex(max(i, 0))
        self.mesh.blockSignals(False)
        self.dump.blockSignals(True)
        self.dump.clear()
        self.dump.addItems([s.label for s in self.srcs])
        self.dump.blockSignals(False)
        if self.srcs:
            self._pick()
        else:                                                       # the board alone, and its meshes
            self.src, self.vol, self._frames = None, None, []
            for key in list(self.items):
                self.view.removeItem(self.items.pop(key))
            self._auto_cu_t()
            self._board()
            self.reset_camera()
            self.status.setText('no volume dumps: the board' + (' and the solvers\' meshes' if self.mesh_files else ''))
        self._fit_sections()
        return bool(self.srcs or (self.board and (self.mesh_files or self.ant or self.lines)))

    def _load_far(self, out_dir):
        """The folder's far-field pattern (its newest antenna result with a sphere) into the Far field choice."""
        from .antennatab import find_antenna, load_sphere
        self.ant = None
        try:
            found = find_antenna(out_dir)
            if found and found[1]:
                self.ant = (found[0], load_sphere(found[1]))
        except Exception:                                           # a half-written or missing file: no pattern
            self.ant = None
        self.far.blockSignals(True)
        self.far.clear()
        self.far.addItem('off', None)
        if self.ant is not None:
            for i, f in enumerate(self.ant[1]['freq']):
                self.far.addItem(f"gain at {f / 1e9:.4g} GHz", i)
        self.far.blockSignals(False)

    def _pick(self, *_):
        i = self.dump.currentIndex()
        if i < 0 or i >= len(self.srcs):
            return
        self.src = self.srcs[i].refresh()
        self.frame.blockSignals(True)
        self.frame.clear()
        self.frame.addItems([self.src.frame_label(k) for k in range(len(self.src))])
        self.frame.setCurrentIndex(0 if self.src.domain == 'FD' else max(0, len(self.src) - 1))
        self.frame.blockSignals(False)
        self.envelope.setEnabled(self.src.domain == 'FD')
        n, fd = len(self.src), self.src.domain == 'FD'             # as the Cut view: a long dump about 120 frames
        self.every.setEnabled(not fd)
        if fd:
            self.every.setValue(1)
        elif n > 200 and self.every.value() == 1:
            self.every.setValue(max(1, n // 120))
        self._auto_cu_t()
        self._board()
        self._rebuild()
        self.reset_camera()

    def _rebuild(self, *_):
        if self.src is None or self.frame.currentIndex() < 0:
            return
        self.vol = v3.Volume(self.src, self.frame.currentIndex(), n=self.res.value())
        self._recolour()

    def _component(self):
        return v3.COMPONENTS[self.comp.currentIndex()]

    def _phases(self):
        """The animation's frames: phases (frequency domain), else None (one frame)."""
        if self.src.domain == 'FD' and not self.envelope.isChecked():
            return list(np.linspace(0, 2 * np.pi, N_PHASE, endpoint=False))
        return [None]

    def _whole_top(self, comp, phases):
        """The top of the colour range over every frame of the dump (each frame's `Range top` percentile, the
        largest), at the current resolution; kept per dump and settings."""
        from PySide6.QtWidgets import QApplication
        key = (self.src.path, self.src.name, comp, len(phases), self.clip.value(), self.res.value())
        if key not in self._ranges:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                tops = []
                for k in range(len(self.src)):
                    vol = self.vol if k == self.frame.currentIndex() else v3.Volume(self.src, k, n=self.res.value())
                    tops.append(v3.levels([vol.scalar(comp, p) for p in phases], True, False,
                                          clip=self.clip.value())[1])
                self._ranges[key] = max(tops)
            finally:
                QApplication.restoreOverrideCursor()
        return self._ranges[key]

    def _recolour(self, *_):
        """The voxels of every animation frame at the current settings (one colour range for all)."""
        if self.vol is None:
            return
        comp, phases = self._component(), self._phases()
        vals = [self.vol.scalar(comp, p) for p in phases]
        signed = self.vol.signed(comp, phases[0])
        log = self.log.isChecked() and not signed
        lo, hi = v3.levels(vals, signed, log, self.decades.value(), self.clip.value())
        whole = self.whole.isChecked() and len(self.src) > 1
        if whole:                                                   # the top over every frame of the dump
            top = self._whole_top(comp, phases)
            lo, hi = (-top, top) if signed else ((top * 10 ** -self.decades.value(), top) if log else (0.0, top))
        cmap = self.cmap.currentText() if not signed else None          # a signed component: blue - white - red
        self._frames = [v3.colour(v, lo, hi, log, signed, self.opacity.value() / 100, self.gamma.value() / 10, cmap)
                        for v in vals]
        self.k %= len(self._frames)
        self._show(self.k)
        what = f"|{self.src.field}|" if comp == 'mag' else f"{self.src.field}{comp}"
        self.status.setText(f"{what}: {lo:.3g} to {hi:.3g} {self.src.unit}" + (' (log)' if log else '')
                            + (' over every frame' if whole else '')
                            + f"; grid {' x '.join(map(str, self.vol.data.shape[:3]))}; drag to orbit, wheel to zoom, "
                              f"Ctrl + drag to pan")
        self._board()

    def _show(self, k):
        gl, zs = self.gl, self.zscale.value()
        rgba = self._frames[k]
        if self.vol.plane is not None:                              # a plane dump: an image in place
            self._show_plane(rgba)
            return
        it = self.items.get('vol')
        if it is not None and not isinstance(it, gl.GLVolumeItem):    # was a plane's image
            self.view.removeItem(self.items.pop('vol'))
            it = None
        if it is None:
            it = gl.GLVolumeItem(rgba, sliceDensity=2, smooth=True, glOptions='translucent')
            it.setDepthValue(10)                                    # last: its slices would hide the board
            self.view.addItem(it)
            self.items['vol'] = it
        else:
            it.setData(rgba)
        it.resetTransform()
        it.scale(self.vol.step[0], self.vol.step[1], self.vol.step[2] * zs)
        o = self.vol.origin - 0.5 * self.vol.step                  # voxel k spans k..k+1: its centre on sample k
        it.translate(o[0], o[1], o[2] * zs)

    def _show_plane(self, rgba):
        """A plane dump's frame as an image at its position (normal x, y or z), at the height scale."""
        from PySide6.QtGui import QMatrix4x4
        gl, zs, n = self.gl, self.zscale.value(), self.vol.plane
        a, b = [k for k in range(3) if k != n]
        img = np.ascontiguousarray(np.take(rgba, 0, axis=n))         # (n_a, n_b, 4)
        it = self.items.get('vol')
        if it is None or not isinstance(it, gl.GLImageItem):
            if it is not None:
                self.view.removeItem(it)
            it = gl.GLImageItem(img, glOptions='translucent')
            it.setDepthValue(10)
            self.view.addItem(it)
            self.items['vol'] = it
        else:
            it.setData(img)
        sc = np.array([1.0, 1.0, zs])
        eu, ev = np.zeros(3), np.zeros(3)
        eu[a], ev[b] = self.vol.step[a] * sc[a], self.vol.step[b] * sc[b]
        en = np.zeros(3)
        en[n] = 1.0
        o = self.vol.origin * sc - 0.5 * (eu + ev)                 # pixel k spans k..k+1: its centre on sample k
        cu = (self.geometry or {}).get('cu_z') or {}
        layer = (getattr(self.src, 'meta', None) or {}).get('label')
        z = cu.get(layer) if n == 2 else None                       # a layer dump (E@F.Cu): at its copper layer;
        if z is None and n == 2:                                    # openEMS samples it a cell into the dielectric
            z = next((c for c in cu.values() if abs(self.vol.origin[2] - c) < 1e-3), None)
        if z is not None:                                           # on top of what is drawn on its layer:
            top = 0.5 * self.cu_t.value() if self.copper.isChecked() else 0.0          # the copper's slab,
            if self.lines and self.lines_on.isChecked() and any(                       # the line model's slabs
                    e.get('z') is not None and abs(e['z'] - z) < 1e-3 and e.get('kind') != 'coupling'
                    for e in self.lines.get('elements', [])):
                top += 0.005 + max(self.relief.value(), 0.01)
            o[2] = z * zs + top + 0.01
        it.setTransform(QMatrix4x4(eu[0], ev[0], en[0], o[0], eu[1], ev[1], en[1], o[1],
                                   eu[2], ev[2], en[2], o[2], 0, 0, 0, 1))

    def _far_on(self):
        """Steering from this view with no pattern shown: the pattern frequency's."""
        if self.far.currentData() is None and self.ant is not None and self.far.count() > 1:
            f0 = self.ant[0].get('f_pattern', self.ant[1]['freq'][0])
            self.far.setCurrentIndex(1 + int(np.argmin(np.abs(np.asarray(self.ant[1]['freq']) - f0))))

    def set_far(self, res, sph):
        """A new pattern of the folder's antenna (a steered drive): only the far field redrawn."""
        if self.gl is None or self.ant is None or len(sph['freq']) != len(self.ant[1]['freq']):
            return
        self.ant = (res, sph)
        if 'far' in self.items:
            self.view.removeItem(self.items.pop('far'))
        if self.geometry is not None:
            self._far_field(self.geometry, self.zscale.value())

    def _far_field(self, g, zs):
        """The far-field pattern over the board's centre (`Far-field height` above its top), the peak `Far-field
        size` x the board's larger side away."""
        i = self.far.currentData()
        if i is None or self.ant is None:
            return
        res, sph = self.ant
        b = v3.board_box(g)
        if b is None:
            return
        x0, y0, x1, y1, z0, z1 = b
        f = float(sph['freq'][i])
        row = min(res['rows'], key=lambda r: abs(r['f'] - f))
        v, faces, col, peak = v3.pattern_mesh(sph, i, row['eff'], (0.5 * (x0 + x1), 0.5 * (y0 + y1),
                                                                   z1 * zs + self.far_up.value()),
                                              self.far_size.value() * max(x1 - x0, y1 - y0))
        col[:, 3] = 1.0                                             # opaque: a translucent surface sorts badly
        m = self.gl.GLMeshItem(vertexes=v.astype(np.float32), faces=faces.astype(np.uint32),
                               vertexColors=col.astype(np.float32), smooth=True, glOptions='opaque')
        m.setDepthValue(5)
        self.view.addItem(m)
        self.items['far'] = m
        self.status.setText(f"far field at {f / 1e9:.4g} GHz: peak gain {peak:.2f} dBi (30 dB of range); "
                            f"drag to orbit, wheel to zoom, Ctrl + drag to pan")

    def _board(self):
        """Copper (translucent orange), vias and the board's box, at the height scale."""
        gl, zs = self.gl, self.zscale.value()
        for key in [k for k in self.items if k != 'vol']:
            self.view.removeItem(self.items.pop(key))
        g = self.geometry
        if g is None:
            return
        if self.copper.isChecked():
            shown = self.cu_t.value()                               # on screen: the slab before the height scale
            t = shown / zs
            parts = v3.copper_solids(g, t) if shown > 0 else v3.copper_triangles(g)
            for i, (lay, z, verts, faces) in enumerate(parts):
                v = verts.copy()
                v[:, 2] *= zs
                if shown > 0:                                       # lit by the faces' angle to the view
                    md = gl.MeshData(vertexes=v.astype(np.float32), faces=faces.astype(np.uint32))
                    m = gl.GLMeshItem(meshdata=md, color=(0.85, 0.5, 0.2, 0.7), smooth=False, shader=copper_shader(),
                                      glOptions='translucent')
                else:
                    m = gl.GLMeshItem(vertexes=v.astype(np.float32), faces=faces.astype(np.uint32),
                                      color=(0.85, 0.5, 0.15, 0.55), smooth=False, glOptions='translucent')
                m.setDepthValue(-10 + i)
                self.view.addItem(m)
                self.items[f'cu{i}'] = m
            ol = v3.copper_outlines(g)                              # dark edges: the copper reads through the field
            if len(ol):
                ol = ol.copy()
                ol[:, 2] = (ol[:, 2] + 0.5 * t) * zs if shown > 0 else ol[:, 2] * zs   # on the slab's top
                ln = gl.GLLinePlotItem(pos=ol, mode='lines', color=(0.35, 0.18, 0.03, 1.0), width=1.5, antialias=True)
                ln.setDepthValue(-5)
                self.view.addItem(ln)
                self.items['outline'] = ln
        if self.boxc.isChecked():
            b = v3.board_box(g)
            if b is not None:
                x0, y0, x1, y1, z0, z1 = b
                c = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]])
                pts = []
                for z in (z0, z1):
                    pts += [np.column_stack([c, np.full(5, z * zs)])]
                edges = np.concatenate([np.repeat(pts[0], 2, 0)[1:-1], np.repeat(pts[1], 2, 0)[1:-1],
                                        np.stack([pts[0][:4], pts[1][:4]], 1).reshape(-1, 3)])
                ln = gl.GLLinePlotItem(pos=edges, mode='lines', color=(0.3, 0.3, 0.3, 0.8), width=1, antialias=True)
                ln.setDepthValue(-20)
                self.view.addItem(ln)
                self.items['box'] = ln
            vl = v3.via_lines(g)
            if len(vl):
                vl = vl.copy()
                vl[:, 2] *= zs
                ln = gl.GLLinePlotItem(pos=vl, mode='lines', color=(0.45, 0.3, 0.1, 1.0), width=2, antialias=True)
                ln.setDepthValue(-20)
                self.view.addItem(ln)
                self.items['vias'] = ln
        solver = self.mesh.currentData()
        if solver and solver in self.mesh_files:                    # a solver's mesh as lines over the board
            from kicad2ems import meshes
            b = v3.board_box(g)
            seg = meshes.segments(self.mesh_files[solver], box=b, planes=sorted(set((g.get('cu_z') or {}).values())))
            if len(seg):
                seg = seg.copy()
                seg[:, 2] *= zs
                colour = dict(openems=(0.1, 0.3, 0.7, 0.55), mom25d=(0.1, 0.5, 0.2, 0.7)).get(solver, (0.2, 0.2, 0.2, 0.6))
                ln = gl.GLLinePlotItem(pos=seg.astype(np.float32), mode='lines', color=colour, width=1, antialias=True)
                ln.setDepthValue(-1)
                self.view.addItem(ln)
                self.items['mesh'] = ln
        self._line_model(zs)
        self._parts(zs)
        self._far_field(g, zs)
        if self.vol is not None and self.vol.plane is not None and self._frames:     # a layer dump: on top of them
            self._show_plane(self._frames[self.k])

    def _line_model(self, zs):
        """The line model's sections as slabs at their copper width, standing on the copper, coloured by Z0 against
        the ports' impedance and as tall as their Z0 is high (overlay.relief: a quarter of `Z0 relief` at the
        model's lowest Z0, all of it at the highest), so every change of impedance is a step; dark rims on their
        tops; the selected one dark. All on screen: the height scale does not stretch them."""
        if not (self.lines and self.lines_on.isChecked()):
            return
        from kicad2ems import overlay as ov
        ref, half = ov.reference(self.lines), ov.span(self.lines)
        zs_all = [e['z0'] for e in self.lines['elements'] if e.get('z0') and e.get('kind') != 'coupling']
        lo, hi = (min(zs_all), max(zs_all)) if zs_all else (None, None)
        full = max(self.relief.value(), 0.01)                       # on screen, mm
        base = 0.5 * self.cu_t.value() if self.copper.isChecked() else 0.0
        chips = bool((self.board or {}).get('parts')) and self.parts_on.isChecked()
        rims = []
        for e in self.lines['elements']:
            if e.get('z') is None or not ov.drawn(e):
                continue
            if e.get('kind') == 'part' and chips:                   # the chip is drawn: no strip inside it
                continue
            g = ov.section_polygon(e)
            if g.is_empty:
                continue
            h = full * ov.relief(e.get('z0'), lo, hi)
            bottom = e['z'] * zs + base + 0.005                     # just above the copper's top: no z-fighting
            parts = [g] if g.geom_type == 'Polygon' else list(g.geoms)
            polys = [[list(p.exterior.coords)] + [list(r.coords) for r in p.interiors] for p in parts]
            solids = v3.copper_solids(dict(copper={'s': polys}, cu_z={'s': bottom + 0.5 * h}), h)
            if not solids:
                continue
            _, _, verts, faces = solids[0]
            sel = e['id'] == self.sel
            rgb = (0.12, 0.12, 0.12) if sel else ov.z0_colour(e.get('z0'), ref, half)
            md = self.gl.MeshData(vertexes=verts.astype(np.float32), faces=faces.astype(np.uint32))
            m = self.gl.GLMeshItem(meshdata=md, color=(*rgb, 1.0), smooth=False, shader=copper_shader(),
                                   glOptions='opaque')
            m.setDepthValue(2)
            self.view.addItem(m)
            self.items[f"ln{e['id']}"] = m
            for p in parts:                                         # the top's rim, as segment pairs
                r = np.asarray(p.exterior.coords)
                top = np.column_stack([r, np.full(len(r), bottom + h + 0.002)])
                rims.append(np.repeat(top, 2, 0)[1:-1])
        if rims:
            ln = self.gl.GLLinePlotItem(pos=np.concatenate(rims).astype(np.float32), mode='lines',
                                        color=(0.1, 0.1, 0.1, 0.9), width=1.2, antialias=True)
            ln.setDepthValue(3)
            self.view.addItem(ln)
            self.items['ln_rims'] = ln

    def _parts(self, zs):
        """The lumped parts as their chips (volume3d.part_solids): coloured body, metal end caps, a label."""
        parts = (self.board or {}).get('parts') or []
        if not (parts and self.parts_on.isChecked()):
            return
        g = self.board
        lift = 0.5 * self.cu_t.value() if self.copper.isChecked() else 0.0
        for k, p in enumerate(parts):
            made = v3.part_solids(p, g.get('cu_z') or {}, zs, lift)
            if made is None:
                continue
            solids, (lx, ly, lz) = made
            for j, (role, rgb, verts, faces) in enumerate(solids):
                md = self.gl.MeshData(vertexes=verts.astype(np.float32), faces=faces.astype(np.uint32))
                m = self.gl.GLMeshItem(meshdata=md, color=(*rgb, 1.0), smooth=False, shader=copper_shader(),
                                       glOptions='opaque')
                m.setDepthValue(4)
                self.view.addItem(m)
                self.items[f"part{k}_{j}"] = m
            t = self.gl.GLTextItem(pos=(lx, ly, lz), text=f"{p['ref']} {_value(p, main=True)}".strip(),
                                   color=(20, 20, 20, 255))
            from OpenGL import GL                                   # on top: never hidden behind its chip
            t.setGLOptions({GL.GL_DEPTH_TEST: False, GL.GL_BLEND: True,
                            'glBlendFunc': (GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)})
            t.setDepthValue(20)
            self.view.addItem(t)
            self.items[f"part{k}_label"] = t

    def set_lines(self, lines):
        """The line model of the folder (overlay.load_lines), or None."""
        self.lines, self.sel = lines, None
        if self.gl is not None:
            self._fit_sections()
            self._board()

    def select(self, i):
        """Mark a section of the line model (None: none)."""
        self.sel = i
        if self.gl is not None:
            self._board()

    def _fit_sections(self):
        """The control sections the folder has something for: the field's with a dump, the far field's with an
        antenna result, the line model's tick box with a line model."""
        self.sections['Field'].setVisible(bool(self.srcs))
        self.sections['Far field'].setVisible(self.ant is not None)
        self.lines_on.setVisible(self.lines is not None)
        self.relief.setVisible(self.lines is not None)
        self.parts_on.setVisible(bool((self.board or {}).get('parts')))
        lab = self.relief.parentWidget().layout().labelForField(self.relief) if self.relief.parentWidget() else None
        if lab is not None:
            lab.setVisible(self.lines is not None)

    def _relief_set(self, *_):
        self._relief_auto = False
        self._board()

    def _cu_t_set(self, *_):
        self._cu_t_auto = False
        self._board()

    def _auto_cu_t(self):
        """The copper's shown thickness for a board, 0.6 % of its larger side (a 32 mm board: 0.2 mm), and the line
        model's relief, 1.5 %; each unless set by hand."""
        b = v3.board_box(self.geometry) if self.geometry is not None else None
        if b is None:
            return
        if self._cu_t_auto:
            self.cu_t.blockSignals(True)
            self.cu_t.setValue(round(0.006 * max(b[2] - b[0], b[3] - b[1]), 2))
            self.cu_t.blockSignals(False)
        if self._relief_auto:
            self.relief.blockSignals(True)
            self.relief.setValue(round(0.015 * max(b[2] - b[0], b[3] - b[1]), 2))
            self.relief.blockSignals(False)

    def reset_camera(self):
        zs = self.zscale.value()
        if self.vol is not None:
            lo = self.vol.origin
            hi = lo + self.vol.step * (np.array(self.vol.data.shape[:3]) - 1)
        elif self.geometry is not None and v3.board_box(self.geometry) is not None:
            x0, y0, x1, y1, z0, z1 = v3.board_box(self.geometry)
            lo, hi = np.array([x0, y0, z0]), np.array([x1, y1, z1])
        else:
            return
        if self.far.currentData() is not None:                      # the far field reaches past the board
            r = self.far_size.value() * max(hi[0] - lo[0], hi[1] - lo[1])
            c0 = np.array([0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1]), hi[2] + self.far_up.value() / zs])
            lo, hi = np.minimum(lo, c0 - r), np.maximum(hi, c0 + r)
        c = 0.5 * (lo + hi)
        from PySide6.QtGui import QVector3D
        self.view.setCameraPosition(pos=QVector3D(c[0], c[1], c[2] * zs), distance=1.6 * max(hi[:2] - lo[:2]),
                                    elevation=32, azimuth=-60)

    # ---- animation ----
    def _play(self, on):
        self.play_btn.setText('Pause' if on else 'Play')
        if on:
            self.timer.start(int(1000 / self.fps.value()))
        else:
            self.timer.stop()

    def _tick(self):
        if not self._frames:
            return
        if len(self._frames) > 1:                                   # the phases of a period
            self.k = (self.k + 1) % len(self._frames)
            self._show(self.k)
        elif self.src is not None and self.src.domain == 'TD' and len(self.src) > 1:
            self.frame.setCurrentIndex((self.frame.currentIndex() + self.every.value()) % len(self.src))

    def grab_rgb(self):
        """The view as it is drawn now: (h, w, 3) uint8."""
        img = self.view.grabFramebuffer().convertToFormat(QImage.Format_RGB888)
        a = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes()).reshape(img.height(), img.bytesPerLine())
        return np.ascontiguousarray(a[:, :3 * img.width()].reshape(img.height(), img.width(), 3))

    def animated(self):
        """What a saved animation steps through: 'phase' (a frequency-domain dump's period), 'time' (a time-domain
        dump's steps) or None (one frame: the envelope, a single time step)."""
        if len(self._frames) > 1:
            return 'phase'
        if self.src is not None and self.src.domain == 'TD' and len(self.src) > 1:
            return 'time'
        return None

    def render_frames(self, orbit=0.0):
        """The animation as RGB images from the current camera, at the view's size (orbit: degrees of azimuth
        turned over the animation): a frequency-domain dump's phases, or a time-domain dump's time steps (every
        n-th, as Every n-th frame says). A time-domain dump had given one frame: a still 'animation'."""
        from PySide6.QtWidgets import QApplication
        kind = self.animated()
        if kind is None:
            raise ValueError("one frame only: nothing animates" + (" (untick envelope to save the period)"
                                                                   if self.envelope.isChecked() else ""))
        if kind == 'phase':
            steps = list(range(len(self._frames)))
        else:
            steps = list(range(0, len(self.src), self.every.value()))
        az0, t0 = self.view.opts['azimuth'], self.frame.currentIndex()
        imgs = []
        for n, k in enumerate(steps):
            if kind == 'phase':
                self._show(k)
            else:                                                   # the time step's volume, as the slider would
                self.frame.blockSignals(True)
                self.frame.setCurrentIndex(k)
                self.frame.blockSignals(False)
                self._rebuild()
            if orbit:
                self.view.setCameraPosition(azimuth=az0 + orbit * n / max(len(steps), 1))
            self.view.update()
            QApplication.processEvents()                            # the new texture reaches the GPU on a repaint
            imgs.append(self.grab_rgb())
        self.view.setCameraPosition(azimuth=az0)
        if kind == 'time':
            self.frame.blockSignals(True)
            self.frame.setCurrentIndex(t0)
            self.frame.blockSignals(False)
            self._rebuild()
        else:
            self._show(self.k)
        return imgs

    def save(self, path, fps=None, orbit=0.0):
        from kicad2ems.fields.frames import write_frames
        return write_frames(self.render_frames(orbit), path, fps or self.fps.value())

    def save_dialog(self, ext):
        if self.src is None:
            return
        if self.animated() is None:
            QMessageBox.information(self, f"Save {ext.upper()}", "Only one frame to save: nothing animates" +
                                    (". Untick envelope to save the field over a period." if self.envelope.isChecked()
                                     else "."))
            return
        d = os.path.dirname(self.src.path)
        path, _ = QFileDialog.getSaveFileName(self, f"Save {ext.upper()}", os.path.join(d, f"{self.src.name}_3d.{ext}"),
                                              f"{ext.upper()} (*.{ext})")
        if path:
            try:
                self.save(path)
                self.status.setText(f"saved {path}")
            except Exception as e:
                QMessageBox.warning(self, 'Save', f"{type(e).__name__}: {e}")


def _value(p, main=False):
    """A board.json part's value as text: 100 Ω, 1.5 pF, 2.2 nH (series parts: each, joined; main: only its main
    element's, the capacitance or the inductance without the ESR / ESL fields)."""
    def fmt(v, unit, scales):
        for f, pre in scales:
            if abs(v) >= f * 0.999:
                return f"{v / f:.3g} {pre}{unit}"
        f, pre = scales[-1]
        return f"{v / f:.3g} {pre}{unit}"
    out = []
    if main:
        kind = v3.part_kind(p)
        p = {k: (p.get(k) if k == kind or (kind == 'short' and k == 'R') else None) for k in ('R', 'L', 'C')}
    if p.get('R') is not None:
        out.append('0 Ω' if p['R'] == 0 else fmt(p['R'], 'Ω', [(1e6, 'M'), (1e3, 'k'), (1, '')]))
    if p.get('L') is not None:
        out.append(fmt(p['L'], 'H', [(1e-6, 'µ'), (1e-9, 'n'), (1e-12, 'p')]))
    if p.get('C') is not None:
        out.append(fmt(p['C'], 'F', [(1e-6, 'µ'), (1e-9, 'n'), (1e-12, 'p'), (1e-15, 'f')]))
    return ' + '.join(out)
