"""
The study: one board, the questions asked of it, who answers each, and the runs that takes.

    TREE                        what the list shows: kicad2ems's study_tree (the questions by group, each with the
                                engines installed that answer it)
    ANALYSES                    the runs the window can make on a board, in the order it makes them: kicad2ems's
                                own ('rf': the solvers together), then each analysis plugin
    with_needs(keys)            keys and the analyses they start from, in that order
    dependents(key)             the analyses that start from key's results
    run_order(ticked, preview)  what a Run (a Preview) of those runs starts, in order
    StudyModel                  the study itself, with no window: what can be asked, what is, who answers each
                                question, the Fields ticks, what cannot run here and why, each run's state
    StudyTree                   the list in the Study dock (studytree.py: the model's view): a row per question,
                                with a tick (it is asked), who answers it (a menu: one engine, or several to
                                compare), a tick for its field dumps where an engine can write them, and its state

A question is something to find out (kicad2ems.study: the ports' S-parameters, a rail's drop, the temperature);
an engine is a solver or an analysis plugin that answers it. The three RF questions are answered by the solvers,
together, as kicad2ems's one run; every other engine is a run of its own, in the registry's order, which is
also a run's: Thermal, which takes its losses from the latest circuit run unless they are typed, runs after
Circuit. `needs` is how one analysis follows another (none does now).

Nothing in this module needs Qt (or a display): a program that drives a study without the window (kicad2ems-ipc,
a test) imports it alone.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Analysis:
    key: str
    title: str
    tool: str               # what runs it, as the list shows it
    page: str = ''          # its own page (a name of app.PANELS: the circuit's editor); '': Viewer, Run and Results
    needs: tuple = ()       # the analyses whose results it starts from
    preview: bool = False   # it has a preview (the model and meshes, no solve)
    planned: bool = False   # no tool for it yet: listed, greyed
    note: str = ''          # the list's tooltip


RF = 'rf'                       # kicad2ems's own run: not a plugin's


def installed():
    """S-parameters, then the analyses of kicad2ems's registry in its order (none: only S-parameters)."""
    out = [Analysis(RF, 'S-parameters', 'the solvers ticked', preview=True,
                    note="kicad2ems's run: the solvers chosen on the RF rows, their S-parameters, fields and antenna "
                         "results")]
    from kicad2ems.api.frontend import analyses
    for a in analyses().values():
        out.append(Analysis(a.name, a.label, a.tool, page=a.label if a.page else '', needs=tuple(a.needs),
                            preview=bool(a.previewed), note=a.about))
    return tuple(out)


def tree():
    """What the list shows: kicad2ems's study_tree, [dict(group, questions=[dict(question, engines, missing)])]."""
    from kicad2ems.api.frontend import study_tree
    return study_tree()


ANALYSES = installed()
BY_KEY = {a.key: a for a in ANALYSES}
TREE = tree()


def with_needs(keys):
    """keys and, for each, the analyses it starts from (and theirs), in ANALYSES' order."""
    want, todo = set(), list(keys)
    while todo:
        k = todo.pop()
        if k in BY_KEY and k not in want:
            want.add(k)
            todo += BY_KEY[k].needs
    return [a.key for a in ANALYSES if a.key in want]


def dependents(key):
    """The analyses that start from key's results (and from theirs), in ANALYSES' order."""
    out, grew = {key}, True
    while grew:
        grew = False
        for a in ANALYSES:
            if a.key not in out and out & set(a.needs):
                out.add(a.key)
                grew = True
    return [a.key for a in ANALYSES if a.key in out and a.key != key]


def run_order(ticked, preview=False, available=None):
    """What a Run of the ticked analyses starts, in order: each after what it starts from; planned ones and (with
    `available`, a set) those that cannot run here left out, with what follows them. preview: only the analyses
    that have one, each alone (a preview solves nothing, so nothing follows another)."""
    if preview:
        return [a.key for a in ANALYSES if a.key in ticked and a.preview and not a.planned
                and (available is None or a.key in available)]
    out = []
    for k in with_needs(ticked):
        a = BY_KEY[k]
        if a.planned or (available is not None and k not in available) or any(n not in out for n in a.needs):
            continue
        out.append(k)
    return out


