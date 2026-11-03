"""The solvers' meshes of a results folder (kicad2ems's meshes.find) as the viewers offer them: one entry a solver
in the Mesh selector (the preview's mesh, or the run's where there is no preview), and the mesh a run solved on,
<solver>-run (mom25d's with its quad cells), drawn over it in pink with the "solved" tick box."""
RUN = '-run'
SOLVED_COLOUR = '#e0479e'                                   # pink: the mesh a run solved on
SOLVED_RGBA = (0.88, 0.28, 0.62, 0.9)


def base(solver):
    """The solver a mesh file belongs to: 'mom25d' of 'mom25d-run'."""
    return solver[:-len(RUN)] if solver.endswith(RUN) else solver


def solvers(found):
    """The solvers of find()'s {solver: path}, each once, in its order (the newest first)."""
    return list(dict.fromkeys(base(s) for s in found))


def shown(found, solver):
    """The mesh drawn for `solver`: the preview's, else the run's (a folder with no preview)."""
    return found.get(solver) or found.get(solver + RUN) if solver else None


def solved(found, solver):
    """The mesh a run of `solver` solved on, or None: drawn over shown()'s with the tick box."""
    return found.get(solver + RUN) if solver else None


def tip(found, solver, counts):
    """The "solved" tick box's tooltip for `solver` (counts: meshes.counts)."""
    p = solved(found, solver)
    if p is None:
        return "the mesh a run solved on, in pink over the preview's (mom25d: its quad cells, without their " \
               "diagonals): a run of this solver writes it"
    return f"the mesh the run solved on, in pink over the preview's: {counts(p)}"
