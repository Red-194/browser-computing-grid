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
DETAIL_FIELDS = [
    "session", "workload", "scheduler", "stealing", "run", "job_id",
    "task_id", "worker_id", "estimated_cost", "execution_time_ms",
    "primary_rays", "total_rays", "sphere_tests", "shadow_rays",
    "reflection_rays", "light_samples", "actual_work_units",
]


def call(base, path, body=None, method=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        base + path, data=data, method=method or ("POST" if data else "GET"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def run_once(base, job_body, include_stats=False):
    start = time.time()
    job_id = call(base, "/jobs", job_body)["job"]["job_id"]
    print(f"  submitted job {job_id}", flush=True)
    status = "running"
    last_report = time.monotonic()
    while status == "running":
        job = call(base, f"/jobs/{job_id}")
        status = job["status"]
        if status != "running":
            break
        if time.monotonic() - last_report >= 5:
            progress = job.get("progress", {})
            print(
                f"    {progress.get('done', 0)}/{progress.get('total', '?')} tiles done; "
                f"{progress.get('failed', 0)} failed",
                flush=True,
            )
            last_report = time.monotonic()
        time.sleep(0.2)
    if status != "done":
        raise RuntimeError(f"job {job_id} ended with status {status}")
    seconds = time.time() - start
    tasks = call(base, f"/jobs/{job_id}/tasks")["tasks"]
    per_worker = collections.Counter((t["worker_id"] or "?")[:4] for t in tasks)
    stats = call(base, f"/jobs/{job_id}/stats") if include_stats else None
    return job_id, seconds, dict(per_worker), tasks, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job_file")
    parser.add_argument("--session", required=True, help="label for this batch, e.g. S4")
    parser.add_argument("--workload", required=True, help="label for the job, e.g. mandelbrot_whole_set_300k")
    parser.add_argument("--configs", nargs="+", default=["random", "fastest_first:on", "boinc:on"])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--interleave",
        action="store_true",
        help="alternate scheduler configs each run to reduce order and load drift",
    )
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument(
        "--details-csv",
        help="optional per-task metrics CSV (estimated cost, execution time, and workload counters)",
    )
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    job_body = json.loads(Path(args.job_file).read_text())
    path = Path(args.csv)
    details_path = Path(args.details_csv) if args.details_csv else None
    new_file = not path.exists()
    with path.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        if details_path:
            details_path.parent.mkdir(parents=True, exist_ok=True)
            details_handle = details_path.open("a", newline="")
        else:
            details_handle = None
        try:
            details_writer = csv.DictWriter(details_handle, fieldnames=DETAIL_FIELDS) if details_handle else None
            if details_writer and details_path.stat().st_size == 0:
                details_writer.writeheader()
            parsed_configs = [
                (config.partition(":")[0], config.partition(":")[2])
                for config in args.configs
            ]
            if args.interleave:
                schedule = [
                    (config, run)
                    for run in range(1, args.runs + 1)
                    for config in parsed_configs
                ]
            else:
                schedule = [
                    (config, run)
                    for config in parsed_configs
                    for run in range(1, args.runs + 1)
                ]
            active_config = None
            for (name, stealing), run in schedule:
                if (name, stealing) != active_config:
                    payload = {"name": name}
                    if stealing:
                        payload["stealing"] = stealing == "on"
                    reply = call(args.base, "/scheduler", payload, method="PUT")
                    active_config = (name, stealing)
                label = "on" if reply.get("stealing") else "off"
                if name in ("random", "round_robin"):
                    label = "n/a"
                job_id, seconds, per_worker, tasks, stats = run_once(
                    args.base, job_body, include_stats=bool(details_writer)
                )
                print(f"{name:14s} stealing={label:3s} run {run}: {seconds:6.1f} s  {per_worker}")
                writer.writerow(dict(
                    session=args.session, workload=args.workload, scheduler=name, stealing=label,
                    run=run, seconds=f"{seconds:.1f}", tasks_by_worker=str(per_worker), note=args.note,
                ))
                handle.flush()
                if details_writer:
                    worker_by_task = {task["task_id"]: task["worker_id"] for task in tasks}
                    for tile in stats.get("tiles", []):
                        work = tile.get("work_stats", {})
                        details_writer.writerow({
                            "session": args.session,
                            "workload": args.workload,
                            "scheduler": name,
                            "stealing": label,
                            "run": run,
                            "job_id": job_id,
                            "task_id": tile["task_id"],
                            "worker_id": worker_by_task.get(tile["task_id"]),
                            "estimated_cost": tile.get("estimated_cost"),
                            "execution_time_ms": tile.get("execution_time_ms"),
                            **{key: work.get(key) for key in DETAIL_FIELDS[9:] if key != "execution_time_ms"},
                        })
                    details_handle.flush()
        finally:
            if details_handle:
                details_handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
