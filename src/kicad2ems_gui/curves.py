"""
The curves of the analyses that are not S-parameters, for the Results page (no Qt here: testable without a display).

    sets = load_sets(folder)        # a result's curve sets, as its analysis gives them (Analysis.curves: a rail's
                                    # |Z| each load sees, a near field's spectrum, a circuit's waveforms)
    cs = load_curves(folder)        # the first of them, or None
    value_at(curve, x)              # a curve's value at x (cursor, markers), interpolated along its axes' scales
    export_csv(path, sets)          # every curve of some sets, one x column per run

A CurveSet is one run's curves with how to draw them (titles, log axes); its curves' roles say what each is: 'data'
(a result), 'reference' (what it is compared with in the same run: the bare planes) or 'limit' (a target line).
The Results page knows nothing of the analyses: which one a folder is of, and its curves, come from kicad2ems's
registry.
"""
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
    kind: str                       # the analysis it is of ('pdn', 'mqs', 'circuit')
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


def run_label(folder):
    """A run's short name: what it solved and when (<board>_pdn_P_20261111_013136: 'P, 11-11 01:31:36'), else
    its folder's name."""
    import re
    from kicad2ems.api.frontend import analyses
    kinds = '|'.join(map(re.escape, analyses())) or 'none'
    name = os.path.basename(os.path.normpath(folder or ''))
    m = re.search(rf'_(?:{kinds})_(.+)_(\d{{4}})(\d{{2}})(\d{{2}})_(\d{{2}})(\d{{2}})(\d{{2}})$', name)
    return f"{m[1]}, {m[3]}-{m[4]} {m[5]}:{m[6]}:{m[7]}" if m else name


def curve_set(d, kind, folder=''):
    """A curve set as an analysis gives it (a dict: Analysis.curves) as a CurveSet."""
    cs = CurveSet(kind, d.get('title', ''), d.get('xlabel', ''), d.get('ylabel', ''), logx=bool(d.get('logx', True)),
                  logy=bool(d.get('logy', True)), folder=folder, label=run_label(folder), info=d.get('info', ''))
    for c in d.get('curves', []):
        cs.curves.append(Curve(str(c['name']), np.asarray(c['x'], float), np.asarray(c['y'], float),
                               c.get('role', 'data'), c.get('unit', '')))
    return cs


def load_sets(folder):
    """The curve sets of a results folder, from the analysis whose result it holds; []: none there, not an
    analysis's, or not readable."""
    from kicad2ems.api.frontend import analyses, analysis_of
    made = analysis_of(folder or '')
    if made is None:
        return []
    try:
        return [curve_set(d, made[0], folder) for d in analyses()[made[0]].curves(folder)]
    except Exception:                                       # a plugin's fault, a damaged file: no curves
        return []


def load_curves(folder):
    """The first curve set of a results folder, or None."""
    sets = load_sets(folder)
    return sets[0] if sets else None


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
