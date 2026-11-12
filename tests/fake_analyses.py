"""Stand-ins for the analysis plugins, for the window's tests (as kicad2ems's standins.py is for the solvers): the
same names, labels and order as pcbqs's four, so the window is the one a user has, but each a few lines whose
"tool" (fake_tool.py) writes a small result at once. The window knows no analysis by name, so what is tested with
these holds for any plugin; test_real_analyses.py runs pcbqs's own through the same window.

    install()                       before kicad2ems_gui is imported (conftest.py): the registry holds these
    write(kind, folder, **values)   a result as the stand-in tool writes it (a test's own folders)
"""
import json
import os
import sys

from kicad2ems import analyses
from kicad2ems.api.analysis import Analysis

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, 'fake_tool.py')


def opt(key, kind='str', default='', group='Settings', help=''):
    return dict(key=key, flag='--' + key.replace('_', '-'), kind=kind, default=default, help=help or key.replace('_', ' '),
                group=group, choices=None)


def write(kind, folder, preview=False, **v):
    """The result a stand-in's tool leaves in `folder` for the settings v; returns the folder."""
    os.makedirs(folder, exist_ok=True)
    scale = float(v.get('scale') or 1.0)
    if kind == 'pdn':
        f = [10 ** (4 + 0.2 * k) for k in range(21)]
        res = dict(rail=v.get('rail') or 'P', volts=float(v.get('volts') or 3.3), loads=dict(U1=[2.0, 10.0 * scale], U2=[0.5, 4.0]),
                   f=f, mag=[scale * 0.01 * (1 + x / 1e6) for x in f], bare=[1e3 / x for x in f], target=0.05,
                   notes=['a note'] if v.get('note') else [])
    elif kind == 'mqs':
        res = dict(converter=v.get('converter') or 'U3', vin=v.get('vin') or 'VIN', ground=v.get('ground') or 'GND',
                   volts=float(v.get('vin_volts') or 0), f=[5e5, 1e6, 1.5e6], peak=[3.0, 1.5, 0.9], preview=bool(preview))
    elif kind == 'circuit':
        res = dict(format=2, name=v.get('name') or 'Stand-in circuit', cases=[], failed=[], complete=True,
                   points=[['light', 1.0, 98.0], ['full', 4.0, 94.0]], model=v.get('model') or '')
        with open(os.path.join(folder, 'model.json'), 'w', encoding='utf-8') as fh:
            json.dump(dict(format=2, parts=[], board=dict(file=v.get('_board') or '')), fh)
    elif kind == 'thermal':
        losses = v.get('loss') or 'Q1=0.5'
        losses = losses if isinstance(losses, (list, tuple)) else [s for s in str(losses).replace(',', '\n').splitlines() if s.strip()]
        parts = {s.split('=')[0].strip(): float(s.split('=')[1]) for s in losses}
        res = dict(parts={r: [w, 25.0 + 100.0 * w * scale] for r, w in parts.items()}, circuit=v.get('circuit') or '',
                   film=float(v.get('film') or 10.0), hottest=25.0 + 100.0 * max(parts.values()) * scale)
        _temperature_dump(folder, res['hottest'])
    else:
        raise ValueError(kind)
    a = analyses.registry()[kind]
    with open(os.path.join(folder, a.preview_result if preview else a.result), 'w', encoding='utf-8') as fh:
        json.dump(res, fh)
    return folder


def _temperature_dump(folder, hottest):
    """A layer's temperature where a viewer reads a run's dumps: a 0 Hz plane dump in C, NaN off the board, its
    colours spanning its own values (as an analysis writes its maps: kicad2ems.api.analysis)."""
    import numpy as np
    from types import SimpleNamespace
    from shapely.geometry import box
    from kicad2ems.api.analysis import Dump, write_info, write_npz
    x, y = np.linspace(0, 20, 21), np.linspace(0, 10, 11)
    t = 40.0 + (hottest - 40.0) * np.exp(-((x[:, None] - 8) ** 2 + (y[None, :] - 5) ** 2) / 30.0)
    t[-3:, -3:] = np.nan                                            # a corner cut away
    exc = os.path.join(folder, 'thermal', 'exc_board')
    os.makedirs(exc, exist_ok=True)
    dm = Dump('T@F.Cu', 'T', (0, 0, 1.5), (20, 10, 1.5), [0.0], 2, 'F.Cu')
    data = np.zeros((21, 11, 3))
    data[:, :, 0] = t
    write_npz(os.path.join(exc, dm.name + '.npz'), dict(x=x, y=y, z=np.array([1.5])), [0.0], data[None, :, :, None, :])
    m = SimpleNamespace(outline=box(0, 0, 20, 10), cu_z={'F.Cu': 1.5}, copper={'F.Cu': [box(1, 1, 19, 9)]}, ports=[],
                        vias=[], thickness=1.5)
    write_info(exc, [dm], m)
    path = os.path.join(exc, 'dump_info.json')
    info = json.load(open(path, encoding='utf-8'))
    info['dumps'][0].update(unit='°C', range='data')
    json.dump(info, open(path, 'w', encoding='utf-8'))


