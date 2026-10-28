"""
S-parameter traces for the interactive plots (no Qt here: testable without a display).

    traces = load_traces(files, compare=None)    # the run's Touchstone files (openEMS, mom25d, line model, compare)
    x, y = transform('dB', tr)                   # what a plot kind shows of a trace
    x, y = difference('Δ|S| (dB)', tr, ref)      # a trace against the same S of another solver
    value_at(kind, tr, f)                        # the value at a frequency (cursor, markers)
    export_csv(path, traces, kind)
"""
import os, re
import numpy as np

KINDS = ('|S| (dB)', '|S| (linear)', 'Phase (deg)', 'Group delay (ns)', 'VSWR')     # the rectangular plot
SMITH = 'Smith chart'                                     # the reflections beside it
DIFF_KINDS = ('Δ|S| (dB)', '|ΔS| (dB)')                   # one solver against another: |S| apart, and S apart
UNITS = {'|S| (dB)': 'dB', '|S| (linear)': '', 'Phase (deg)': '°', 'Group delay (ns)': 'ns', 'VSWR': '',
         'Smith chart': ''}
SOURCES = (('openEMS', 'solid'), ('mom25d', 'dashdot'), ('qucsator', 'dot'), ('scikit-rf', 'dot'), ('line model', 'dot'),
           ('compare', 'dash'))


class Trace:
    """S(i+1, j+1) of one result file."""
    def __init__(self, source, i, j, f, s, names=None, path=None):
        self.source, self.i, self.j, self.f, self.s, self.path = source, i, j, np.asarray(f), np.asarray(s), path
        self.names = names
        self.style = dict(SOURCES).get(source, 'solid')

    @property
    def param(self):
        """S21; for a file with differential pairs (P1d, P1c: kicad2ems's mixed-mode ports) the modes and the
        pairs' numbers, Sdd21, Scd21, and s for a single-ended port among them (Sds31)."""
        m = modes(self.names)
        if m and max(self.i, self.j) < len(m):
            (mi, ki), (mj, kj) = m[self.i], m[self.j]
            return f"S{mi}{mj}{ki}{kj}"
        return f"S{self.i + 1}{self.j + 1}"

    @property
    def label(self):
        return f"{self.param} {self.source}"

    @property
    def title(self):
        """S21 (P2 <- P1) with the port names, when the file has them."""
        if self.names and max(self.i, self.j) < len(self.names):
            return f"{self.param} ({self.names[self.i]} ← {self.names[self.j]})"
        return self.param

    @property
    def empty(self):
        return not np.isfinite(self.s).all() or not np.abs(self.s).any()


def modes(names):
    """[(mode, port number)] per port of a file with differential pairs, or None: a pair's ports are <name>d and
    <name>c (its differential and common modes, as kicad2ems writes them), 'd' and 'c' at the pair's number; any
    other port is single-ended, 's'. Ports are numbered in order of first appearance, a pair once."""
    if not names:
        return None
    pairs = {n[:-1] for n in names if n.endswith('d') and n[:-1] + 'c' in names}
    if not pairs:
        return None
    out, order = [], []
    for n in names:
        base, mode = (n[:-1], n[-1]) if n[:-1] in pairs and n[-1] in 'dc' else (n, 's')
        if base not in order:
            order.append(base)
        out.append((mode, order.index(base) + 1))
    return out


def port_names(path):
    """Port names from the '! ports: 1=P1, 2=P2' comment kicad2ems writes, or None."""
    try:
        with open(path) as fh:
            for line in fh:
                if not line.startswith('!'):
                    break
                m = re.match(r'!\s*ports:\s*(.*)', line)
                if m:
                    return [p.split('=', 1)[1].strip() for p in m.group(1).split(',') if '=' in p]
    except OSError:
        pass
    return None


BY_SUFFIX = dict(openems='openEMS', mom25d='mom25d', qucs='qucsator', scikit='scikit-rf',
                 mom='mom25d', fast='line model')             # the last two: file names of older runs


