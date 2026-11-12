"""
Where the GUI's runs go: each in a folder of its own under the output folder, named after the board and the date
and time it started, and a preview in one folder per board that each preview refreshes. A folder then only ever
holds one board's results (a shared one had shown another board's dumps after opening a config).

    run_dir(base, board)          # <base>/<board>_20261013_141502
    preview_dir(base, board)      # <base>/<board>_preview
    runs(base, board)             # [(folder, label)], the newest first: this board's runs that wrote a summary

The other analyses' tools (pcbqs's: 'pdn', 'mqs') get a folder per run there too, so two runs of a rail can be
compared; their results from before that (pdn_<rail>, mqs_<converter> beside the board) are still found.

    tool_dir(base, board, kind, name)     # <base>/<board>_pdn_<rail>_20261013_141502
    tool_preview_dir(base, board, kind)   # <base>/<board>_mqs_preview
    tool_runs(base, board)                # [(folder, kind, label)], the newest first: those that wrote a result
"""
import datetime, glob, os, re
# the folders' names are kicad2ems's (its `kicad2ems study` puts its runs there too): kicad2ems.runs
from kicad2ems.api.frontend import board_name, run_dir, preview_dir, tool_dir, tool_preview_dir      # noqa: F401

STAMP = '%Y%m%d_%H%M%S'


def runs(base, board):
    """This board's run folders under base, the newest first: [(folder, label)], label the start time and the
    solvers of its summary (<name>_run.json)."""
    name = board_name(board)
    pat = re.compile(re.escape(name) + r'_(\d{8}_\d{6})$')
    out = []
    for d in glob.glob(os.path.join(base, f"{glob.escape(name)}_*")):
        m = pat.match(os.path.basename(d))
        if not m or not os.path.isdir(d):
            continue
        summary = os.path.join(d, f"{name}_run.json")
        if not os.path.exists(summary):                             # stopped before it wrote anything
            continue
        when = datetime.datetime.strptime(m.group(1), STAMP)
        try:
            from kicad2ems.api.frontend import read_summary
            solvers = read_summary(summary).get('solvers') or []
        except (OSError, ValueError):
            solvers = []
        out.append((d, f"{when:%Y-%m-%d %H:%M:%S}" + (f" ({', '.join(solvers)})" if solvers else '')))
    return sorted(out, key=lambda r: os.path.basename(r[0]), reverse=True)


def tool_titles():
    """{kind: title} of the analyses whose runs are listed: those kicad2ems's registry holds, in its order."""
    from kicad2ems.api.frontend import analyses
    return {name: a.label for name, a in analyses().items()}




def tool_kind(folder):
    """The analysis ('pdn', 'thermal' ...) whose finished result the folder holds, else None (a preview's too)."""
    from kicad2ems.api.frontend import analysis_of
    made = analysis_of(folder or '')
    return made[0] if made and not made[1] else None


def tool_runs(base, board):
    """This board's analysis results (Power integrity, Near field, Circuit, Thermal: what the registry holds), the
    newest first: [(folder, kind, label)], label what was solved (the rail, the converter) and when. Under base:
    a folder per run; beside the board: the single pdn_<rail> / mqs_<converter> folders those tools wrote to
    before."""
    name = board_name(board)
    out = []
    TOOL_TITLES = tool_titles()
    if not TOOL_TITLES:
        return out
    pat = re.compile(re.escape(name) + r'_(' + '|'.join(map(re.escape, TOOL_TITLES)) + r')_(.+)_(\d{8}_\d{6})$')
    for d in glob.glob(os.path.join(base, f"{glob.escape(name)}_*")):
        m = pat.match(os.path.basename(d))
        if m and tool_kind(d) == m.group(1):
            when = datetime.datetime.strptime(m.group(3), STAMP)
            out.append((when, d, m.group(1), f"{TOOL_TITLES[m.group(1)]}: {m.group(2)}, {when:%Y-%m-%d %H:%M:%S}"))
    beside = os.path.dirname(os.path.abspath(board)) if board else None
    for kind in TOOL_TITLES if beside else ():
        for d in glob.glob(os.path.join(glob.escape(beside), f"{kind}_*")):
            if tool_kind(d) != kind:
                continue
            when = datetime.datetime.fromtimestamp(os.path.getmtime(d))
            out.append((when, d, kind, f"{TOOL_TITLES[kind]}: {os.path.basename(d)[len(kind) + 1:]}, {when:%Y-%m-%d %H:%M:%S}"))
    tools = list(TOOL_TITLES)
    out.sort(key=lambda r: (tools.index(r[2]), r[3]))                   # runs of one moment: in the tools' order
    out.sort(key=lambda r: r[0], reverse=True)                          # newest first (a stable sort keeps the rest)
    return [(d, kind, label) for _when, d, kind, label in out]
