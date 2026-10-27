"""Stress live browser workers with repeated Mandelbrot and ray-tracing jobs.

Run with the controller and browser workers already online:
    python scripts/bench_live_mandelbrot_raytracing.py
"""
import json
import statistics
import time
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = "http://127.0.0.1:8000"
ROUNDS = 3
OUT = Path(__file__).resolve().parents[1] / "docs" / "results" / "live_mandelbrot_raytracing_stealing_2026-10-27.md"

JOBS = {
    "mandelbrot": {
        "workload": "mandelbrot",
        "config": {
            "width": 1024, "height": 768,
            "x_min": -2.0, "x_max": 0.6, "y_min": -1.2, "y_max": 1.2,
            "max_iterations": 300000, "tile_size": 64,
        },
    },
    "raytracing": {
        "workload": "raytracing",
        "config": {
            "width": 2000, "height": 2000, "tile_size": 250,
            "samples_per_pixel": 32, "max_bounces": 6,
        },
    },
}


def request(path, body=None, method=None):
    payload = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=payload,
        headers={"Content-Type": "application/json"},
        method=method or ("POST" if payload is not None else "GET"),
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.status, response.headers, response.read()


def get_json(path):
    _, _, body = request(path)
    return json.loads(body)


def run_job(label, sequence):
    body = JOBS[label]
    started = time.perf_counter()
    _, _, raw = request("/jobs", body)
    submitted = json.loads(raw)
    job_id = submitted["job"]["job_id"]
    task_count = submitted["task_count"]
    print(f"[{sequence}] {label}: job {job_id}, {task_count} tasks", flush=True)

    last_report = time.monotonic()
    while True:
        job = get_json(f"/jobs/{job_id}")
        status = job["status"]
        progress = job.get("progress", {})
        if status != "running":
            break
        if time.monotonic() - last_report >= 10:
            print(
                f"    {progress.get('done', 0)}/{progress.get('total', task_count)} done, "
                f"{progress.get('failed', 0)} failed", flush=True,
            )
            last_report = time.monotonic()
        time.sleep(0.5)

    seconds = time.perf_counter() - started
    tasks = get_json(f"/jobs/{job_id}/tasks")["tasks"]
    done = sum(t["status"] == "Completed" for t in tasks)
    failed = sum(t["status"] == "Failed" for t in tasks)
    worker_ids = sorted({t["worker_id"] for t in tasks if t["worker_id"]})
    result_status, headers, png = request(f"/jobs/{job_id}/result")
    png_ok = result_status == 200 and headers.get_content_type() == "image/png" and png.startswith(b"\x89PNG\r\n\x1a\n")
    counters = {}
    if label == "raytracing":
        stats = get_json(f"/jobs/{job_id}/stats")
        counters = stats.get("totals", {})
        if stats.get("completed_tiles") != task_count:
            raise RuntimeError(f"{job_id}: raytracing completed tile count mismatch")

    row = {
        "sequence": sequence, "workload": label, "job_id": job_id,
        "seconds": round(seconds, 2), "tasks": task_count, "completed": done,
        "failed": failed, "status": status, "workers": worker_ids,
        "png_bytes": len(png), "png_valid": png_ok, "counters": counters,
    }
    print(
        f"    {status}: {done}/{task_count} complete, {failed} failed, "
        f"{seconds:.2f}s, PNG={'ok' if png_ok else 'INVALID'}, "
        f"workers={','.join(worker_ids) or 'none'}", flush=True,
    )
    if status != "done" or done != task_count or failed or not png_ok:
        raise RuntimeError(f"job {job_id} failed validation: {row}")
    if len(worker_ids) != 1:
        print(f"    NOTE: expected the connected worker; observed {len(worker_ids)} owners", flush=True)
    return row


def main():
    with urllib.request.urlopen(BASE + "/events", timeout=10) as stream:
        first_event = stream.readline().decode(errors="replace").strip()
    workers = json.loads(first_event.removeprefix("data: "))
    online = [worker for worker in workers if worker.get("state") != "Offline"]
    if not online:
        raise RuntimeError("No online browser workers are connected")

    _, _, raw = request("/scheduler", {"name": "boinc", "stealing": True}, method="PUT")
    scheduler = json.loads(raw)
    print(f"Scheduler: {scheduler['active']}; work stealing: {scheduler['stealing']}", flush=True)
    print("Online workers:", json.dumps(online), flush=True)

    rows = []
    sequence = 0
    for _ in range(ROUNDS):
        for label in ("mandelbrot", "raytracing"):
            sequence += 1
            rows.append(run_job(label, sequence))

    for label in JOBS:
        times = [r["seconds"] for r in rows if r["workload"] == label]
        print(f"{label}: mean={statistics.mean(times):.2f}s median={statistics.median(times):.2f}s runs={times}", flush=True)

    lines = [
        "# Live Mandelbrot and ray-tracing stress test — 2026-10-27", "",
        f"Ran {ROUNDS} jobs per workload through the live browser controller with "
        f"**{scheduler['active']}** scheduling and work stealing **{str(scheduler['stealing']).lower()}**.", "",
        "## Configuration", "",
        "- Mandelbrot: 1024×768, 64-pixel tiles (192 tasks), 300,000 maximum iterations.",
        "- Ray tracing: 2000×2000, 250-pixel tiles (64 tasks), 32 samples per pixel, 6 bounces.",
        f"- Online worker snapshot: `{json.dumps(online, separators=(',', ':'))}`", "",
        "## Results", "",
        "| # | Workload | Job ID | Wall time | Tasks complete | Failed | PNG | Worker IDs |", "|---:|---|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['sequence']} | {row['workload']} | `{row['job_id']}` | {row['seconds']:.2f}s "
            f"| {row['completed']}/{row['tasks']} | {row['failed']} | {len_ok(row['png_valid'])}, {row['png_bytes']:,} bytes "
            f"| {', '.join(row['workers'])} |"
        )
    lines += ["", "## Timing summary", ""]
    for label in JOBS:
        times = [r["seconds"] for r in rows if r["workload"] == label]
        lines.append(f"- {label}: mean {statistics.mean(times):.2f}s, median {statistics.median(times):.2f}s, runs {', '.join(f'{v:.2f}' for v in times)}s.")
    lines += ["", "## Ray-tracing work counters", "", "| # | Primary rays | Total rays | Sphere tests | Shadow rays | Reflection rays |", "|---:|---:|---:|---:|---:|---:|"]
    for row in (r for r in rows if r["workload"] == "raytracing"):
        c = row["counters"]
        lines.append(f"| {row['sequence']} | {c.get('primary_rays', 0):,} | {c.get('total_rays', 0):,} | {c.get('sphere_tests', 0):,} | {c.get('shadow_rays', 0):,} | {c.get('reflection_rays', 0):,} |")
    lines += [
        "", "## Work-stealing coverage", "",
        f"The controller reported work stealing `{str(scheduler['stealing']).lower()}` for scheduler `{scheduler['active']}` during these runs.",
        f"The live worker snapshot contained {len(online)} online worker(s). Work stealing requires an idle worker to duplicate a task held by another worker; with fewer than two online workers, the cross-worker stealing path cannot activate. These runs validate the workloads and scheduler configuration, not the multi-worker steal path.",
        "", "All six jobs reported done, all tiles completed without failures, and each returned a PNG with a valid signature.", "",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {OUT}", flush=True)


def len_ok(ok):
    return "valid" if ok else "INVALID"


if __name__ == "__main__":
    main()