class _Fake(Analysis):
    api = (2, 5)
    OPTIONS = ()

    def check(self):
        return True, 'a stand-in (the tests)'

    def options(self):
        return [dict(o) for o in self.OPTIONS]

    def command(self, values, board, out, preview=False, results=None):
        if not board:
            raise ValueError('choose a board first')
        return [sys.executable, TOOL, self.name, out, json.dumps(dict(values, _board=board, _preview=preview))]

    def status(self, line):
        return line.split(':', 1)[1].strip() if line.startswith(self.name + ':') else None

    def read(self, folder):
        for f in (self.result, self.preview_result):
            p = os.path.join(folder or '', f) if f else ''
            if p and os.path.isfile(p):
                return json.load(open(p, encoding='utf-8'))
        return None


class PowerIntegrity(_Fake):
    name, label, tool, order, result = 'pdn', 'Power integrity', 'fake.pdn', 20, 'pdn.json'
    about = "a rail's DC drop and the impedance its loads see"
    OPTIONS = (opt('rail', group='Rail'), opt('volts', 'float', 3.3, 'Rail'), opt('load', 'list', [], 'Rail'),
               opt('scale', 'float', 1.0, 'Rail'), opt('no_pdn', 'bool', False, 'PDN impedance'))

    def tag(self, values):
        return str(values.get('rail') or 'rail').strip()

    def command(self, values, board, out, preview=False, results=None):
        if not board:
            raise ValueError('choose a board first')
        if not str(values.get('rail') or '').strip():
            raise ValueError('name the rail (its net)')
        return super().command(values, board, out, preview, results)

    def report(self, folder):
        r = self.read(folder)
        if r is None:
            return None
        worst = max(r['loads'].items(), key=lambda kv: kv[1][1])
        return dict(title=f"{r['rail']}: {r['volts']:g} V", summary=f"Power integrity, rail {r['rail']}: worst DC drop "
                    f"{worst[1][1]:.2f} mV (at {worst[0]})", notes=r['notes'], images=[], footer='a stand-in',
                    show=dict(field='V', run='power'),
                    sections=[dict(title='', text=f"Rail tree: {r['rail']}."),
                              dict(title='Loads at DC', table=dict(columns=['load', 'I (A)', 'drop (mV)'], formats=[None, '.3g', '.2f'],
                                                                   rows=[[k, i, d] for k, (i, d) in r['loads'].items()]))])

    def curves(self, folder):
        r = self.read(folder)
        if r is None:
            return []
        f = r['f']
        return [dict(title='Impedance each load sees', xlabel='frequency (Hz)', ylabel='|Z| (Ω)', logx=True, logy=True,
                     info=self.report(folder)['summary'],
                     curves=[dict(name='U1', x=f, y=r['mag'], role='data', unit='Ω'),
                             dict(name='U1, bare planes', x=f, y=r['bare'], role='reference', unit='Ω'),
                             dict(name='target 50 mΩ', x=[f[0], f[-1]], y=[r['target']] * 2, role='limit', unit='Ω')])]


class NearField(_Fake):
    name, label, tool, order = 'mqs', 'Near field', 'fake.mqs', 30
    about = "a converter's input loop and its magnetic near field"
    previewed, finds = True, 'converters'
    result, preview_result = 'mqs.json', 'mqs-preview.json'
    OPTIONS = (opt('converter', group='Converter'), opt('vin', group='Converter'), opt('ground', default='GND', group='Converter'),
               opt('fsw', 'float', 5e5, 'Operating point'), opt('vin_volts', 'float', 0.0, 'Operating point'))

    def tag(self, values):
        return str(values.get('converter') or 'auto').strip()

    def discover(self, values, board):
        if not board:
            raise ValueError('choose a board first')
        return [sys.executable, TOOL, 'find', board]

    def choices(self, text):
        try:
            return [(c['label'], c['values']) for c in json.loads(text[text.index('['):])]
        except ValueError:
            return []

    def suggest(self, folder):
        r = self.read(folder)
        if r is None:
            return []
        volts = r['volts'] or ''
        return [dict(to='pdn', label='Copy the input rail to Power integrity', need=[] if volts else ['volts'],
                     values=dict(rail=r['vin'], volts=volts, load=''), note='The input rail is copied.')]

    def report(self, folder):
        r = self.read(folder)
        if r is None:
            return None
        if r.get('preview'):
            return dict(title=f"{r['converter']}: mesh preview", summary=f"Near field, {r['converter']}: mesh preview",
                        sections=[dict(title='', text='No solve.')], notes=[], images=[], footer='', mesh='mqs')
        return dict(title=f"{r['converter']}: {r['vin']} / {r['ground']}", summary=f"Near field, {r['converter']} on {r['vin']}: 3 harmonics",
                    sections=[dict(title='Harmonics', table=dict(columns=['frequency (Hz)', 'peak H (A/m)'], formats=['g', '.4g'],
                                                                 rows=[list(p) for p in zip(r['f'], r['peak'])]))],
                    notes=[], images=[], footer='', mesh='mqs')

    def curves(self, folder):
        r = self.read(folder)
        if r is None or r.get('preview'):
            return []
        return [dict(title='Peak magnetic field per harmonic', xlabel='frequency (Hz)', ylabel='peak |H| (A/m)', logx=True,
                     logy=True, info=self.report(folder)['summary'],
                     curves=[dict(name='peak |H|', x=r['f'], y=r['peak'], role='data', unit='A/m')])]


