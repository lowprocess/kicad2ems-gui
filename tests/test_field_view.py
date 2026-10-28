"""The field view tab on a run folder: a time-domain plane dump (VTR frames) and a frequency-domain one (HDF5),
frames, components, live following and the phase of a frequency-domain dump (from kicad2ems's field tests)."""
import base64, os, zlib
import numpy as np
import pytest
from kicad2ems.fields.dumps import write_info, write_norm, parse_dump


def _b64_block(raw, compress):
    if not compress:
        return base64.b64encode(np.uint32(len(raw)).tobytes() + raw).decode()
    c = zlib.compress(raw)
    head = np.array([1, 32768, len(raw), len(c)], '<u4').tobytes()
    return base64.b64encode(head).decode() + base64.b64encode(c).decode()   # encoded separately, as VTK does


def write_vtr(path, x, y, z, field, compress=True):
    """A VTK rectilinear grid like openEMS's dumps: coordinates in m, point data x fastest."""
    hdr = ' compressor="vtkZLibDataCompressor"' if compress else ''
    data = np.transpose(field.astype('<f4'), (2, 1, 0, 3)).tobytes()
    coords = ''.join(f'<DataArray type="Float64" format="binary">{_b64_block((np.asarray(c, "<f8") * 1e-3).tobytes(), compress)}</DataArray>'
                     for c in (x, y, z))
    ext = f"0 {len(x) - 1} 0 {len(y) - 1} 0 {len(z) - 1}"
    with open(path, 'w') as fh:
        fh.write(f'<?xml version="1.0"?><VTKFile type="RectilinearGrid" version="0.1" byte_order="LittleEndian" '
                 f'header_type="UInt32"{hdr}><RectilinearGrid WholeExtent="{ext}"><Piece Extent="{ext}"><PointData>'
                 f'<DataArray type="Float32" Name="E-Field" NumberOfComponents="3" format="binary">'
                 f'{_b64_block(data, compress)}</DataArray></PointData><CellData></CellData><Coordinates>{coords}'
                 f'</Coordinates></Piece></RectilinearGrid></VTKFile>')


@pytest.fixture(scope='module')
def run_folder(demo_files, tmp_path_factory):
    """A run folder with a time-domain plane dump (VTR frames), a frequency-domain one (HDF5) and their info."""
    h5py = pytest.importorskip('h5py')
    from kicad2ems.importers.kicad import KiCadBoard
    from kicad2ems.board import Board
    base, _ = demo_files
    m = Board(KiCadBoard(base + '.kicad_pcb'), nets=['RF', 'GND'], pos_file=base + '-top.pos', ground='B.Cu')
    out = tmp_path_factory.mktemp('out')
    run = out / 'openems' / 'exc_P1'
    td, fd = parse_dump('E@F.Cu-0.1', m), parse_dump('J@F.Cu@3', m)
    write_info(str(run), [td, fd], m, dt_ps=0.5)
    ob = m.outline.bounds
    x, y = np.linspace(ob[0], ob[2], 30), np.linspace(ob[1], ob[3], 12)
    for k in range(5):
        f = np.zeros((30, 12, 1, 3), np.float32)
        f[:, :, 0, 2] = (k + 1) * np.sin(x / 3)[:, None]
        write_vtr(run / f"{td.name}_{k * 60:010d}.vtr", x, y, [td.start[2]], f)
    with h5py.File(run / f"{fd.name}.h5", 'w') as h:
        for ax, v in zip('xyz', (x, y, [fd.start[2]])):
            h[f'Mesh/{ax}'] = np.asarray(v) * 1e-3
        g = h.create_group('FieldData/FD')
        ds = g.create_dataset('f0', data=np.ones((3, 30, 12, 1)) * (1 + 1j))
        ds.attrs['d_order'], ds.attrs['frequency'] = 'NXYZ', 3e9
    write_norm(str(run), {3e9: 0.5j})
    return str(out), m


def test_field_view_tab(run_folder, tmp_path):
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from kicad2ems_gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    out, _ = run_folder
    w = MainWindow()
    f = w.fields
    f.load(out)
    assert len(f.srcs) == 2 and f.src.domain == 'TD' and f.frame.maximum() == 4 and f.axis.currentText() == 'z'
    f.frame.setValue(3)
    assert '4/5' in f.frame_lab.text() and f.pl.img.shape == (30, 12)
    f.comp.setCurrentIndex(3)                                       # Ez: signed, symmetric range
    assert f.pl.signed and f.lim[0] == -f.lim[1]
    f.follow(out)                                                   # live: jumps to the newest frame
    assert f.frame.value() == 4
    f.dump.setCurrentIndex(1)
    f.phase_on.setChecked(True)
    f.phase.setValue(90)
    assert 'phase 90°' in f.frame_lab.text()
    w.close()
