"""Compare the scheduling algorithms on a simulated grid (no server, no devices).

    python scripts/simulate_schedulers.py
    python scripts/simulate_schedulers.py --scenario known_uneven_sizes --seeds 10
    python scripts/simulate_schedulers.py --scenario worker_hangs --no-timeouts

Each row is one algorithm, averaged over several random seeds (the seed changes
task-time noise and the random scheduler's choices). "done" is how many of the
runs finished the job. The worker speeds are assumptions (see
app/services/scheduler/simulator.py), so this shows how the algorithms behave,
not how fast the real grid is.
"""
import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `app` can be imported from scripts/

from app.services import scheduler  # noqa: E402
from app.services.scheduler.simulator import SCENARIOS, run_scenario  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--scenario", choices=sorted(SCENARIOS), help="only this scenario")
parser.add_argument("--seeds", type=int, default=5, help="runs per algorithm (default 5)")
parser.add_argument(
    "--no-timeouts", action="store_true", help="switch the timeout monitor off"
)
args = parser.parse_args()

names = scheduler.available()
for scenario in [args.scenario] if args.scenario else SCENARIOS:
    doc = (SCENARIOS[scenario].__doc__ or "").strip().splitlines()[0]
    print(f"\n{scenario}: {doc}")
    print(f"  {'algorithm':14}{'done':>6}{'makespan s':>12}{'  range':>18}{'effic.':>8}{'retries':>9}{'wasted s':>10}")
    for name in names:
        runs = [
            run_scenario(scenario, name, seed=seed, use_timeouts=not args.no_timeouts)
            for seed in range(args.seeds)
        ]
        finished = [r for r in runs if r.completed]
        if finished:
            times = [r.makespan for r in finished]
            makespan = f"{statistics.mean(times):12.2f}"
            spread = f"{min(times):9.2f}-{max(times):.2f}".rjust(18)
            efficiency = f"{statistics.mean(r.efficiency for r in finished):8.2f}"
        else:
            makespan, spread, efficiency = f"{'-':>12}", f"{'-':>18}", f"{'-':>8}"
        print(
            f"  {name:14}{len(finished):>3}/{len(runs):<2}{makespan}{spread}{efficiency}"
            f"{sum(r.retries for r in runs):>9}{sum(r.wasted_seconds for r in runs):>10.1f}"
        )
