"""
The status bar's memory meters and the toolbar's estimate.

    MemoryMeters   system RAM, the GPU's memory and, while a run goes, the run's own memory (it and its children):
                   RAM every 2 s from /proc, the GPU every 3 s through nvidia-smi / rocm-smi in its own process;
                   without either tool, the GPU as the Solvers window's check found it
    EstimateButton what the next run should take (meters.estimate): time, RAM and GPU memory for the solvers it
                   runs; grey when the settings changed since the preview, red when it won't fit; opens the
                   Solvers window
"""
from PySide6.QtCore import Qt, QTimer, QProcess
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar, QToolButton, QSizePolicy
from . import meters

WARN, FULL = 0.80, 0.95                                             # a bar turns amber, then red


def _bar(tip):
    b = QProgressBar()
    b.setRange(0, 1000)
    b.setFixedHeight(16)
    b.setMinimumWidth(150)
    b.setMaximumWidth(210)
    b.setToolTip(tip)
    b.setTextVisible(True)
    return b


def _fill(bar, used, total, label):
    """A bar at used / total, its text 'label used / total GB', amber above 80 %, red above 95 %."""
    frac = used / total if total else 0.0
    bar.setValue(int(1000 * min(max(frac, 0.0), 1.0)))
    bar.setFormat(f"{label} {used:.1f} / {total:.1f} GB")
    colour = '#c0392b' if frac > FULL else ('#d68910' if frac > WARN else '')
    bar.setStyleSheet(f"QProgressBar::chunk {{ background: {colour}; }}" if colour else '')


class MemoryMeters(QWidget):
    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(8)
        self.run = QLabel('')
        self.run.setToolTip('memory of the run: kicad2ems, its workers and openEMS')
        self.run.hide()
        self.ram = _bar('system memory in use (all programs); what is left is what a run can have')
        self.gpu = _bar("the GPU's memory in use (mom25d's GPU solvers)")
        self.gpu_note = QLabel('GPU: none')
        self.gpu_note.setStyleSheet('color: gray')
        self.gpu_note.setToolTip('no GPU found for mom25d (Help > Solvers and hardware)')
        for w in (self.run, self.ram, self.gpu, self.gpu_note):
            lay.addWidget(w)
        self.gpu.hide()
        self.pid, self.info, self.free_gb = None, None, None
        self.cmd = meters.gpu_command()
        self.proc = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(2000)
        self.ticks = 0
        self.tick()

    def set_info(self, info):
        """The Solvers window's check (sysinfo): the GPU's name, and its memory when no vendor tool can poll it."""
        self.info = info
        g = (info or {}).get('gpu')
        if g and not self.cmd:
            if g.get('total'):
                _fill(self.gpu, g['total'] - g['free'], g['total'], 'GPU')
                self.gpu.setToolTip(f"{g['device']} ({g['backend']}): as checked at start (no nvidia-smi / rocm-smi "
                                    f"to follow it)")
                self.gpu.show()
                self.gpu_note.hide()
            else:
                self.gpu_note.setText(f"GPU: {g['free']:.1f} GB free")
        elif g:
            self.gpu.setToolTip(f"{g['device']} ({g['backend']}, {g['api']}): memory in use")

    def set_run(self, pid):
        """Follow a run's process (None: no run)."""
        self.pid = pid
        self.run.setVisible(bool(pid))
        self.tick()

    def tick(self):
        r = meters.ram()
        if r:
            used, total = r
            _fill(self.ram, used, total, 'RAM')
            self.free_gb = total - used
        else:
            self.ram.setFormat('RAM: unknown')
        if self.pid:
            rss = meters.tree_rss(self.pid)
            self.run.setText(f"run: {rss:.2f} GB" if rss is not None else 'run')
        self.ticks += 1
        if self.cmd and self.proc is None and (self.ticks % 2 == 1):        # every other tick: ~4 s
            self.proc = QProcess(self)
            self.proc.finished.connect(self._gpu_read)
            self.proc.start(self.cmd[0], self.cmd[1:])

    def _gpu_read(self, code, _status):
        text = bytes(self.proc.readAllStandardOutput()).decode('utf-8', 'replace')
        self.proc.deleteLater()
        self.proc = None
        cards = meters.parse_gpu(self.cmd[0], text) if code == 0 else []
        if cards:
            used, total = cards[0]                                  # mom25d's device: the first
            _fill(self.gpu, used, total, 'GPU')
            self.gpu.show()
            self.gpu_note.hide()
        else:
            self.gpu.hide()
            self.gpu_note.show()

    def stop(self):
        self.timer.stop()
        if self.proc is not None:
            self.proc.finished.disconnect()
            self.proc.kill()
            self.proc.waitForFinished(1000)
            self.proc = None


class EstimateButton(QToolButton):
    """The toolbar's estimate: '~4 min · 1.3 GB' over the solvers it is for."""
    def __init__(self):
        super().__init__()
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setAutoRaise(True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.setMinimumWidth(130)
        self.show_estimate(None, has_preview=False)

    def show_estimate(self, e, has_preview=True, stale=False, labels=None):
        """e: meters.estimate's dict, or None. stale: the settings changed since the preview."""
        labels = labels or {}
        if e is None:
            self.setText('No estimate\n' + ('no full-wave solver' if has_preview else 'Preview to estimate'))
            self.setToolTip('Preview a board: each full-wave solver\'s time and memory on it shows here and beside '
                            'its tick box (click for the Solvers window)')
            self.setStyleSheet('QToolButton { color: gray; }')
            return
        head = f"{meters.duration(e['seconds'])} · {e['gb']:.1f} GB" + (f" · GPU {e['gpu_gb']:.1f} GB"
                                                                          if e.get('gpu_gb') else '')
        who = ' + '.join(labels.get(n, n) + (' (auto)' if auto else '') for n, *_, auto in e['rows'])
        if e.get('missing'):
            who += ' + ' + ', '.join(e['missing']) + ' (no estimate)'
        self.setText(f"{head}\n{who}" + (' · changed' if stale else ''))
        tip = [f"{labels.get(n, n)}{' (auto)' if auto else ''}: {meters.duration(s)}, {gb:.1f} GB RAM"
               + (f", {g:.1f} GB GPU" if g else '') for n, s, gb, g, auto in e['rows']]
        if not e['fits']:
            tip.append('does not fit in the memory available now (20 % kept spare)')
        if stale:
            tip.append('the settings changed since the preview: preview again for a new estimate')
        self.setToolTip('\n'.join(['Estimate of the last preview'] + tip + ['(click for the Solvers window)']))
        colour = '#c0392b' if not e['fits'] else ('gray' if stale else '')
        self.setStyleSheet(f"QToolButton {{ color: {colour}; }}" if colour else '')