def classify(path):
    """The source of a Touchstone file of a run, from its name (<name>_<solver>.sNp)."""
    m = re.search(r'_([A-Za-z0-9-]+)\.s\d+p$', os.path.basename(path))
    if m and m.group(1) in BY_SUFFIX:
        return BY_SUFFIX[m.group(1)]
    from kicad2ems.api.frontend import registry
    return m.group(1) if m and m.group(1) in registry() else 'openEMS'


def load_traces(files, compare=None):
    """Traces of every Touchstone file in (label, path) files (a run's file list), plus a compare file."""
    from kicad2ems.api.frontend import read_touchstone
    paths = [p for _, p in files if re.search(r'\.s\d+p$', p) and os.path.exists(p)]
    seen, out = set(), []
    items = [(classify(p), p) for p in paths]
    if compare and os.path.exists(compare):
        items.append(('compare', compare))
    for source, p in items:
        if p in seen:
            continue
        seen.add(p)
        f, S = read_touchstone(p)
        names = port_names(p)
        n = S.shape[1]
        out += [Trace(source, i, j, f, S[:, i, j], names, p) for j in range(n) for i in range(n)]
    order = {s: k for k, (s, _) in enumerate(SOURCES)}
    out.sort(key=lambda t: (order.get(t.source, 9), t.j, t.i))
    return out


def default_visible(tr):
    """Shown at first: the first port's column (S11, S21, S31, ...: what a run driving P1 computes)."""
    return tr.j == 0 and not tr.empty


def group_delay(f, s):
    ph = np.unwrap(np.angle(s))
    return -np.gradient(ph, 2 * np.pi * f) * 1e9


def transform(kind, tr):
    """(x, y) a plot kind shows of a trace: frequency (GHz) and value, or Re / Im for the Smith chart."""
    s = tr.s
    if kind == 'Smith chart':
        return s.real, s.imag
    x = tr.f / 1e9
    if kind == '|S| (dB)':
        y = 20 * np.log10(np.abs(s) + 1e-15)
    elif kind == '|S| (linear)':
        y = np.abs(s)
    elif kind == 'Phase (deg)':
        y = np.degrees(np.angle(s))
    elif kind == 'Group delay (ns)':
        y = group_delay(tr.f, s)
    elif kind == 'VSWR':
        a = np.minimum(np.abs(s), 0.999999)
        y = (1 + a) / (1 - a)
    else:
        raise ValueError(f"unknown plot kind {kind!r}")
    return x, y


def difference(kind, tr, ref):
    """(x, y) of trace tr against ref (the same S of another solver), on tr's frequencies (GHz): Δ|S| (dB), the
    difference of their magnitudes in dB, or |ΔS| (dB), the magnitude of the complex difference (the error
    vector) in dB. NaN outside ref's band."""
    f = tr.f
    inside = (f >= ref.f[0]) & (f <= ref.f[-1])
    r = np.interp(f, ref.f, ref.s.real) + 1j * np.interp(f, ref.f, ref.s.imag)
    if kind == DIFF_KINDS[0]:
        y = 20 * np.log10(np.abs(tr.s) + 1e-15) - 20 * np.log10(np.abs(r) + 1e-15)
    elif kind == DIFF_KINDS[1]:
        y = 20 * np.log10(np.abs(tr.s - r) + 1e-15)
    else:
        raise ValueError(f"unknown difference {kind!r}")
    return f / 1e9, np.where(inside, y, np.nan)


def counterpart(traces, tr, source):
    """The trace of `source` with tr's S (the same i, j), or None."""
    return next((t for t in traces if t.source == source and (t.i, t.j) == (tr.i, tr.j)), None)


def value_at(kind, tr, f):
    """The value of a trace at frequency f (Hz), interpolated; NaN outside its band. Smith: complex S."""
    if f < tr.f[0] or f > tr.f[-1]:
        return np.nan
    if kind == 'Smith chart':
        return np.interp(f, tr.f, tr.s.real) + 1j * np.interp(f, tr.f, tr.s.imag)
    x, y = transform(kind, tr)
    return float(np.interp(f / 1e9, x, y))


