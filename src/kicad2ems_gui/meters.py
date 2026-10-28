"""
Live memory for the GUI's status bar (no Qt here: testable without a display). All cheap enough to read every
couple of seconds; the GPU through its vendor's tool, run by the caller as a separate process, so the GUI never
holds a GPU context or imports CuPy.

    ram()                    (used, total) GB of the system (Linux: /proc/meminfo; elsewhere what sysconf gives)
    tree_rss(pid)            GB resident in a process and its children (Linux), or None
    gpu_command()            [program, args...] that prints the GPU's memory (nvidia-smi / rocm-smi), or None
    parse_gpu(name, text)    [(used, total) GB per GPU] from that program's output
    estimate(est, values, usable)  what the next run should take: the solvers it runs, their time and memory
"""
import json, os, shutil


def ram(meminfo='/proc/meminfo'):
    """(used, total) of the system's memory in GB: used = total - available (what other programs can still
    have). None where neither /proc/meminfo nor sysconf can tell."""
    try:
        kb = {}
        with open(meminfo) as fh:
            for line in fh:
                k, _, v = line.partition(':')
                if k in ('MemTotal', 'MemAvailable'):
                    kb[k] = float(v.split()[0])
        total, avail = kb['MemTotal'] / 1e6 * 1.024, kb['MemAvailable'] / 1e6 * 1.024     # kiB -> GB
        return total - avail, total
    except (OSError, KeyError, ValueError, IndexError):
        pass
    try:
        page = os.sysconf('SC_PAGE_SIZE')
        total = page * os.sysconf('SC_PHYS_PAGES') / 1e9
        avail = page * os.sysconf('SC_AVPHYS_PAGES') / 1e9
        return total - avail, total
    except (ValueError, OSError, AttributeError):
        return None


def _children(proc='/proc'):
    """{parent pid: [child pids]} of every process (Linux)."""
    kids = {}
    for d in os.listdir(proc):
        if not d.isdigit():
            continue
        try:
            with open(os.path.join(proc, d, 'stat')) as fh:
                stat = fh.read()
            ppid = int(stat[stat.rindex(')') + 2:].split()[1])      # the name may hold spaces and brackets
        except (OSError, ValueError, IndexError):
            continue
        kids.setdefault(ppid, []).append(int(d))
    return kids


def tree_rss(pid, proc='/proc'):
    """GB resident in a process and all its descendants (a run: the kicad2ems process, its --jobs workers and
    openEMS); None where /proc cannot tell (not Linux, or the process is gone)."""
    if not pid or not os.path.isdir(os.path.join(proc, str(pid))):
        return None
    kids, total, todo, seen = _children(proc), 0.0, [int(pid)], set()
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        try:
            with open(os.path.join(proc, str(p), 'status')) as fh:
                for line in fh:
                    if line.startswith('VmRSS:'):
                        total += float(line.split()[1]) * 1.024e-6  # kiB -> GB
                        break
        except OSError:
            continue
        todo += kids.get(p, [])
    return total


def gpu_command():
    """The command that prints the GPU's memory use: nvidia-smi (NVIDIA) or rocm-smi (AMD); None without either."""
    if shutil.which('nvidia-smi'):
        return ['nvidia-smi', '--query-gpu=memory.used,memory.total,name', '--format=csv,noheader,nounits']
    if shutil.which('rocm-smi'):
        return ['rocm-smi', '--showmeminfo', 'vram', '--json']
    return None


def parse_gpu(prog, text):
    """[(used GB, total GB)] per GPU from gpu_command's output (prog: its program name); [] when it can't be read."""
    out = []
    try:
        if os.path.basename(prog).startswith('nvidia-smi'):
            for line in text.strip().splitlines():
                used, total = [float(x) for x in line.split(',')[:2]]   # MiB
                out.append((used * 1.048576e-3, total * 1.048576e-3))
        else:
            d = json.loads(text[text.index('{'):])
            for card in d.values():
                if not isinstance(card, dict):
                    continue
                tot = next((v for k, v in card.items() if 'Total Memory' in k), None)
                used = next((v for k, v in card.items() if 'Used' in k), None)
                if tot is not None and used is not None:
                    out.append((float(used) / 1e9, float(tot) / 1e9))
    except (ValueError, TypeError, IndexError):
        return []
    return out


def estimate(est, values, usable=None, ram_avail=None):
    """What the next run should take, from a preview's estimates (summary['estimates']: {solvers: {name: dict(
    seconds, gb, gpu_gb)}}) and the form's settings (values: solvers as runner.solvers_from_form makes them).

    The full-wave solvers it runs, as the pipeline picks them: those named, or for auto (the default) when none
    is named the one auto would pick, the fastest of those that can run here (usable: names, None for all) and fit
    in 80 % of ram_avail GB. Returns dict(rows=[(name, seconds, gb, gpu_gb, auto)], seconds (summed: they run one
    after the other), gb (the largest), gpu_gb, fits, missing (named solvers without an estimate)), or None when
    no full-wave solver would run or none has an estimate."""
    from kicad2ems.api.frontend import registry, AUTO
    rows = {n: r for n, r in ((est or {}).get('solvers') or {}).items() if n in registry()}
    plan = values.get('solvers')
    plan = [AUTO] if plan is None else list(plan)
    full = {n for n, sv in registry().items() if sv.consumes == 'board'}     # named, even hidden: auto adds none
    named = [n for n in plan if n in full]
    out, missing = [], [n for n in named if n not in rows]
    for n in named:
        if n in rows:
            out.append((n, rows[n].get('seconds', 0.0), rows[n].get('gb', 0.0), rows[n].get('gpu_gb'), False))
    if AUTO in plan and not named:                                  # auto: the one Job.choose would take
        cand = [n for n in rows if (usable is None or n in usable)
                and (ram_avail is None or rows[n].get('gb', 0) <= 0.8 * ram_avail)]
        if cand:
            n = min(cand, key=lambda k: rows[k].get('seconds', float('inf')))
            out.append((n, rows[n].get('seconds', 0.0), rows[n].get('gb', 0.0), rows[n].get('gpu_gb'), True))
    if not out:
        return None
    gb = max(r[2] for r in out)
    gpu = max([r[3] for r in out if r[3]] or [0.0]) or None
    return dict(rows=out, seconds=sum(r[1] for r in out), gb=gb, gpu_gb=gpu, missing=missing,
                fits=ram_avail is None or gb <= 0.8 * ram_avail)


def duration(sec):
    """A short duration: ~40 s, ~4 min, ~1.5 h."""
    if sec < 120:
        return f"~{sec:.0f} s"
    if sec < 7200:
        return f"~{sec / 60:.0f} min"
    return f"~{sec / 3600:.1f} h"
