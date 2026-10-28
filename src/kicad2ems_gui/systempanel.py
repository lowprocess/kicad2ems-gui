"""
The Solvers window (Help > Solvers and hardware, or ? beside the Solvers settings): the solvers this machine can
run, the GPU mom25d would use, the memory of the system and of the GPU (kicad2ems.sysinfo, run as its own process
with the interpreter the runs use), and after a preview what each full-wave solver would need on that board
(summary['estimates'] of <name>_run.json) against it.
"""
import glob, json, os, sys
from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QProgressBar, QGroupBox, QFormLayout, QHeaderView, QLineEdit)

OK, NO = '✔', '✖'


def _bar(used, total):
    b = QProgressBar()
    b.setRange(0, 1000)
    b.setValue(int(1000 * used / total) if total else 0)
    b.setFormat(f"{used:.1f} of {total:.1f} GB in use" if total else 'unknown')
    b.setMaximumHeight(16)
    return b


def fit_note(need, have):
    """'fits' / 'tight' / 'does not fit' of `need` GB against `have` GB available (the solvers keep 20 % spare)."""
    if not need or have is None:
        return ''
    return 'fits' if need <= 0.8 * have else ('tight' if need <= have else 'does not fit')


def _user_value(key):
    """The user's own site.toml setting of key, or '' (the field shows it, not setup.sh's)."""
    from kicad2ems.api.frontend import sitecfg
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    try:
        with open(sitecfg.user_file(), 'rb') as fh:
            return str(tomllib.load(fh).get(key) or '')
    except (OSError, ValueError):
        return ''


