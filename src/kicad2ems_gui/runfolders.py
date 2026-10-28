"""
Where the GUI's runs go: each in a folder of its own under the output folder, named after the board and the date
and time it started, and a preview in one folder per board that each preview refreshes. A folder then only ever
holds one board's results (a shared one had shown another board's dumps after opening a config).

    run_dir(base, board)          # <base>/<board>_20261013_141502
    preview_dir(base, board)      # <base>/<board>_preview
    runs(base, board)             # [(folder, label)], the newest first: this board's runs that wrote a summary
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
