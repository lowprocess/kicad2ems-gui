"""
A results folder's antenna results (mode = antenna), for the GUI: the run's <name>[_<solver>]_antenna.json and its
far-field sphere (openEMS's <out>/openems/exc_<port>/nf2ff_sphere.h5, or mom25d's .npz). The Results page plots
them (match, gain, efficiency, pattern cuts); the Viewer draws the pattern in 3D over the board.
"""
import glob, json, os
import numpy as np
from kicad2ems.api.frontend import read_sphere


def antenna_files(out_dir):
    """The antenna results (<name>[_<solver>]_antenna.json) of a folder, the newest last."""
    return sorted(glob.glob(os.path.join(out_dir, '*_antenna.json')), key=os.path.getmtime)


def find_antenna(out_dir, path=None):
    """(results dict, sphere path or None, S1P path or None) of an antenna result of out_dir (path: which one;
    default the newest), or None."""
    js = [path] if path else antenna_files(out_dir)
    if not js:
        return None
    with open(js[-1]) as fh:
        res = json.load(fh)
    name = os.path.basename(js[-1])[:-len('_antenna.json')]
    solver = res.get('solver', 'openems')
    if solver != 'openems':                                         # <name>_<solver>_antenna.json, its own sphere
        name = name[:-len(f"_{solver}")] if name.endswith(f"_{solver}") else name
        sph = os.path.join(out_dir, res.get('sphere_file', ''))
    else:
        tag = res.get('port', 'P1').replace('+', 'p').replace('-', 'n')
        sph = os.path.join(out_dir, 'openems', f"exc_{tag}", 'nf2ff_sphere.h5')
    s1p = os.path.join(out_dir, f"{name}_{solver}.s1p")
    return res, (sph if os.path.isfile(sph) else None), (s1p if os.path.exists(s1p) else None)


def load_array(out_dir, res):
    """Each port's far field of an antenna result (mom25d's <name>_mom25d_array.npz: phased.load), or None."""
    from kicad2ems.api.frontend import phased
    f = os.path.join(out_dir, (res or {}).get('array_file') or '')
    return phased.load(f) if (res or {}).get('array_file') and os.path.isfile(f) else None


def load_sphere(path):
    """An antenna sphere: openEMS's NF2FF HDF5 file, or the .npz of mom25d's antenna mode (the same keys)."""
    if path.endswith('.npz'):
        with np.load(path) as z:
            return {k: np.asarray(z[k]) for k in z.files}
    return read_sphere(path)
