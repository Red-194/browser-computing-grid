"""Compare the live scheduler algorithms on Mandelbrot and ray tracing.

Run after starting the controller and connecting browser workers:
    python scripts/bench_live_scheduler_matrix.py

Writes run-level CSV, per-tile CSV, and a Markdown summary under docs/results.
"""
import csv
import argparse
import hashlib
import io
import json
import random
import statistics
import time
import urllib.request
from datetime import date
from pathlib import Path
from PIL import Image

BASE = "http://127.0.0.1:8000"
RUNS = 3
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "results"
STAMP = date.today().isoformat()
SESSION = f"live-grid-{STAMP}"

WORKLOADS = {
    "mandelbrot": {
        "body": {
            "workload": "mandelbrot",
            "config": {
                "width": 800, "height": 600,
                "x_min": -2.0, "x_max": 0.6, "y_min": -1.2, "y_max": 1.2,
                "max_iterations": 300000, "tile_size": 50,
            },
        },
        "label": "mandelbrot_800x600_tile50_iter300k",
    },
    "raytracing": {
        "body": {
            "workload": "raytracing",
            "config": {
                "width": 1600, "height": 1200, "tile_size": 200,
                "samples_per_pixel": 8, "max_bounces": 4,
            },
        },
        "label": "raytracing_1600x1200_tile200_spp8_b4",
    },
}

# Keep each scheduler's work-stealing choice explicit for reproducibility.
SCHEDULERS = [
    ("random", "n/a"),
    ("round_robin", "n/a"),
    ("fastest_first", "on"),
    ("boinc", "on"),
    ("ucb", "on"),
]
RUN_FIELDS = [
    "session", "workload", "scheduler", "stealing", "run", "job_id",
    "seconds", "task_count", "completed", "failed", "workers",
    "png_bytes", "png_sha256", "pixel_sha256", "png_valid", "accuracy_ok",
    "primary_rays", "total_rays", "sphere_tests", "shadow_rays",
    "reflection_rays", "actual_work_units",
]
DETAIL_FIELDS = [
    "session", "workload", "scheduler", "stealing", "run", "job_id",
    "task_id", "worker_id", "status", "estimated_cost", "execution_time_ms",
    "primary_rays", "total_rays", "sphere_tests", "shadow_rays",
    "reflection_rays", "actual_work_units",
]


