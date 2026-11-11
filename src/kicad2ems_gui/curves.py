"""
The curves of the analyses that are not S-parameters, for the Results page (no Qt here: testable without a display).

    cs = load_curves(folder)        # a Power integrity result's |Z| each load sees, a Near field result's spectrum
    value_at(curve, x)              # a curve's value at x (cursor, markers), interpolated along its axes' scales
    export_csv(path, sets)          # every curve of some sets, one x column per run

A CurveSet is one run's curves with how to draw them (titles, log axes); its curves' roles say what each is: 'data'
(a result), 'reference' (what it is compared with in the same run: the bare planes) or 'limit' (a target line).
"""
import json
import os
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Curve:
    name: str
    x: np.ndarray
    y: np.ndarray
    role: str = 'data'              # 'data', 'reference' or 'limit'
    unit: str = ''


@dataclass
class CurveSet:
    kind: str                       # 'pdn' or 'mqs'
    title: str
    xlabel: str
    ylabel: str
    curves: list = field(default_factory=list)
    logx: bool = True
    logy: bool = True
    folder: str = ''
    label: str = ''                 # the run, as overlays name it (its folder)
    info: str = ''                  # one line about the run, for the page's head


def _ohm(z):
    return f"{z:.3g} Ω" if z >= 1 else f"{z * 1e3:.3g} mΩ"


def _pdn(res, folder):
    p = res.get('pdn')
    if not p or not p.get('z'):
        return None
    f = np.asarray(p['f'], float)
    cs = CurveSet('pdn', 'Impedance each load sees', 'frequency (Hz)', '|Z| (Ω)', folder=folder)
    for ref, z in p['z'].items():
        cs.curves.append(Curve(ref, f, np.asarray(z['mag'], float), unit='Ω'))
        cs.curves.append(Curve(f"{ref}, bare planes", f, np.asarray(z['bare'], float), 'reference', 'Ω'))
    targets = sorted({t for t in [p.get('target'), *[z.get('target') for z in p['z'].values()]] if t})
    for t in targets:
        cs.curves.append(Curve(f"target {_ohm(t)}", f[[0, -1]], np.array([t, t], float), 'limit', 'Ω'))
    worst = max(p['z'].items(), key=lambda kv: max(kv[1]['mag']))
    cs.info = (f"Power integrity, rail {res.get('rail', '?')}: {len(p['z'])} load{'s' if len(p['z']) != 1 else ''}, "
               f"at most {_ohm(max(worst[1]['mag']))} (at {worst[0]})")
    return cs


def _mqs(res, folder):
    if res.get('preview') or not res.get('frequencies_Hz'):
        return None
    f = np.asarray(res['frequencies_Hz'], float)
    cs = CurveSet('mqs', 'Peak magnetic field per harmonic', 'frequency (Hz)', 'peak |H| (A/m)', folder=folder)
    cs.curves.append(Curve('peak |H|', f, np.asarray([max(row) for row in res['peak_H_Am']], float), unit='A/m'))
    s = res.get('selection', {})
    cs.info = f"Near field, {s.get('converter', '?')} on {s.get('vin', '?')}: {len(f)} harmonic{'s' if len(f) != 1 else ''}"
    return cs


def run_label(folder):
    """A run's short name: what it solved and when (<board>_pdn_P_20261111_013136: 'P, 11-11 01:31:36'), else
    its folder's name."""
    import re
    name = os.path.basename(os.path.normpath(folder or ''))
    m = re.search(r'_(?:pdn|mqs)_(.+)_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$', name)
    return f"{m[1]}, {m[3]}-{m[4]} {m[5]}:{m[6]}:{m[7]}" if m else name


def load_curves(folder):
    """The curves of a results folder (pdn.json, else mqs.json), or None: none there, or not readable."""
    for name, make in (('pdn.json', _pdn), ('mqs.json', _mqs)):
        path = os.path.join(folder or '', name)
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    cs = make(json.load(fh), folder)
            except (OSError, ValueError, KeyError, TypeError):
                return None
            if cs is not None:
                cs.label = run_label(folder)
            return cs
    return None


def value_at(curve, x, logx=True, logy=True):
    """The curve at x, interpolated along the axes as they are drawn (a straight segment on a log-log plot is a
    power law); None outside it."""
    xs, ys = np.asarray(curve.x, float), np.asarray(curve.y, float)
    if len(xs) == 0 or not (xs.min() <= x <= xs.max()):
        return None
    ok = (xs > 0 if logx else np.isfinite(xs)) & (ys > 0 if logy else np.isfinite(ys))
    if ok.sum() < 2:
        return float(ys[np.argmin(np.abs(xs - x))])
    tx = np.log10(xs[ok]) if logx else xs[ok]
    ty = np.log10(ys[ok]) if logy else ys[ok]
    order = np.argsort(tx)
    v = np.interp(np.log10(x) if logx else x, tx[order], ty[order])
    return float(10 ** v) if logy else float(v)


def fmt(v, unit=''):
    if v is None:
        return ''
    if unit == 'Ω':
        return _ohm(v)
    return f"{v:.4g}" + (f" {unit}" if unit else '')


def fmt_hz(f):
    return f"{f / 1e9:.4g} GHz" if f >= 1e9 else (f"{f / 1e6:.4g} MHz" if f >= 1e6 else
                                                  (f"{f / 1e3:.4g} kHz" if f >= 1e3 else f"{f:.4g} Hz"))


def export_csv(path, sets):
    """Every data and reference curve of the sets: per run, its x then its curves (runs side by side, a shorter
    one padded)."""
    cols = []
    for cs in sets:
        seen = None
        for c in cs.curves:
            if c.role == 'limit':
                continue
            x = np.asarray(c.x, float)
            if seen is None or len(seen) != len(x) or not np.allclose(seen, x):
                cols.append((f"{cs.label}: {cs.xlabel}", x))
                seen = x
            cols.append((f"{cs.label}: {c.name}" + (f" ({c.unit})" if c.unit else ''), np.asarray(c.y, float)))
    n = max((len(v) for _, v in cols), default=0)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(','.join('"' + h.replace('"', "'") + '"' for h, _ in cols) + '\n')
        for i in range(n):
            fh.write(','.join(f"{v[i]:.6g}" if i < len(v) else '' for _, v in cols) + '\n')
