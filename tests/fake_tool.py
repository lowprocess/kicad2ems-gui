"""The stand-in analyses' tool (fake_analyses.py): `fake_tool.py KIND OUT VALUES-JSON` says a line or two as a real
one does and writes KIND's result in OUT; a rail named FAIL fails; `fake_tool.py find BOARD` lists two converters."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_analyses                                                # noqa: E402

kind = sys.argv[1]
if kind == 'find':
    print('reading the board')
    print(json.dumps([dict(label='U7: VIN (inductor L3)', values=dict(converter='U7', vin='VIN')),
                      dict(label='U9: +5V (inductor L4)', values=dict(converter='U9', vin='+5V'))]))
    sys.exit(0)
fake_analyses.install()
out, v = sys.argv[2], json.loads(sys.argv[3])
print(f"{kind}: reading the board", flush=True)
if v.get('rail') == 'SLOW':                                         # as a tool that starts a solver: SIGTERM stops
    import signal, subprocess, time                                 # its child, then the tool
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    open(os.path.join(os.path.dirname(out) or '.', 'child.pid'), 'w').write(str(child.pid))

    def on_term(*_):
        child.terminate()
        child.wait()
        print(f"{kind}: stopped what it started", flush=True)
        sys.exit(143)
    signal.signal(signal.SIGTERM, on_term)
    print(f"{kind}: solving", flush=True)
    time.sleep(60)
if v.get('rail') == 'FAIL':
    print(f"{kind}: error: the rail has no copper", file=sys.stderr, flush=True)
    sys.exit(3)
fake_analyses.write(kind, out, preview=bool(v.get('_preview')), **{k: x for k, x in v.items() if k != '_preview'})
print(f"{kind}: solved", flush=True)