class SystemPanel(QWidget):
    ready = Signal(dict)                                            # the machine's info, when its check is done

    def __init__(self):
        super().__init__()
        self.info, self.est, self.proc = None, None, None
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.state = QLabel('checking the solvers and the GPU…')
        self.state.setStyleSheet('color: gray')
        top.addWidget(self.state, 1)
        self.refresh_btn = QPushButton('Refresh')
        self.refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self.refresh_btn)
        lay.addLayout(top)
        box = QGroupBox('Solvers')
        bl = QVBoxLayout(box)
        self.solvers = QTreeWidget()
        self.solvers.setHeaderLabels(['', 'solver', 'details'])
        self.solvers.setRootIsDecorated(False)
        self.solvers.header().setSectionResizeMode(2, QHeaderView.Stretch)
        bl.addWidget(self.solvers)
        lay.addWidget(box)
        box = QGroupBox('Programs')                                 # the machine's, not a board's: site.toml
        pf = QFormLayout(box)
        row = QHBoxLayout()
        self.qucsator = QLineEdit()
        self.qucsator.setToolTip("the line model's circuit solver (Qucs-S's qucsator_rf, or qucsator): empty finds it "
                                 "on the PATH (or where setup.sh recorded it); saved in ~/.config/kicad2ems/site.toml")
        self.qucsator.setText(_user_value('qucsator'))
        self.qucsator.editingFinished.connect(self._save_programs)
        row.addWidget(self.qucsator, 1)
        b = QPushButton('…')
        b.setFixedWidth(28)
        b.clicked.connect(self._browse_qucsator)
        row.addWidget(b)
        pf.addRow('qucsator program', row)
        row = QHBoxLayout()
        self.openems_venv = QLineEdit()
        self.openems_venv.setToolTip("a Python environment (venv) with openEMS (CSXCAD and openEMS), when it is not "
                                     "in kicad2ems's own: its folder, or its bin/python. It must be the same Python "
                                     "version as kicad2ems's; saved in ~/.config/kicad2ems/site.toml")
        self.openems_venv.setPlaceholderText('empty: openEMS in kicad2ems\'s own Python')
        self.openems_venv.setText(_user_value('openems_venv'))
        self.openems_venv.editingFinished.connect(self._save_programs)
        row.addWidget(self.openems_venv, 1)
        b = QPushButton('…')
        b.setFixedWidth(28)
        b.clicked.connect(self._browse_openems)
        row.addWidget(b)
        pf.addRow('openEMS environment', row)
        lay.addWidget(box)
        box = QGroupBox('Hardware')
        self.hw = QFormLayout(box)
        lay.addWidget(box)
        box = QGroupBox('Estimate (the last preview)')
        el = QVBoxLayout(box)
        self.est_note = QLabel('Preview a board: what each full-wave solver needs on its mesh appears here')
        self.est_note.setWordWrap(True)
        self.est_note.setStyleSheet('color: gray')
        el.addWidget(self.est_note)
        self.est_tree = QTreeWidget()
        self.est_tree.setHeaderLabels(['solver', 'time', 'memory', 'GPU memory', 'how', 'model'])
        self.est_tree.setRootIsDecorated(False)
        self.est_tree.header().setSectionResizeMode(5, QHeaderView.Stretch)
        el.addWidget(self.est_tree)
        lay.addWidget(box, 1)
        self.refresh()

    # ---- the programs ----
    def _browse_qucsator(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, 'qucsator program', self.qucsator.text() or '/usr/bin')
        if path:
            self.qucsator.setText(path)
            self._save_programs()

    def _browse_openems(self):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, 'A Python environment (venv) with openEMS',
                                                self.openems_venv.text() or os.path.expanduser('~'))
        if path:
            self.openems_venv.setText(path)
            self._save_programs()

    def _save_programs(self):
        """The programs into the user's site.toml (sitecfg), then the solvers checked again."""
        from kicad2ems.api.frontend import sitecfg
        changed = False
        for key, field in (('qucsator', self.qucsator), ('openems_venv', self.openems_venv)):
            path = field.text().strip()
            if path != _user_value(key):
                sitecfg.set_user(key, path)
                changed = True
        if changed:
            self.refresh()

    # ---- the machine ----
    def refresh(self):
        if self.proc is not None:
            return
        self.state.setText('checking the solvers and the GPU…')
        self.refresh_btn.setEnabled(False)
        self.proc = QProcess(self)
        self.proc.finished.connect(self._done)
        self.proc.start(sys.executable, ['-m', 'kicad2ems.sysinfo'])

    def stop(self):
        """End a check still going (the window closes)."""
        if self.proc is not None:
            self.proc.finished.disconnect()
            self.proc.kill()
            self.proc.waitForFinished(2000)
            self.proc = None

    def _done(self, code, _status):
        out = bytes(self.proc.readAllStandardOutput()).decode('utf-8', 'replace')
        err = bytes(self.proc.readAllStandardError()).decode('utf-8', 'replace')
        self.proc = None
        self.refresh_btn.setEnabled(True)
        try:
            from kicad2ems.api.frontend import check_format
            d = json.loads(out)
            why = check_format(d, 'kicad2ems-sysinfo')
            if why:
                self.state.setText(f"system check: {why}")
                return
            self.set_info(d)
        except ValueError:
            self.state.setText(f"system check failed (code {code}): {err.strip().splitlines()[-1] if err.strip() else out[:200]}")

    def set_info(self, info):
        self.info = info
        self.state.setText(f"{sum(s['ok'] for s in info['solvers'])} of {len(info['solvers'])} solvers available")
        self.state.setStyleSheet('')
        self.solvers.clear()
        for s in info['solvers']:
            it = QTreeWidgetItem([OK if s['ok'] else NO, s['label'], s['what']])
            it.setForeground(0, Qt.darkGreen if s['ok'] else Qt.red)
            it.setToolTip(2, s['what'])
            self.solvers.addTopLevelItem(it)
        for i in range(2):
            self.solvers.resizeColumnToContents(i)
        self.ready.emit(info)
        rows = max(1, self.solvers.topLevelItemCount())
        self.solvers.setFixedHeight(self.solvers.header().height() + rows * self.solvers.sizeHintForRow(0) + 6)
        while self.hw.rowCount():
            self.hw.removeRow(0)
        ram, g = info['ram'], info.get('gpu')
        self.hw.addRow('CPU', QLabel(f"{info.get('cpus') or '?'} cores"))
        if ram.get('total'):
            avail = ram.get('available')
            self.hw.addRow('Memory', _bar(ram['total'] - (avail if avail is not None else 0), ram['total']))
            self.hw.addRow('', QLabel(f"{avail:.1f} GB available" if avail is not None else ''))
        if g:
            self.hw.addRow('GPU', QLabel(f"{OK} {g['device']} ({g['backend']}, {g['api']})"))
            if g.get('total'):
                self.hw.addRow('GPU memory', _bar(g['total'] - g['free'], g['total']))
            self.hw.addRow('', QLabel(f"{g['free']:.1f} GB free: mom25d's complex64 LU runs there"))
        else:
            lab = QLabel(f"{NO} none: mom25d solves on the CPU ({info.get('gpu_why') or 'no GPU backend'}). For a GPU, "
                         f"install CuPy into this Python ({sys.executable}): pip install cupy-rocm-7-0 (AMD, ROCm 7), "
                         f"cupy-cuda12x or cupy-cuda13x (NVIDIA)")
            lab.setWordWrap(True)
            self.hw.addRow('GPU', lab)
        self.show_estimates(self.est)

    # ---- a preview's estimates ----
    def load_estimates(self, out_dir):
        """The estimates of the newest <name>_run.json in out_dir (a preview's); False when there are none."""
        runs = sorted(glob.glob(os.path.join(out_dir, '*_run.json')), key=os.path.getmtime)
        if not runs:
            return False
        try:
            from kicad2ems.api.frontend import read_summary
            est = read_summary(runs[-1]).get('estimates')
        except (OSError, ValueError):
            return False
        if not est:
            return False
        self.est = est
        self.show_estimates(est)
        return True

    def show_estimates(self, est):
        self.est_tree.clear()
        if not est or not est.get('solvers'):
            return
        ram = (self.info or {}).get('ram', {}).get('available')
        g = (self.info or {}).get('gpu')
        gfree = g['free'] if g else None
        usable = {s['name']: s['ok'] for s in (self.info or {}).get('solvers', [])}
        for n, e in est['solvers'].items():
            sec = e.get('seconds', 0)
            t = f"~{sec:.0f} s" if sec < 120 else (f"~{sec / 60:.0f} min" if sec < 7200 else f"~{sec / 3600:.1f} h")
            mem = f"{e['gb']:.1f} GB" + (f" ({fit_note(e['gb'], ram)})" if ram else '')
            gm = e.get('gpu_gb')
            gtxt = (f"{gm:.1f} GB" + (f" ({fit_note(gm, gfree)})" if gfree else '')) if gm else ''
            how = e.get('how', '') if usable.get(n, True) else 'not available here (the preview only meshes it)'
            it = QTreeWidgetItem([n, t, mem, gtxt, how, e.get('what', '')])
            if ram and e['gb'] > ram:
                it.setForeground(2, Qt.red)
            if not usable.get(n, True):
                for c in range(6):
                    it.setForeground(c, Qt.gray)
            it.setToolTip(5, e.get('what', ''))
            self.est_tree.addTopLevelItem(it)
        for i in range(5):
            self.est_tree.resizeColumnToContents(i)
        self.est_note.setText("On the board's mesh at the current settings; the memory against what is "
                              "available now (20 % kept spare).")
