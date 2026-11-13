"""The study with no window (study.StudyModel): what is asked and by whom, the runs that takes, what cannot run
here, each run's state, and what a list shows of all that. No Qt is imported: a program that drives a study
without the window uses the same object the Study dock draws."""
import subprocess
import sys

from kicad2ems_gui import study
from kicad2ems_gui.study import StudyModel, RF, AUTO


def test_the_module_needs_no_qt():
    code = ("import sys; import kicad2ems_gui.study as s; m = s.StudyModel(); m.tick('sparams'); "
            "assert m.jobs() == ['rf'] and not any(n.startswith('PySide6') for n in sys.modules), "
            "[n for n in sys.modules if n.startswith('PySide6')]")
    p = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_what_is_asked_and_the_runs_it_takes():
    m = StudyModel()
    seen = []
    m.listeners.append(lambda what, key: seen.append((what, key)))
    assert [g for g, _ in m.groups][:2] == ['RF', 'Signal integrity'] and m.questions[0] == 'sparams'
    assert m.asked() == {} and m.jobs() == [] and m.study().asked == {}
    for q in ('thermal', 'sparams', 'dc', 'pdn'):
        m.tick(q)
    assert seen == [('ticks', q) for q in ('thermal', 'sparams', 'dc', 'pdn')]
    assert list(m.asked()) == ['sparams', 'dc', 'pdn', 'thermal']       # the list's order, not the order ticked
    assert m.jobs() == ['rf', 'pdn', 'thermal']                         # one run of pdn answers two questions
    assert m.jobs(preview=True) == ['rf'] and m.jobs(only='thermal') == ['thermal'] and m.jobs(only='pdn') == ['pdn']
    assert m.asked_of('pdn') == ('dc', 'pdn') and m.asked_of(RF) == ('sparams',)
    m.tick('crosstalk')                                                 # nobody installed answers it: not asked
    assert 'crosstalk' not in m.on and not m.can_ask('crosstalk') and m.state_of('crosstalk')[0] == 'not installed'
    m.tick('dc', False)
    assert m.jobs() == ['rf', 'pdn', 'thermal'] and m.asked_of('pdn') == ('pdn',)
    # as kicad2ems holds a study, and back
    other = StudyModel()
    other.set_study(m.study())
    assert other.asked() == m.asked() and other.jobs() == m.jobs()
    other.set_ticked(['circuit'])
    assert list(other.asked()) == ['circuit'] and other.jobs() == ['circuit']


def test_who_answers_and_what_cannot_run_here():
    m = StudyModel()
    m.tick('thermal')
    assert m.engines_for('thermal') == ['thermal'] and m.run_of('thermal') == 'thermal'
    assert m.by('thermal') == (m.engines['thermal'][0].label, 'click to choose: '
                               + ', '.join(e.label for e in m.engines['thermal']), True)
    m.choose('thermal', 'elmer_thermal', True)                          # a second engine: both run, compared
    assert m.engines_for('thermal') == ['thermal', 'elmer_thermal'] and m.jobs() == ['thermal', 'elmer_thermal']
    assert m.asked() == {'thermal': ['thermal', 'elmer_thermal']} and m.panels_of('thermal') == ['thermal', 'elmer_thermal']
    m.choose('thermal', 'thermal', False)
    assert m.engines_for('thermal') == ['elmer_thermal'] and m.run_of('thermal') == 'elmer_thermal'
    m.choose('thermal', AUTO, True)
    assert m.choice['thermal'] == [] and m.engines_for('thermal') == ['thermal']
    # the first engine cannot run here: the other answers; neither: the question cannot be asked, and says why
    m.set_available('thermal', False, 'no ngspice')
    assert m.engines_for('thermal') == ['elmer_thermal'] and 'thermal' in m.on and m.available() >= {'elmer_thermal'}
    m.set_available('elmer_thermal', False, 'no Elmer')
    assert not m.can_ask('thermal') and 'thermal' not in m.on and m.jobs() == []
    text, tip, tone = m.state_of('thermal')
    assert (text, tone) == ('not available', 'gray') and 'no ngspice' in tip and 'no Elmer' in tip
    m.set_available('thermal', True)
    assert m.can_ask('thermal') and m.state_of('thermal')[0] == ''


