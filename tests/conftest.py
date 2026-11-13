"""kicad2ems-gui's tests use kicad2ems's fixtures and example boards, and its stand-in solvers (the GUI's forms
are built from the solver registry: the same solvers on every machine), from a kicad2ems checkout: KICAD2EMS_SRC,
default ../kicad2ems next to this repository."""
import os, sys

K2E = os.environ.get('KICAD2EMS_SRC') or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'kicad2ems')
if not os.path.exists(os.path.join(K2E, 'tests', 'k2e_fixtures.py')):
    raise RuntimeError(f"no kicad2ems checkout at {K2E}: set KICAD2EMS_SRC")
sys.path.insert(0, os.path.join(K2E, 'tests'))
from k2e_fixtures import *                                          # noqa: E402,F401,F403
import standins                                                     # noqa: E402

standins.install()                                                  # before kicad2ems.config is imported

# the analyses: stand-ins too (fake_analyses.py), before kicad2ems_gui lists the registry's; pcbqs's own are run
# through the same window in test_real_analyses.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_analyses                                                # noqa: E402

fake_analyses.install()



# The interpreter's own exit is skipped once pytest has reported: PySide 6.12 crashed tearing down what the tests
# leave (every test passed, then exit 139 on Linux, 127 on Windows, two runs in three). Its QApplication's
# destruction walks every widget wrapper still alive (110k by the last test), and a pyqtgraph scene's items call
# their Python overrides (itemChange) from their C++ destructors after their wrappers are gone (gdb:
# QGraphicsScene::clear -> QGraphicsWidget::~QGraphicsWidget -> a null call). Deleting each test's windows after
# it hit the same in mid-run. pytest's exit status stands.
_status = [0]


def pytest_sessionfinish(session, exitstatus):
    _status[0] = int(exitstatus)


def pytest_unconfigure(config):
    if 'PySide6.QtWidgets' in sys.modules and not os.environ.get('K2E_GUI_TEST_TEARDOWN'):
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_status[0])
