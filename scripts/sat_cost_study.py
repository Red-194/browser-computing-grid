"""Measure how much work the SAT kernel does, and check the cost model against it.

Python port of runtime/src/kernels/sat.rs (same branching order) that counts
clause visits, which is what the kernel's time follows. Prints how well
`app/services/scheduler/cost.py` ranks random 3-SAT instances by that count.

    python scripts/sat_cost_study.py [--seeds N]
"""
import argparse
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.setrecursionlimit(10000)

from app.models.tasks import SATTaskConfig  # noqa: E402
from app.services.scheduler.cost import task_cost  # noqa: E402
from app.services.splitters.sat_batch import make_random_3sat  # noqa: E402


def visits(num_variables, clauses, fixed=()):
    """Clause visits the kernel makes on this formula (a step of its propagate loop)."""
    value = [0] * (num_variables + 1)
    count = 0

    def lit(literal):
        v = value[abs(literal)]
        return v if literal > 0 else -v

    def propagate():
        nonlocal count
        while True:
            changed = False
            for clause in clauses:
                count += 1
                unassigned, unit, satisfied = 0, 0, False
                for literal in clause:
                    v = lit(literal)
                    if v == 1:
                        satisfied = True
                        break
                    if v == 0:
                        unassigned, unit = unassigned + 1, literal
                if satisfied:
                    continue
                if unassigned == 0:
                    return False
                if unassigned == 1:
                    changed |= value[abs(unit)] == 0
                    value[abs(unit)] = 1 if unit > 0 else -1
            if not changed:
                return True

    def dpll():
        if not propagate():
            return False
        free = next((i for i in range(1, num_variables + 1) if value[i] == 0), None)
        if free is None:
            return True
        snapshot = value[:]
        value[free] = 1
        if dpll():
            return True
        value[:] = snapshot
        value[free] = -1
        if dpll():
            return True
        value[:] = snapshot
        return False

    for literal in fixed:
        sign = 1 if literal > 0 else -1
        if value[abs(literal)] not in (0, sign):
            return count
        value[abs(literal)] = sign
    dpll()
    return count


def spearman(xs, ys):
    def ranks(values):
        order = sorted(range(len(values)), key=values.__getitem__)
        out = [0] * len(values)
        for rank, index in enumerate(order):
            out[index] = rank
        return out

    return statistics.correlation(ranks(xs), ranks(ys))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=15, help="instances per setting")
    args = parser.parse_args()

    actual, estimated = [], []
    seed = 5000
    for n in (20, 30, 40):
        for ratio in (3.0, 4.0, 4.26, 4.6, 5.5):
            for instance in make_random_3sat(args.seeds, n, round(n * ratio), seed):
                seed += 1
                actual.append(visits(n, instance.clauses))
                estimated.append(task_cost("sat", SATTaskConfig(
                    num_variables=n, clauses=instance.clauses, fixed_assignments=[])))

    errors = [math.log(e / a) for e, a in zip(estimated, actual)]
    print(f"{len(actual)} instances; Spearman {spearman(estimated, actual):.2f}; "
          f"typical error x{math.exp(statistics.pstdev(errors)):.2f}; "
          f"bias x{math.exp(statistics.mean(errors)):.2f}")


if __name__ == "__main__":
    main()
