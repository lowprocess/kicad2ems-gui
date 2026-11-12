#!/usr/bin/env python3
"""
kicad2ems's README and GUI-page pictures, from the examples: runs them (gfdtd, mom25d and the line model, with
field dumps), then takes the window's pages and renders the 3D field views.

    python tools/readme_media.py                 # runs, then every picture
    python tools/readme_media.py --skip-runs     # only the pictures, from the last runs
    python tools/readme_media.py --only hairpin filter

Writes kicad2ems's docs/img/readme/ (the README) and docs/img/gui/ (docs/gui.md), in its checkout (KICAD2EMS_SRC,
default ../kicad2ems; the runs go to its build/readme/). Needs PySide6, pyqtgraph and dfsynth; the 3D views also
PyOpenGL and a display (with QT_QPA_PLATFORM=offscreen they are left out).
"""
import argparse, glob, os, shutil, subprocess, sys, time

REPO = os.environ.get('KICAD2EMS_SRC') or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'kicad2ems')                      # kicad2ems's checkout: its examples and docs
IMG, GUI = os.path.join(REPO, 'docs', 'img', 'readme'), os.path.join(REPO, 'docs', 'img', 'gui')
RUNS = os.path.join(REPO, 'build', 'readme')

# name: (example, extra arguments)
CASES = {
    'hairpin': ('hairpin', ['--solvers', 'gfdtd,mom25d,qucs']),
    'stub': ('rf_stubnotch', ['--solvers', 'gfdtd,mom25d', '--dump', 'E@volume+3@2.4', '--mom-dump', '2.4',
                              '--dump-animate', 'gif']),
    'patch': ('antenna_patch', ['--solvers', 'gfdtd,mom25d', '--dump', 'E@volume+12@2.45']),
}