def fmt_value(kind, v, z0=50.0):
    if isinstance(v, complex) or np.iscomplexobj(v):
        if not np.isfinite(v):
            return '–'
        z = z0 * (1 + v) / (1 - v) if abs(1 - v) > 1e-12 else complex(np.inf)
        return f"|S| {abs(v):.3f} ∠{np.degrees(np.angle(v)):.1f}°, Z {z.real:.1f}{z.imag:+.1f}j Ω"
    if not np.isfinite(v):
        return '–'
    return f"{v:.3f} {UNITS[kind]}".strip() if kind != '|S| (dB)' else f"{v:.2f} dB"


def nearest(trs, x, y):
    """The trace and frequency index nearest to a point of the Smith chart."""
    best = (np.inf, None, None)
    for t in trs:
        d = np.hypot(t.s.real - x, t.s.imag - y)
        k = int(np.argmin(d))
        if d[k] < best[0]:
            best = (d[k], t, k)
    return best[1], best[2]


def smith_grid(n=181):
    """Polylines (x, y) of a Smith chart grid: constant-resistance circles and constant-reactance arcs."""
    lines = []
    t = np.linspace(0, 2 * np.pi, n)
    for r in (0, 0.2, 0.5, 1, 2, 5):
        c, rad = r / (1 + r), 1 / (1 + r)
        lines.append((c + rad * np.cos(t), rad * np.sin(t)))
    for x in (0.2, 0.5, 1, 2, 5):
        for sx in (x, -x):
            g = (np.linspace(0, 50, 400) + 1j * sx)               # z = r + jx, r from 0 to 50
            gam = (g - 1) / (g + 1)
            lines.append((gam.real, gam.imag))
    lines.append((np.array([-1, 1]), np.array([0, 0])))
    return lines


def polar_grid(rings=(0.25, 0.5, 0.75, 1.0), spokes=12, n=181):
    """Polylines (x, y) of a polar grid: circles of the given radii and `spokes` radial lines out to the largest."""
    t = np.linspace(0, 2 * np.pi, n)
    lines = [(r * np.cos(t), r * np.sin(t)) for r in rings]
    R = max(rings)
    for k in range(spokes):
        a = 2 * np.pi * k / spokes
        lines.append((np.array([0, R * np.cos(a)]), np.array([0, R * np.sin(a)])))
    return lines


def pattern_xy(angles_deg, gain, lo_db, range_db):
    """A far-field cut on a polar plot: angle 0 at the top, clockwise; the radius 0 at lo_db, 1 at lo_db +
    range_db. gain linear. Returns (x, y)."""
    db = 10 * np.log10(np.maximum(np.asarray(gain, float), 1e-12))
    r = np.clip((db - lo_db) / range_db, 0, 1)
    a = np.radians(np.asarray(angles_deg, float))
    return r * np.sin(a), r * np.cos(a)


def export_csv(path, trs, kind, reflections=()):
    """The traces as a kind shows them, plus Re / Im of the Smith chart's reflections, on the frequency grid of
    the first trace (the others interpolated; NaN outside their band)."""
    if not trs:
        raise ValueError("no traces shown")
    f = trs[0].f
    cols, head = [f / 1e9], ['f_GHz']
    for t in trs:
        x, y = transform(kind, t)
        cols.append(np.interp(f / 1e9, x, y, left=np.nan, right=np.nan))
        head.append(f"{t.label} {UNITS[kind]}".strip())
    for t in reflections:
        cols += [np.interp(f, t.f, t.s.real, left=np.nan, right=np.nan),
                 np.interp(f, t.f, t.s.imag, left=np.nan, right=np.nan)]
        head += [f"{t.label} re", f"{t.label} im"]
    np.savetxt(path, np.column_stack(cols), delimiter=',', header=','.join(head), comments='', fmt='%.9g')
