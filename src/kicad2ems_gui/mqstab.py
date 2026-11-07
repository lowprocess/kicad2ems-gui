"""Near-field page: the MQS CLI owns options and physics; Qt runs it in a subprocess."""
import html
import json
import os
import subprocess
import sys
from pathlib import Path

from .pdntab import PdnTab, FitImages, pdn_argv
from PySide6.QtCore import Qt, QProcess
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QTabWidget,
                               QTextBrowser, QPlainTextEdit, QPushButton)
import pyqtgraph as pg


def describe():
    p=subprocess.run([sys.executable,'-m','mom25d.mqs','--describe','--json'],capture_output=True,text=True,timeout=60)
    if p.returncode:
        raise ValueError(p.stderr.strip() or 'MQS command unavailable; update mom25d')
    d=json.loads(p.stdout)
    if d.get('format')!=1:
        raise ValueError('Unsupported MQS option format; update mom25d and kicad2ems-gui')
    return d


def mqs_argv(vals,board,out,desc,python=None):
    argv=pdn_argv(vals,board,out,desc,python)
    argv[2]='mom25d.mqs'
    return argv


def load_result(out):
    path=Path(out)/'mqs.json'
    if not path.is_file():return None
    res=json.loads(path.read_text())
    if res.get('format')!=1:raise ValueError('Unsupported MQS result format')
    res['_dir']=str(out)
    return res


def summary_html(res):
    s=res['selection'];e=html.escape
    h=[f"<h3>{e(s['converter'])}: {e(s['vin'])} / {e(s['ground'])}</h3>",
       f"<p>Input capacitors: {e(', '.join(s['capacitors']))}; {res['triangles']:,} triangles.</p>",
       '<table cellspacing=6><tr><th>Hz</th><th>Peak A</th><th>Copper R (mΩ)</th><th>Copper L (nH)</th><th>Peak H (A/m)</th></tr>']
    for f,a,r,l,hp in zip(res['frequencies_Hz'],res['harmonic_peak_A'],res['copper_R_ohm'],res['copper_L_H'],res['peak_H_Am']):
        h.append(f'<tr><td>{f:g}</td><td>{a:.4g}</td><td>{r*1e3:.4g}</td><td>{l*1e9:.4g}</td><td>{max(hp):.4g}</td></tr>')
    h.append('</table><h4>Model assumptions</h4><ul>')
    h.extend(f'<li>{e(note)}</li>' for note in res.get('notes',[]))
    h.append('</ul>')
    return ''.join(h)


class MqsTab(PdnTab):
    """Reuse the PDN option form and process controls, with MQS-specific results."""
    def __init__(self,win=None):
        QWidget.__init__(self)
        self.win,self.proc,self.out,self.result=win,None,None,None
        why=''
        try:self.desc=describe()
        except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
            self.desc=None;why=str(exc)
        layout=QHBoxLayout(self);self.split=QSplitter(Qt.Horizontal);layout.addWidget(self.split)
        self.split.addWidget(self._form());self.split.addWidget(self._views());self.split.setSizes([380,900])
        from .panels import Section
        for section in self.findChildren(Section):
            if section.title in ('Converter', 'Operating point'):
                section.set_expanded(True)
        self.outdir.setPlaceholderText('mqs_<converter> beside the board')
        self.run_btn.setToolTip('Solve the converter input loop and scan its magnetic near field')
        if self.desc is None:
            self.run_btn.setEnabled(False);self.say(why)

    def _views(self):
        self.tabs=QTabWidget()
        self.summary=QTextBrowser();self.maps=FitImages('Magnetic near-field maps')
        self.spectrum=pg.PlotWidget(title='Peak magnetic field per harmonic')
        self.spectrum.setLogMode(x=True,y=True)
        self.spectrum.setLabel('bottom','Hz');self.spectrum.setLabel('left','Peak |H|, A/m')
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(5000)
        self.tabs.addTab(self.summary,'Summary');self.tabs.addTab(self.spectrum,'Spectrum')
        self.tabs.addTab(self.maps,'H maps');self.tabs.addTab(self.log,'Log')
        box=QWidget();layout=QVBoxLayout(box);layout.addWidget(self.tabs)
        self.open_btn=QPushButton('Open fields in Viewer');self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self.open_fields);layout.addWidget(self.open_btn)
        return box

    def start(self):
        if self.proc is not None:return
        board=self.board_path()
        if not board or not os.path.isfile(board):
            self.status.setText('Choose a board first');return
        vals=self.values();ref=vals.get('converter') or 'auto'
        folder='mqs_'+''.join(c if c.isalnum() else '_' for c in ref)
        self.out=os.path.abspath(self.outdir.text().strip() or os.path.join(os.path.dirname(os.path.abspath(board)),folder))
        argv=mqs_argv(vals,board,self.out,self.desc)
        self.log.clear();self.say('$ python '+' '.join(argv[1:]));self.tabs.setCurrentWidget(self.log)
        self.proc=QProcess(self);self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._stdout);self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)
        self.run_btn.setEnabled(False);self.stop_btn.setEnabled(True);self.busy.show()
        self.open_btn.setEnabled(False);self.status.setText('Running…')
        self.proc.start(argv[0],argv[1:])

    def _error(self,error):
        if error==QProcess.FailedToStart:
            self.say(self.proc.errorString());self._finished(-1)

    def _stdout(self):
        text=bytes(self.proc.readAllStandardOutput()).decode(errors='replace')
        self.say(text.rstrip())
        lines=[s for s in text.splitlines() if s.startswith('mqs:')]
        if lines:self.status.setText(lines[-1][4:].strip())

    def _finished(self,code,_status=None):
        if self.proc is not None:
            self._stdout();self.proc.deleteLater();self.proc=None
        self.run_btn.setEnabled(True);self.stop_btn.setEnabled(False);self.busy.hide()
        try:res=load_result(self.out) if code==0 else None
        except (OSError,ValueError,KeyError) as exc:
            self.say(str(exc));res=None
        if res is None:
            self.status.setText(f'Run failed (exit {code}); see Log');return
        self.show_result(res);self.tabs.setCurrentWidget(self.summary);self.status.setText('Done')

    def show_result(self,res):
        self.result=res;self.summary.setHtml(summary_html(res))
        self.maps.show_images([os.path.join(res['_dir'],f) for f in res.get('figures',[])])
        self.spectrum.clear()
        self.spectrum.plot(res['frequencies_Hz'],[max(row) for row in res['peak_H_Am']],pen='b',symbol='o')
        self.open_btn.setEnabled(self.win is not None)

    def open_fields(self):
        if self.win is not None and self.result is not None:
            self.win.open_results(self.result['_dir'])