def run_cases(only):
    for name, (ex, args) in CASES.items():
        if only and name not in only:
            continue
        out = os.path.join(RUNS, name)
        cmd = [sys.executable, '-m', 'kicad2ems', os.path.join(REPO, 'examples', ex + '.toml'), '--no-report',
               '--out', out] + args
        print(f"run {name}: {' '.join(cmd[2:])}", flush=True)
        t = time.time()
        with open(os.path.join(RUNS, name + '.log'), 'w') as log:
            p = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
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
    from kicad2ems_gui import application
    from kicad2ems_gui.app import MainWindow
    app = application()

    def pump(n=20):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.03)

    def window(case, size=(1600, 950)):
        """The window with the case's config in the settings and its run in the pages (no preview of its own)."""
        w = MainWindow(os.path.join(REPO, 'examples', CASES[case][0] + '.toml'))
        pump()                                                      # not on the screen yet: no automatic preview
        w.resize(*size)
        w.show()
        pump()
        w.reset_layout()
        w.open_results(os.path.join(RUNS, case), quiet=True)
        if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':        # no 3D there: the board from above
            w.viewer.set_view('Plan')
        pump(40)
        return w

    def shot(w, path, page=None, view=None):
        """The window with `page` in front (and the Viewer's `view`), saved to path (None: only shown). A page
        under the board gets most of the workspace's height, the board the rest; the board's own pictures the
        other way round."""
        if page:
            w.show_panel(page)
            from PySide6.QtCore import Qt
            h = w.work.height()
            lower = page in ('Results', 'Run')
            w.work.resizeDocks([w.docks['Viewer'], w.docks['Results']],
                               [int(0.3 * h), int(0.7 * h)] if lower else [int(0.78 * h), int(0.22 * h)], Qt.Vertical)
        if view:
            w.viewer.set_view(view)
        pump(30)
        if path:
            w.grab().save(path)
            print(f"  {os.path.relpath(path, REPO)}")

    def close(w):
        w.setup.dirty = False
        w.close()

    gl = os.environ.get('QT_QPA_PLATFORM') != 'offscreen'
    if not only or 'hairpin' in only:
        w = window('hairpin')
        shot(w, os.path.join(IMG, 'gui_sparams.png'), 'Results')
        w.viewer.plan.mesh.setCurrentIndex(max(0, w.viewer.plan.mesh.findData('mom25d')))
        w.viewer.lines_on.setChecked(False)                         # the mesh, not the sections over it
        shot(w, None, 'Viewer', 'Plan')
        w.viewer.plan.plot.setRange(xRange=(3.2, 9.4), yRange=(-14.0, -9.6), padding=0)   # one U's bottom, close up
        shot(w, os.path.join(IMG, 'gui_mesh.png'))
        w.viewer.lines_on.setChecked(True)
        els = (w.viewer.lines or {}).get('elements', [])
        pick = next((e for e in els if e.get('section') and e.get('group') is not None),       # a coupled pair
                    next((e for e in els if e.get('section')), None))
        if pick is not None:
            w.viewer.select(pick['id'])
            shot(w, os.path.join(GUI, 'section.png'), 'Viewer', 'Section')
        close(w)
    if not only or 'patch' in only:
        w = window('patch')
        shot(w, os.path.join(IMG, 'gui_antenna.png'), 'Results')
        if gl and w.volume.gl is not None:
            v = w.volume
            v.zscale.setValue(1.0)
            v.decades.setValue(1.2)
            v.clip.setValue(99.0)
            v.gamma.setValue(22)                                    # the near field above the patch: thinned out
            v.opacity.setValue(70)
            shot(w, None, 'Viewer', '3D')
            v.reset_camera()
            pump(30)
            tmp = os.path.join(RUNS, 'patch_3d.gif')
            v.save(tmp, fps=12, orbit=40)
            gif_resized(tmp, os.path.join(IMG, 'patch_3d.gif'))
            print("  docs/img/readme/patch_3d.gif")
        close(w)
    if not only or 'stub' in only:
        if gl:
            w = window('stub')
            v = w.volume
            if v.gl is not None:
                v.log.setChecked(False)
                v.zscale.setValue(2.0)
                v.opacity.setValue(90)
                v.gamma.setValue(10)
                shot(w, None, 'Viewer', '3D')
                v.reset_camera()
                v.view.setCameraPosition(azimuth=-70, elevation=28)
                pump(30)
                tmp = os.path.join(RUNS, 'stub_3d.gif')
                v.save(tmp, fps=12)
                gif_resized(tmp, os.path.join(IMG, 'stub_3d.gif'))
                print("  docs/img/readme/stub_3d.gif")
            close(w)
        # mom25d's surface-current standing wave (written by the run: --mom-dump 2.4 --dump-animate gif)
        for f in glob.glob(os.path.join(RUNS, 'stub', '*mom25d*_J_F_Cu_fd_2.4GHz.gif')):
            gif_resized(f, os.path.join(IMG, 'stub_current.gif'), width=720)
            print("  docs/img/readme/stub_current.gif")
    if not only or 'filter' in only:
        from kicad2ems_gui import filtertab as ft
        from dfsynth.cli import main as dfsynth
        base = os.path.join(RUNS, 'filter', 'hairpin_2g4')
        os.makedirs(os.path.dirname(base), exist_ok=True)
        args = dict(type='bandpass', topology='hairpin', f0='2.4G', bw='240M', substrate='RO4003C-0.813')
        dfsynth([a for k, v in args.items() for a in (f'--{k}', v)] + ['-o', base])
        w = MainWindow()
        w.resize(1500, 900)
        w.show()
        w.filter.set_values(dict(args, out=base))
        w.filter.show_result(ft.load_design(base))
        shot(w, os.path.join(GUI, 'filter.png'), 'Filter')
        close(w)


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
    ap.add_argument('--skip-runs', action='store_true', help="render from the runs already in build/readme/")
    ap.add_argument('--only', nargs='*', choices=list(CASES) + ['filter'], help="these cases only")
    a = ap.parse_args()
    for d in (IMG, GUI, RUNS):
        os.makedirs(d, exist_ok=True)
    if not a.skip_runs:
        run_cases(a.only)
    print("images:")
    copies(a.only)
    gui_media(a.only)


if __name__ == '__main__':
    main()
