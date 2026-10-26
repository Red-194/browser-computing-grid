"""Time one job file under several schedulers and append the results to a CSV.

    python scripts/bench_scheduler.py job.json --session S4 --workload mandelbrot_whole_set_300k \\
        --configs random round_robin fastest_first:off fastest_first:on boinc:on ucb:on --runs 3

A config is `name` or `name:on` / `name:off` (work stealing). Start the server and
connect the workers first. Rows go to docs/results/scheduler_comparison.csv by
default, in the same columns as the existing data.
"""
import argparse
import collections
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_CSV = Path(__file__).resolve().parents[1] / "docs" / "results" / "scheduler_comparison.csv"
FIELDS = ["session", "workload", "scheduler", "stealing", "run", "seconds", "tasks_by_worker", "note"]


def call(base, path, body=None, method=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        base + path, data=data, method=method or ("POST" if data else "GET"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def run_once(base, job_body):
    start = time.time()
    job_id = call(base, "/jobs", job_body)["job"]["job_id"]
    while call(base, f"/jobs/{job_id}")["status"] == "running":
        time.sleep(0.2)
    seconds = time.time() - start
    tasks = call(base, f"/jobs/{job_id}/tasks")["tasks"]
    per_worker = collections.Counter((t["worker_id"] or "?")[:4] for t in tasks)
    return seconds, dict(per_worker)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job_file")
    parser.add_argument("--session", required=True, help="label for this batch, e.g. S4")
    parser.add_argument("--workload", required=True, help="label for the job, e.g. mandelbrot_whole_set_300k")
    parser.add_argument("--configs", nargs="+", default=["random", "fastest_first:on", "boinc:on"])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    job_body = json.loads(Path(args.job_file).read_text())
    path = Path(args.csv)
    new_file = not path.exists()
    with path.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        for config in args.configs:
            name, _, stealing = config.partition(":")
            payload = {"name": name}
            if stealing:
                payload["stealing"] = stealing == "on"
            reply = call(args.base, "/scheduler", payload, method="PUT")
            label = "on" if reply.get("stealing") else "off"
            if name in ("random", "round_robin"):
                label = "n/a"
            for run in range(1, args.runs + 1):
                seconds, per_worker = run_once(args.base, job_body)
                print(f"{name:14s} stealing={label:3s} run {run}: {seconds:6.1f} s  {per_worker}")
                writer.writerow(dict(
                    session=args.session, workload=args.workload, scheduler=name, stealing=label,
                    run=run, seconds=f"{seconds:.1f}", tasks_by_worker=str(per_worker), note=args.note,
                ))
                handle.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
