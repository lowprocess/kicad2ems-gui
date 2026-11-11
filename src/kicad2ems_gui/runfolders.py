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

STAMP = '%Y%m%d_%H%M%S'


def board_name(board):
    """The name a board's folders take: its file name without the extension (and a resolved board's _board)."""
    name = os.path.splitext(os.path.basename(board or 'board'))[0]
    return name[:-len('_board')] if name.endswith('_board') else name


def run_dir(base, board, now=None):
    return os.path.join(base, f"{board_name(board)}_{(now or datetime.datetime.now()).strftime(STAMP)}")


def preview_dir(base, board):
    return os.path.join(base, f"{board_name(board)}_preview")


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


TOOL_RESULTS = {'pdn': 'pdn.json', 'mqs': 'mqs.json'}               # the file a finished run of each wrote
TOOL_TITLES = {'pdn': 'Power integrity', 'mqs': 'Near field'}


def _tag(text):
    return ''.join(c if c.isalnum() else '_' for c in str(text or '')).strip('_') or 'run'


def tool_dir(base, board, kind, name, now=None):
    return os.path.join(base, f"{board_name(board)}_{kind}_{_tag(name)}_{(now or datetime.datetime.now()).strftime(STAMP)}")


def tool_preview_dir(base, board, kind):
    return os.path.join(base, f"{board_name(board)}_{kind}_preview")


def tool_kind(folder):
    """'pdn' or 'mqs' when the folder holds that tool's result, else None."""
    return next((k for k, f in TOOL_RESULTS.items() if os.path.isfile(os.path.join(folder or '', f))), None)


def tool_runs(base, board):
    """This board's Power integrity and Near field results, the newest first: [(folder, kind, label)], label what
    was solved (the rail, the converter) and when. Under base: a folder per run; beside the board: the single
    pdn_<rail> / mqs_<converter> folders those tools wrote to before."""
    name = board_name(board)
    out = []
    pat = re.compile(re.escape(name) + r'_(pdn|mqs)_(.+)_(\d{8}_\d{6})$')
    for d in glob.glob(os.path.join(base, f"{glob.escape(name)}_*")):
        m = pat.match(os.path.basename(d))
        if m and tool_kind(d) == m.group(1):
            when = datetime.datetime.strptime(m.group(3), STAMP)
            out.append((when, d, m.group(1), f"{TOOL_TITLES[m.group(1)]}: {m.group(2)}, {when:%Y-%m-%d %H:%M:%S}"))
    beside = os.path.dirname(os.path.abspath(board)) if board else None
    for kind, result in TOOL_RESULTS.items() if beside else ():
        for f in glob.glob(os.path.join(glob.escape(beside), f"{kind}_*", result)):
            d = os.path.dirname(f)
            when = datetime.datetime.fromtimestamp(os.path.getmtime(f))
            out.append((when, d, kind, f"{TOOL_TITLES[kind]}: {os.path.basename(d)[len(kind) + 1:]}, {when:%Y-%m-%d %H:%M:%S}"))
    return [(d, kind, label) for _when, d, kind, label in sorted(out, key=lambda r: r[0], reverse=True)]