def test_the_solvers_ticks_and_the_fields():
    m = StudyModel()
    assert m.by('sparams')[0] == 'auto' and m.by('lines')[0] == 'auto' and m.can_dump('sparams')    # (ticks not known)
    m.set_solvers({AUTO: False, 'openems': True, 'mom25d': True, 'qucs': True})
    label = {e.name: study.short(e.label) for e in m.engines['sparams']}    # ('openEMS', 'mom25d', 'line model')
    assert m.by('sparams')[0] == ' + '.join(label[n] for n in ('openems', 'mom25d', 'qucs'))
    assert m.by('lines')[0] == label['qucs'] and m.is_solver('lines')
    assert m.can_dump('sparams') and not m.can_dump('lines') and m.engines_for('sparams') == [] and m.run_of('antenna') == RF
    m.set_solvers({AUTO: False, 'qucs': True})
    assert not m.can_dump('sparams') and m.by('sparams')[0] == label['qucs']    # a line model writes no fields
    m.set_solvers({AUTO: False})
    assert m.by('sparams')[0] == 'no solver' and m.by('lines')[0] == 'line model'
    m.set_solvers({AUTO: True, 'mom25d': True})
    m.tick('sparams')
    m.tick('circuit')
    assert m.set_fields('sparams', True) and not m.set_fields('sparams', True) and m.fields_on(RF)
    assert m.asked_fields() == {'sparams': True, 'circuit': False} and not m.fields_on('circuit')
    assert m.study().fields == {'sparams': True, 'circuit': False}
    assert not m.can_dump('dc') and 'dc' not in m.asked_fields()


def test_a_run_s_state_on_its_questions():
    m = StudyModel()
    seen = []
    m.listeners.append(lambda what, key: seen.append((what, key)))
    m.set_state('pdn', 'running: 3 of 7', '')
    assert m.state('pdn') == 'running: 3 of 7' and m.state_of('dc') == ('running', 'running: 3 of 7', '')
    assert m.state_of('pdn')[0] == 'running' and m.state_of('thermal')[0] == '' and seen == [('state', 'pdn')]
    m.choose('thermal', 'elmer_thermal', True)
    m.set_state('thermal', 'done 21:42')
    m.set_state('elmer_thermal', 'failed (exit 2)', 'bad')
    text, tip, tone = m.state_of('thermal')
    assert tone == 'bad' and 'done' in text and 'failed' in text and tip.count('\n') == 1
    m.set_available('mqs', False, 'not here')
    m.set_state('mqs', 'done')                                          # a run that cannot be made has no state
    assert m.state('mqs') == '' and m.state_of('nearfield')[0] == 'not available'
    m.clear_states()
    assert m.state('pdn') == '' and m.state_of('dc')[0] == ''


def test_the_list_is_the_model_s_view():
    """The Study dock's list draws a model, its own or one it is given: a tick made on the model shows on the row,
    and one made on the row is the model's."""
    import os
    import pytest
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import Qt
    from kicad2ems_gui import application
    from kicad2ems_gui.studytree import StudyTree
    application()
    m = StudyModel()
    tree = StudyTree(m)
    assert tree.m is m and study.StudyTree is StudyTree and study.StudyList is StudyTree
    m.tick('dc')
    assert tree.rows['dc'].checkState(0) == Qt.Checked and tree.asked() == {'dc': []}
    tree.rows['thermal'].setCheckState(0, Qt.Checked)
    assert 'thermal' in m.on and m.jobs() == ['pdn', 'thermal'] == tree.jobs()
    m.set_state('pdn', 'done 10:00')
    assert tree.rows['dc'].text(3) == 'done 10:00' and tree.state('pdn') == 'done 10:00'
    m.set_available('pdn', False, 'not installed')
    assert tree.rows['dc'].checkState(0) == Qt.Unchecked and tree.rows['dc'].text(3) == 'not available'