SOLVER_QUESTIONS = ('sparams', 'antenna', 'lines')      # what the solvers answer: together, kicad2ems's one run
AUTO = 'auto'                                           # the solvers' tick box of that name
short = lambda label: label.split(' (')[0]          # 'mom25d (MoM)' -> 'mom25d'


class StudyModel:
    """The study with no window: the questions by group with the engines installed that answer each (TREE as it
    is when this is made), and what the user has made of them:

        on          the questions ticked
        choice      {question: [engine names]}: who answers ([]: its default, the first that can run here)
        fields      {question: its Fields tick}
        solvers     {name: ticked} of the solvers and 'auto', as the RF settings have them; None: not known
        why         {run: why it cannot be made here}
        states      {run: (text, tone)}

    A run is an engine's, so availability, state and the queue go by run ('rf', or an analysis's name), and a
    question shows those of its engines. Every change calls each of `listeners` with what changed ('ticks',
    'engines', 'fields', 'available', 'state', 'study') and the question or run it was (None: several)."""

    def __init__(self, tree=None):
        self.groups, self.labels, self.about, self.engines, self.missing = [], {}, {}, {}, {}
        for g in (TREE if tree is None else tree):
            self.groups.append((g['group'], [row['question'].name for row in g['questions']]))
            for row in g['questions']:
                q = row['question']
                self.labels[q.name], self.about[q.name] = q.label, q.about
                self.engines[q.name] = [e for e in row['engines'] if q.name in SOLVER_QUESTIONS or e.name in BY_KEY]
                self.missing[q.name] = row['missing'] or 'no engine for it is installed'
        self.questions = list(self.labels)
        self.on = set()
        self.choice, self.fields = {q: [] for q in self.questions}, {q: False for q in self.questions}
        self.why, self.states, self.solvers = {}, {}, None
        self.listeners = []

    def changed(self, what, key=None):
        for f in list(self.listeners):
            f(what, key)

    # ---- the questions and their engines ----
    def is_solver(self, q):
        return q in SOLVER_QUESTIONS

    def usable(self, q):
        """The engines of a question that can run here, in their order."""
        return [e.name for e in self.engines.get(q, []) if e.name not in self.why]

    def can_ask(self, q):
        return bool(self.engines.get(q)) if self.is_solver(q) else bool(self.usable(q))

    def engines_for(self, q):
        """The analyses that answer a question as it stands: those chosen that can run here, else its first that
        can. A solver question: none (the solvers ticked answer it, in kicad2ems's own run)."""
        if self.is_solver(q):
            return []
        ok = self.usable(q)
        chosen = [n for n in self.choice.get(q, []) if n in ok]
        return chosen or ok[:1]

    def run_of(self, q):
        """The run a question's settings and page belong to: 'rf', or its first engine."""
        if self.is_solver(q) or not self.engines.get(q):
            return RF
        return (self.engines_for(q) or [self.engines[q][0].name])[0]

    def panels_of(self, q):
        """The runs whose settings a question shows: 'rf' for the solvers', else its engines' (those chosen, or
        its default; all of them where none can run, so that their settings can still be read)."""
        if self.is_solver(q):
            return [RF]
        return self.engines_for(q) or [e.name for e in self.engines.get(q, [])]

    def solver_names(self, q):
        """The solvers ticked that answer a solver question, and whether auto is."""
        ticked = self.solvers or {}
        return [e.name for e in self.engines.get(q, []) if ticked.get(e.name)], bool(ticked.get(AUTO))

    def set_solvers(self, ticked):
        """The solvers' ticks ({name: bool}, 'auto' among them), as the RF settings have them."""
        if self.solvers != dict(ticked):
            self.solvers = dict(ticked)
            self.changed('engines')

    def can_dump(self, q):
        """Whether a question's engines, as chosen, can write field dumps."""
        es = {e.name: e for e in self.engines.get(q, [])}
        if q == 'lines':
            return False
        if self.is_solver(q):
            on, auto = self.solver_names(q)
            return any(es[n].fields for n in on) or (auto or self.solvers is None) and any(e.fields for e in es.values())
        return any(es[n].fields for n in self.engines_for(q))

    def by(self, q):
        """A question's 'Answered by' as a list shows it: (text, tooltip, whether there is a choice to make)."""
        es = self.engines[q]
        by = {e.name: e for e in es}
        if not es:
            return '', self.missing[q], False
        if self.is_solver(q):
            on, auto = self.solver_names(q)
            if q == 'lines':
                text = ' + '.join(short(by[n].label) for n in on) or ('auto' if auto or self.solvers is None else 'line model')
            else:
                text = ' + '.join((['auto'] if auto else []) + [short(by[n].label) for n in on]) or \
                       ('auto' if self.solvers is None else 'no solver')
            return text, 'the solvers that answer it, in one run with the other RF questions: click to choose', True
        names = self.engines_for(q)
        text = ' + '.join(by[n].label for n in names) or ' / '.join(e.label for e in es)
        tip = ('click to choose: ' + ', '.join(e.label for e in es)) if len(es) > 1 else by[es[0].name].plugin.tool
        return text, tip, len(es) > 1

    # ---- what is asked ----
    def tick(self, q, on=True):
        """Ask a question, or not (one that cannot be asked here stays unasked)."""
        on = bool(on) and self.can_ask(q)
        if (q in self.on) != on:
            (self.on.add if on else self.on.discard)(q)
            self.changed('ticks', q)

    def asked(self):
        """{question: [engine names]} of the questions ticked, in the list's order: the engines chosen, [] for its
        default (a solver question: the solvers ticked, which the settings hold)."""
        return {q: ([] if self.is_solver(q) else list(self.choice[q])) for q in self.questions
                if q in self.on and self.can_ask(q)}

    def asked_fields(self):
        """{question: its Fields tick} of the questions asked that have one."""
        return {q: bool(self.fields.get(q)) for q in self.asked() if self.can_dump(q)}

    def study(self):
        """The study as kicad2ems holds one (a config's [study] tables)."""
        from kicad2ems.api.frontend import Study
        return Study(self.asked(), self.asked_fields(), 'study')

    def set_study(self, study):
        """The ticks, the engines and the Fields ticks of a Study (a config's): a question it does not ask
        unticked. An engine not installed here is left out; a solver question's solvers are the settings'."""
        self.on = {q for q in self.questions if q in study.asked and self.can_ask(q)}
        for q in self.questions:
            names = {e.name for e in self.engines[q]}
            self.choice[q] = [] if self.is_solver(q) else [n for n in study.asked.get(q, []) if n in names]
            self.fields[q] = bool(study.fields.get(q, False))
        self.changed('study')

    def jobs(self, preview=False, only=None):
        """The runs the questions asked take, in order: 'rf' when a solver question is asked, then the analyses
        of the others in the registry's order (run_order). preview: those that have one. only: a question (or a
        run) alone, ticked or not."""
        if only is not None:
            qs = [only] if only in self.labels else [q for q in self.questions if only == self.run_of(q)
                                                     or (only == RF and self.is_solver(q))][:1]
            qs = [q for q in qs if self.can_ask(q)]
        else:
            qs = list(self.asked())
        keys = set()
        for q in qs:
            keys |= {RF} if self.is_solver(q) else set(self.engines_for(q))
        return run_order(keys, preview, self.available())

    def asked_of(self, key, only=None):
        """The questions asked of a run ('rf' or an analysis), in the list's order."""
        qs = [only] if only in self.labels else list(self.asked())
        return tuple(q for q in qs if (self.is_solver(q) if key == RF else key in self.engines_for(q)))

    def set_fields(self, q, on):
        """A question's Fields tick, as its settings say (no default filled in: they hold what is asked). True:
        it changed."""
        if q in self.labels and bool(self.fields.get(q)) != bool(on):
            self.fields[q] = bool(on)
            self.changed('fields', q)
            return True
        return False

    def fields_on(self, key):
        """Whether a run's field dumps are asked for: a Fields tick on one of its questions."""
        return any(self.fields.get(q) and self.can_dump(q) for q in self.asked_of(key))

    def choose(self, q, name, on):
        """Tick or untick an engine of a question that analyses answer ('auto': its default alone)."""
        names = [e.name for e in self.engines[q]]
        if name == AUTO:
            self.choice[q] = []
        elif name in names:
            cur = set(self.choice[q] or self.engines_for(q)) if on else set(self.choice[q])
            cur = (cur | {name}) if on else (cur - {name})
            self.choice[q] = [n for n in names if n in cur]
        self.changed('engines', q)

    # ---- as the runs see it ----
    def available(self):
        return {a.key for a in ANALYSES if a.key not in self.why}

    def ticked(self):
        """The runs of the questions asked, in order."""
        return self.jobs()

    def study_of_runs(self, keys):
        """The Study in which the questions these runs answer are asked, each by that engine: 'rf' is
        S-parameters."""
        asked = {}
        for k in keys:
            for q in self.questions:
                if (k == RF and q == 'sparams') or (k != RF and any(e.name == k for e in self.engines[q])):
                    first = (self.usable(q) or [None])[0]
                    asked.setdefault(q, [])
                    if k != RF and k != first and k not in asked[q]:
                        asked[q].append(k)
        from kicad2ems.api.frontend import Study
        return Study(asked, {q: self.fields.get(q, False) for q in asked})

    def set_ticked(self, keys):
        self.set_study(self.study_of_runs(keys))

    def ask(self, key):
        """The questions a run answers asked too (those that can be, by that run where it is one of several
        engines: the others stay as they are): what a result proposed for it is to be run."""
        for q in self.questions:
            if key != RF and key in self.engines_for(q):
                self.tick(q, True)

    def set_available(self, key, ok, why=''):
        """A run that cannot be made here: its engine is not offered, and a question nobody else answers cannot be
        asked (it is unticked), its state saying why."""
        if ok:
            self.why.pop(key, None)
        else:
            self.why[key] = why or 'not installed'
            self.states.pop(key, None)
        self.on = {q for q in self.on if self.can_ask(q)}
        self.changed('available', key)

    def set_state(self, key, text, tone=''):
        """A run's state ('running', 'done 21:42', 'failed (exit 2)', 'not started: no rail'); tone: '', 'gray'
        or 'bad'."""
        if key in self.why:
            return
        self.states[key] = (text, tone)
        self.changed('state', key)

    def state(self, key):
        """A run's state as it was set."""
        return self.states.get(key, ('', ''))[0]

    def clear_states(self):
        """Another board: the last one's runs say nothing of it."""
        self.states.clear()
        self.changed('state')

    def state_of(self, q):
        """A question's state as a list shows it, from its engines' runs: (text, tooltip, tone)."""
        if not self.engines[q]:
            return 'not installed', self.missing[q], 'gray'
        if not self.can_ask(q):
            why = '; '.join(f"{e.label}: {self.why[e.name]}" for e in self.engines[q] if e.name in self.why)
            return 'not available', why, 'gray'
        keys = [RF] if self.is_solver(q) else self.engines_for(q)
        by = {e.name: e.label for e in self.engines[q]}
        got = [(k, *self.states[k]) for k in keys if self.states.get(k, ('', ''))[0]]
        cut = lambda t: t.split(' (')[0].split(': ')[0]
        if len(keys) > 1:
            same = len(got) == len(keys) and len({cut(t) for _, t, _ in got}) == 1
            text = cut(got[0][1]) if same else ' · '.join(f"{by.get(k, k)} {cut(t)}" for k, t, _ in got)
            tip = '\n'.join(f"{by.get(k, k)}: {t}" for k, t, _ in got)
        else:
            text, tip = (cut(got[0][1]), got[0][1]) if got else ('', '')
        tone = 'bad' if any(tn == 'bad' for _, _, tn in got) else 'gray' if got and all(tn == 'gray' for _, _, tn in got) else ''
        return text, tip, tone


def __getattr__(name):                                  # the list itself is the window's (studytree.py: Qt)
    if name in ('StudyTree', 'StudyList'):
        from . import studytree
        return getattr(studytree, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
