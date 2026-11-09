"""
A page's tool as a child process (pcbqs's PDN, near-field and circuit tools, dfsynth): the page never imports it.

    describe_tool(python, args, name, install)   (its --describe --json, or None; why not), asked once
    run_tool(page, argv, on_output, on_finished) page.proc: a QProcess running argv, its output merged
"""
import json
import subprocess
import sys

_DESCRIPTIONS = {}


def describe_tool(python, args, name, install, fmt=1, too_old=None):
    """(description, '') from `python <args> --describe --json`, or (None, why it cannot run here): not installed
    (`install` says how), too old to describe itself (`too_old`, when given), or in another format than `fmt`."""
    key = (python or sys.executable, *args)
    if key not in _DESCRIPTIONS:
        d, why = None, ''
        try:
            p = subprocess.run([*key, '--describe', '--json'], capture_output=True, text=True, timeout=60)
            if p.returncode == 0:
                d = json.loads(p.stdout)
                if d.get('format') != fmt:
                    newer = (d.get('format') or 0) > fmt
                    d, why = None, (f"{name} {d.get('version', '?')} describes itself in format {d.get('format')}, "
                                    f"this page reads {fmt}: update {'kicad2ems-gui' if newer else name}")
            elif 'No module named' in p.stderr:
                why = f"{name} is not installed here: {install}"
            elif too_old and '--describe' in p.stderr:                  # argparse: unrecognized arguments
                why = too_old
            else:
                why = f"{name} --describe failed: {(p.stderr.strip().splitlines() or ['?'])[-1]}"
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            why = f"{name} --describe failed: {type(e).__name__}: {e}"
        _DESCRIPTIONS[key] = (d, why)
    return _DESCRIPTIONS[key]


def run_tool(page, argv, on_output, on_finished, cwd=None, env=None):
    """Start argv as page.proc (unbuffered Python output, stdout and stderr merged, `env` added). When it cannot
    start, page.say (if it has one) gets why and on_finished(-1, None) runs."""
    from PySide6.QtCore import QProcess, QProcessEnvironment
    proc = page.proc = QProcess(page)
    proc.setProcessChannelMode(QProcess.MergedChannels)
    e = QProcessEnvironment.systemEnvironment()
    for k, v in {'PYTHONUNBUFFERED': '1', **(env or {})}.items():
        e.insert(k, v)
    proc.setProcessEnvironment(e)
    if cwd:
        proc.setWorkingDirectory(cwd)
    proc.readyReadStandardOutput.connect(on_output)
    proc.finished.connect(on_finished)

    def failed(error):
        if error == QProcess.FailedToStart:
            if hasattr(page, 'say'):
                page.say(proc.errorString())
            on_finished(-1, None)
    proc.errorOccurred.connect(failed)
    proc.start(argv[0], argv[1:])
    return proc