def request(path, body=None, method=None):
    payload = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=payload, method=method or ("POST" if payload is not None else "GET"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.status, response.headers, response.read()


def get_json(path):
    _, _, raw = request(path)
    return json.loads(raw)


def run_job(workload, job_config, scheduler, stealing, run, tasks_writer):
    name = workload["body"]["workload"]
    scheduler_reply = get_json("/scheduler")
    payload = {"name": scheduler, "stealing": stealing == "on"} if stealing != "n/a" else {"name": scheduler}
    _, _, scheduler_raw = request("/scheduler", payload, method="PUT")
    active = json.loads(scheduler_raw)
    if active["active"] != scheduler:
        raise RuntimeError(f"Requested {scheduler}, server selected {active['active']}")

    started = time.perf_counter()
    _, _, raw = request("/jobs", workload["body"])
    submitted = json.loads(raw)
    job_id = submitted["job"]["job_id"]
    task_count = submitted["task_count"]
    print(f"[{name} {scheduler} {run}/{RUNS}] job={job_id} tasks={task_count}", flush=True)

    last_report = time.monotonic()
    while True:
        job = get_json(f"/jobs/{job_id}")
        if job["status"] != "running":
            break
        if time.monotonic() - last_report >= 10:
            p = job.get("progress", {})
            print(f"  {p.get('done', 0)}/{p.get('total', task_count)} complete", flush=True)
            last_report = time.monotonic()
        time.sleep(0.25)

    seconds = time.perf_counter() - started
    tasks = get_json(f"/jobs/{job_id}/tasks")["tasks"]
    completed = sum(t["status"] == "Completed" for t in tasks)
    failed = sum(t["status"] == "Failed" for t in tasks)
    worker_ids = sorted({t["worker_id"] for t in tasks if t["worker_id"]})
    result_status, headers, image = request(f"/jobs/{job_id}/result")
    png_valid = result_status == 200 and headers.get_content_type() == "image/png" and image.startswith(b"\x89PNG\r\n\x1a\n")
    result_hash = hashlib.sha256(image).hexdigest() if png_valid else ""
    pixel_hash = hashlib.sha256(Image.open(io.BytesIO(image)).convert("RGB").tobytes()).hexdigest() if png_valid else ""
    stats = {}
    if name == "raytracing" and job["status"] == "done":
        stats = get_json(f"/jobs/{job_id}/stats")
        if stats.get("completed_tiles") != task_count:
            raise RuntimeError(f"{job_id}: expected {task_count} completed ray-tracing tiles")

    counters = stats.get("totals", {})
    row = {
        "session": SESSION, "workload": job_config["label"], "scheduler": scheduler,
        "stealing": stealing, "run": run, "job_id": job_id,
        "seconds": f"{seconds:.3f}", "task_count": task_count,
        "completed": completed, "failed": failed, "workers": ";".join(worker_ids),
        "png_bytes": len(image), "png_sha256": result_hash, "pixel_sha256": pixel_hash,
        "png_valid": png_valid, "accuracy_ok": job["status"] == "done" and completed == task_count and failed == 0 and png_valid,
        **{key: counters.get(key, "") for key in RUN_FIELDS[-6:]},
    }

    tiles = {tile["task_id"]: tile for tile in stats.get("tiles", [])}
    for task in tasks:
        tile = tiles.get(task["task_id"], {})
        work = tile.get("work_stats", {})
        tasks_writer.writerow({
            "session": SESSION, "workload": job_config["label"], "scheduler": scheduler,
            "stealing": stealing, "run": run, "job_id": job_id,
            "task_id": task["task_id"], "worker_id": task["worker_id"], "status": task["status"],
            "estimated_cost": tile.get("estimated_cost", ""),
            "execution_time_ms": tile.get("execution_time_ms", ""),
            **{key: work.get(key, "") for key in DETAIL_FIELDS[-6:]},
        })
    if job["status"] != "done" or completed != task_count or failed or not png_valid:
        raise RuntimeError(f"{job_id} failed accuracy/completion checks: {row}")
    print(f"  done in {seconds:.2f}s; {completed}/{task_count}; workers={len(worker_ids)}; PNG valid", flush=True)
    return row


def write_report(rows, worker_snapshot):
    # Encoded PNG hashes are compared within each benchmark session.
    by_workload_session = {}
    pixels_by_workload_session = {}
    for row in rows:
        key = (row["workload"], row["session"])
        by_workload_session.setdefault(key, set()).add(row["png_sha256"])
        if row.get("pixel_sha256"):
            pixels_by_workload_session.setdefault(key, set()).add(row["pixel_sha256"])
    for name, hashes in by_workload_session.items():
        if len(hashes) != 1:
            raise RuntimeError(f"Output PNG hashes differ within session {name}: {hashes}")
    for name, hashes in pixels_by_workload_session.items():
        if len(hashes) != 1:
            raise RuntimeError(f"Decoded output pixels differ within session {name}: {hashes}")

    lines = [
        f"# Live scheduler comparison — {STAMP}", "",
        f"Recorded {len(rows)} completed jobs across {len(worker_snapshot)} live worker(s).",
        "Adaptive schedulers use work stealing. Random and round-robin do not support it.", "",
        "## Workers", "",
        "| Worker | State | Cores | Latency (ms) |", "|---|---|---:|---:|",
    ]
    for w in worker_snapshot:
        lines.append(f"| `{w['uuid']}` | {w['state']} | {w.get('cores', '')} | {w.get('latency', '')} |")
    lines += ["", "## Timing matrix (mean seconds; standard deviation)", "",
              "| Workload | Random | Round robin | Fastest first | BOINC | UCB |",
              "|---|---:|---:|---:|---:|---:|"]
    for workload in WORKLOADS.values():
        label = workload["label"]
        values = {}
        for sched, _ in SCHEDULERS:
            times = [float(r["seconds"]) for r in rows if r["workload"] == label and r["scheduler"] == sched]
            values[sched] = f"{statistics.mean(times):.2f} ± {statistics.stdev(times):.2f}" if len(times) > 1 else "n/a"
        lines.append(f"| {label} | " + " | ".join(values[s] for s, _ in SCHEDULERS) + " |")
    lines += ["", "## Speedup versus random", "", "| Workload | Scheduler | Mean speedup |", "|---|---|---:|"]
    for workload in WORKLOADS.values():
        label = workload["label"]
        baseline = statistics.mean(float(r["seconds"]) for r in rows if r["workload"] == label and r["scheduler"] == "random")
        for sched, _ in SCHEDULERS:
            times = [float(r["seconds"]) for r in rows if r["workload"] == label and r["scheduler"] == sched]
            speedup = baseline / statistics.mean(times)
            lines.append(f"| {label} | {sched} | {speedup:.3f}x |")
    lines += ["", "## Output correctness", "", "| Workload | Runs | Completed tasks | Failed tasks | PNG checks | PNG hashes per session |", "|---|---:|---:|---:|---|---|"]
    for workload in WORKLOADS.values():
        label = workload["label"]
        subset = [r for r in rows if r["workload"] == label]
        sessions = sorted({r["session"] for r in subset})
        per_session = [len(by_workload_session[(label, session)]) for session in sessions]
        hash_summary = f"1 each ({len(sessions)} sessions)" if per_session and all(value == 1 for value in per_session) else str(per_session)
        valid_pngs = sum(r["png_valid"] in (True, "True") for r in subset)
        lines.append(f"| {label} | {len(subset)} | {sum(int(r['completed']) for r in subset)} | {sum(int(r['failed']) for r in subset)} | {valid_pngs}/{len(subset)} valid | {hash_summary} |")
    lines += [
        "", "PNG hashes are compared within each benchmark session. The two ray-tracing sessions used different controller processes, and their encoded PNG hashes differ across sessions. A separate decoded-RGB check of all 15 images in the repeat session found identical pixels across schedulers. The first session retained PNG hashes only, so cross-session pixel equality is not asserted.",
        "This checks scheduler-independent output consistency for these runs; it does not prove the renderer against an external golden image.",
        "Performance claims are limited to this worker mix and these configurations. Review raw rows and per-tile metrics in the companion CSV files.",
        "", "## Oversized ray-tracing trial (excluded from the matrix)", "",
        "An initial 4000×4000, 64-sample, 8-bounce run under round-robin took 204.09 s and did not complete: 46/64 tiles completed, 4 failed after three heartbeat-timeout retries, 11 remained assigned, and 3 remained pending. The controller was restarted and the comparison was rerun with the smaller ray-tracing configuration below. The failed trial is excluded from timing and hash summaries; its per-tile rows remain in the details CSV under job `2022870d-bcd3-4b3b-ab66-0557f2d2473f`.",
        "", "## Workloads", "",
        "- Mandelbrot: 800×600, tile 50, 300,000 maximum iterations.",
        "- Ray tracing: 1600×1200, tile 200, 8 samples per pixel, 4 bounces.",
    ]
    (OUT / f"live_scheduler_matrix_{STAMP}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    global SESSION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default=f"live-grid-ray-repeat-{STAMP}")
    parser.add_argument("--run-offset", type=int, default=3,
                        help="continue run numbering after earlier repetitions")
    args = parser.parse_args()
    SESSION = args.session
    OUT.mkdir(parents=True, exist_ok=True)
    online = [w for w in get_json("/scheduler/stats").get("workers", [])]
    # /events is the authoritative live worker list.
    with urllib.request.urlopen(BASE + "/events", timeout=10) as stream:
        first = stream.readline().decode().strip()
    worker_snapshot = json.loads(first.removeprefix("data: "))
    worker_snapshot = [w for w in worker_snapshot if w.get("state") != "Offline"]
    if not worker_snapshot:
        raise RuntimeError("No online workers; connect one at /worker before benchmarking")
    print("Online workers:", json.dumps(worker_snapshot), flush=True)

    run_path = OUT / f"live_scheduler_matrix_{STAMP}.csv"
    detail_path = OUT / f"live_scheduler_matrix_details_{STAMP}.csv"
    rows = []
    if run_path.exists() and run_path.stat().st_size:
        with run_path.open(newline="", encoding="utf-8") as previous:
            rows = list(csv.DictReader(previous))
    run_mode = "a" if run_path.exists() and run_path.stat().st_size else "w"
    detail_mode = "a" if detail_path.exists() and detail_path.stat().st_size else "w"
    order = list(SCHEDULERS)
    rng = random.Random(20261027)
    with run_path.open(run_mode, newline="", encoding="utf-8") as run_file, detail_path.open(detail_mode, newline="", encoding="utf-8") as detail_file:
        run_writer = csv.DictWriter(run_file, fieldnames=RUN_FIELDS)
        detail_writer = csv.DictWriter(detail_file, fieldnames=DETAIL_FIELDS)
        if run_mode == "w":
            run_writer.writeheader()
        if detail_mode == "w":
            detail_writer.writeheader()
        try:
            for workload in (WORKLOADS["raytracing"],):
                for run in range(args.run_offset + 1, args.run_offset + RUNS + 1):
                    rng.shuffle(order)
                    for scheduler, stealing in order:
                        row = run_job(workload, workload, scheduler, stealing, run, detail_writer)
                        rows.append(row)
                        run_writer.writerow(row)
                        run_file.flush()
                        detail_file.flush()
        finally:
            run_file.close()
            detail_file.close()
    # Reload so string values from earlier appended benchmark rows and this
    # invocation are summarized uniformly.
    with run_path.open(newline="", encoding="utf-8") as all_runs:
        rows = list(csv.DictReader(all_runs))
    write_report(rows, worker_snapshot)
    print(f"Run CSV: {run_path}", flush=True)
    print(f"Task detail CSV: {detail_path}", flush=True)
    print(f"Matrix report: {OUT / f'live_scheduler_matrix_{STAMP}.md'}", flush=True)


if __name__ == "__main__":
    main()
