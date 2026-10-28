#!/usr/bin/env python3
"""
The README's images and animations, from the examples: runs them (openEMS, mom25d and the line model, with field
dumps), then takes the GUI's panels and renders the 3D field views.

    python tools/readme_media.py --openems-python /opt/openems/venv/bin/python
    python tools/readme_media.py --skip-runs            # only re-render from the last runs

Writes kicad2ems's docs/img/readme/*.png and *.gif, in its checkout (KICAD2EMS_SRC, default ../kicad2ems; the runs
go to its build/readme/). The GUI part needs PySide6, pyqtgraph and
PyOpenGL in this Python and a display (OpenGL); openEMS may live in another Python (--openems-python), which also
needs kicad2ems importable (run from the checkout: PYTHONPATH is set to its src/).
"""
import argparse, glob, os, shutil, subprocess, sys, time

REPO = os.environ.get('KICAD2EMS_SRC') or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'kicad2ems')                      # kicad2ems's checkout: its examples and docs
IMG = os.path.join(REPO, 'docs', 'img', 'readme')
RUNS = os.path.join(REPO, 'build', 'readme')

# name: (example, extra arguments)
CASES = {
    'hairpin': ('hairpin', ['--solvers', 'openems,mom25d']),
    'stub': ('rf_stubnotch', ['--solvers', 'openems,mom25d', '--dump', 'E@volume+3@2.4', '--mom-dump', '2.4',
                              '--dump-animate', 'gif']),
    'patch': ('antenna_patch', ['--solvers', 'openems,mom25d', '--dump', 'E@volume+12@2.45']),
}


def run_cases(py, only):
    env = dict(os.environ, PYTHONPATH=os.path.join(REPO, 'src') + os.pathsep + os.environ.get('PYTHONPATH', ''))
    for name, (ex, args) in CASES.items():
        if only and name not in only:
            continue
        out = os.path.join(RUNS, name)
        cmd = [py, '-m', 'kicad2ems', os.path.join(REPO, 'examples', ex + '.toml'), '--no-report', '--out', out] + args
        print(f"run {name}: {' '.join(cmd[2:])}", flush=True)
        t = time.time()
        with open(os.path.join(RUNS, name + '.log'), 'w') as log:
            p = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
        print(f"  {'ok' if p.returncode == 0 else f'FAILED ({p.returncode}): see build/readme/{name}.log'} "
              f"({time.time() - t:.0f} s)", flush=True)


def gif_resized(src, dst, width=720, every=1):
    """Copy a GIF at `width` pixels (and every n-th frame): README-sized."""
    from PIL import Image
    im = Image.open(src)
    frames, dur = [], im.info.get('duration', 80)
    for k in range(0, im.n_frames, every):
        im.seek(k)
        f = im.convert('RGB')
        frames.append(f.resize((width, round(f.height * width / f.width)), Image.LANCZOS))
    frames[0].save(dst, save_all=True, append_images=frames[1:], duration=dur * every, loop=0, optimize=True)
    return dst


def gui_media(only):
    os.environ.setdefault('QT_QPA_PLATFORM', os.environ.get('QT_QPA_PLATFORM', ''))
    from kicad2ems_gui import application
    from kicad2ems_gui.app import MainWindow
    app = application()

    def pump(n=20):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.03)

    def window(out, size=(1500, 900)):
        w = MainWindow()
        w.resize(*size)
        w.show()
        pump()
        w.docks['System'].hide()
        w.open_results(out, quiet=True)
        pump(40)
        return w

    def shot(w, panel, path):
        w.show_panel(panel)
        pump(30)
        w.grab().save(path)
        print(f"  {os.path.relpath(path, REPO)}")

    if not only or 'hairpin' in only:
        w = window(os.path.join(RUNS, 'hairpin'))
        shot(w, 'S-parameters', os.path.join(IMG, 'gui_sparams.png'))
        shot(w, 'Model and mesh', os.path.join(IMG, 'gui_mesh.png'))
        w.close()
    if not only or 'patch' in only:
        w = window(os.path.join(RUNS, 'patch'))
        shot(w, 'Antenna', os.path.join(IMG, 'gui_antenna.png'))
        v = w.volume
        v.zscale.setValue(1.0)
        v.decades.setValue(1.2)
        v.clip.setValue(99.0)
        v.gamma.setValue(22)                                        # the near field above the patch: thinned out
        v.opacity.setValue(70)
        w.show_panel('3D fields')
        v.reset_camera()
        pump(30)
        tmp = os.path.join(RUNS, 'patch_3d.gif')
        v.save(tmp, fps=12, orbit=40)
        gif_resized(tmp, os.path.join(IMG, 'patch_3d.gif'))
        print("  docs/img/readme/patch_3d.gif")
        w.close()
    if not only or 'stub' in only:
        w = window(os.path.join(RUNS, 'stub'))
        v = w.volume
        v.log.setChecked(False)
        v.zscale.setValue(2.0)
        v.opacity.setValue(90)
        v.gamma.setValue(10)
        w.show_panel('3D fields')
        v.reset_camera()
        v.view.setCameraPosition(azimuth=-70, elevation=28)
        pump(30)
        tmp = os.path.join(RUNS, 'stub_3d.gif')
        v.save(tmp, fps=12)
        gif_resized(tmp, os.path.join(IMG, 'stub_3d.gif'))
        print("  docs/img/readme/stub_3d.gif")
        w.close()
        # mom25d's surface-current standing wave (written by the run: --mom-dump 2.4 --dump-animate gif)
        for f in glob.glob(os.path.join(RUNS, 'stub', '*mom25d*_J_F_Cu_fd_2.4GHz.gif')):
            gif_resized(f, os.path.join(IMG, 'stub_current.gif'), width=720)
            print("  docs/img/readme/stub_current.gif")


def copies(only):
    """Plots the runs wrote, as they are."""
    pick = {'hairpin': ['hairpin_tlines.png']}
    for name, files in pick.items():
        if only and name not in only:
            continue
        for f in files:
            src = os.path.join(RUNS, name, f)
            if os.path.exists(src):
                shutil.copy(src, os.path.join(IMG, f))
                print(f"  docs/img/readme/{f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument('--openems-python', default=sys.executable, help="the Python with openEMS (default: this one)")
    ap.add_argument('--skip-runs', action='store_true', help="render from the runs already in build/readme/")
    ap.add_argument('--only', nargs='*', choices=list(CASES), help="these cases only")
    a = ap.parse_args()
    os.makedirs(IMG, exist_ok=True)
    os.makedirs(RUNS, exist_ok=True)
    if not a.skip_runs:
        run_cases(a.openems_python, a.only)
    print("images:")
    copies(a.only)
    gui_media(a.only)


if __name__ == '__main__':
    main()