class Circuit(_Fake):
    name, label, tool, order, result = 'circuit', 'Circuit', 'fake.circuit', 40, 'circuit.json'
    about = 'ngspice runs of a circuit model'
    page, paths = True, ('model',)
    OPTIONS = (opt('model', group='Circuit'), opt('copper', 'bool', False, 'Circuit'))

    def tag(self, values):
        return os.path.splitext(os.path.basename(str(values.get('model') or 'circuit')))[0]

    def report(self, folder):
        r = self.read(folder)
        if r is None or 'points' not in r:
            return None
        return dict(title=r['name'], summary=f"Circuit, {r['name']}: {len(r['points'])} points", notes=[], images=[], footer='',
                    sections=[dict(title='Points', table=dict(columns=['point', 'load (A)', 'efficiency %'], rows=r['points'],
                                                              formats=[None, '.3g', '.1f']))])

    def curves(self, folder):
        r = self.read(folder)
        if r is None or 'points' not in r:
            return []
        t = [0.1 * k for k in range(41)]
        return [dict(title=f"{name}: {what}", xlabel='time in the final two periods (µs)', ylabel=u, logx=False, logy=False,
                     info=self.report(folder)['summary'],
                     curves=[dict(name=what[0], x=t, y=[amp * (k % 20 < 10) for k in range(41)], role='data', unit=u)])
                for name, amp, _e in r['points'] for what, u in (('voltages', 'V'), ('currents', 'A'))]


class Thermal(_Fake):
    name, label, tool, order, result = 'thermal', 'Thermal', 'fake.thermal', 50, 'thermal.json'
    about = "the board's steady temperature from its parts' losses"
    paths = ('circuit',)
    OPTIONS = (opt('loss', 'list', [], 'Heat'), opt('circuit', group='Heat'), opt('film', 'float', 10.0, 'Air'),
               opt('scale', 'float', 1.0, 'Air'))

    def tag(self, values):
        return 'losses' if str(values.get('loss') or '').strip() else 'circuit'

    def command(self, values, board, out, preview=False, results=None):
        values = dict(values)
        if not str(values.get('loss') or '').strip() and not values.get('circuit'):
            if not (results or {}).get('circuit'):
                raise ValueError("give the parts' losses (REF=W), or run the Circuit analysis first")
            values['circuit'] = results['circuit']
        return super().command(values, board, out, preview, results)

    def report(self, folder):
        r = self.read(folder)
        if r is None:
            return None
        return dict(title=f"Hottest copper {r['hottest']:.1f} °C", summary=f"Thermal: hottest copper {r['hottest']:.1f} °C",
                    notes=[], images=[], footer='', show=dict(field='T'),
                    sections=[dict(title='', text=f"films {r['film']:g} W/m²K" + (f"; losses of {os.path.basename(r['circuit'])}" if r['circuit'] else '')),
                              dict(title='Parts', table=dict(columns=['part', 'loss (W)', 'part °C'], formats=[None, '.3g', '.1f'],
                                                             rows=[[k, w, c] for k, (w, c) in r['parts'].items()])),
                              dict(title='Layers', table=dict(columns=['layer', 'hottest °C'], formats=[None, '.1f'],
                                                              rows=[['F.Cu', r['hottest']]]))])


FAKES = (PowerIntegrity, NearField, Circuit, Thermal)


class _EP:
    def __init__(self, cls):
        self.name, self.value, self._cls = cls.name, f"tests:{cls.__name__}", cls

    def load(self):
        return self._cls


def install():
    """The registry holds the stand-ins (and nothing an installed package registers)."""
    analyses._entry_points = lambda: [_EP(c) for c in FAKES]
    analyses._registry = None
    analyses.broken.clear()
    return analyses.registry()
