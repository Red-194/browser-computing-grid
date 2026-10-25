"""Submit one job for each workload and check the answer.

Start the server and open at least one /worker tab first, then run:

    python scripts/test_all_workloads.py
    python scripts/test_all_workloads.py http://192.168.1.23:8000
"""
import json
import logging
import sys
import time
import urllib.request

from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger("grid.cli.test_all_workloads")

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 120


def post_job(workload, config):
    body = json.dumps({"workload": workload, "config": config}).encode()
    request = urllib.request.Request(
        BASE + "/jobs", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def wait_for_result(job_id):
    """Ask for the result until the job is done."""
    deadline = time.time() + TIMEOUT_SECONDS
    while time.time() < deadline:
        with urllib.request.urlopen(f"{BASE}/jobs/{job_id}/result") as response:
            data = json.load(response)
        if "message" not in data:  # "still processing" replies have a message
            return data
        time.sleep(1)
    return None


# ---- one check per workload: each returns a list of problems (empty = pass)


def check_nqueens(result):
    problems = []
    if result["solutions"] != 724:
        problems.append(f"expected 724 solutions, got {result['solutions']}")
    return problems


def check_sat_batch(result):
    problems = []
    if result["instances"] != 3:
        problems.append(f"expected 3 instances, got {result['instances']}")
    if result["satisfiable"] != 2 or result["unsatisfiable"] != 1:
        problems.append(
            f"expected 2 satisfiable and 1 not, got "
            f"{result['satisfiable']} and {result['unsatisfiable']}"
        )
    return problems


def check_sat_random(result):
    if result["instances"] != 20:
        return [f"expected 20 instances, got {result['instances']}"]
    return []


def check_compression(result):
    problems = []
    for variant in ("lz4", "zstd-fastest"):
        stats = result.get(variant)
        if stats is None:
            problems.append(f"{variant}: missing from result")
            continue
        if stats["errors"]:
            problems.append(f"{variant}: worker errors {stats['errors'][:2]}")
        if stats["chunks"] != 4:
            problems.append(f"{variant}: expected 4 chunks, got {stats['chunks']}")
        if stats["original_bytes"] != 1_000_000:
            problems.append(f"{variant}: original_bytes is {stats['original_bytes']}")
        if stats["roundtrip_failures"] != 0:
            problems.append(f"{variant}: {stats['roundtrip_failures']} round-trip failures")
        if not stats["ratio"] or stats["ratio"] >= 1:
            problems.append(f"{variant}: data did not shrink (ratio {stats['ratio']})")
    return problems


def check_regex(result):
    problems = []
    letters, digits, broken, backref = result["patterns"]
    if letters["matched_texts"] != 5:  # aaa, abc, aab, ab, aaaab
        problems.append(f"a+: expected 5 matching texts, got {letters['matched_texts']}")
    if digits["matched_texts"] != 2:
        problems.append(f"digits: expected 2 matching texts, got {digits['matched_texts']}")
    if not broken["compile_error"]:
        problems.append("bad pattern should report a compile_error")
    if backref["matched_texts"] != 2:
        problems.append(f"backreference: expected 2 matching texts, got {backref['matched_texts']}")
    return problems


TESTS = [
    ("nqueens", "nqueens (10 queens = 724)",
     {"n": 10, "split_depth": 2}, check_nqueens),
    ("sat_batch", "sat_batch (your own formulas)",
     {"instances": [
         {"num_variables": 2, "clauses": [[1, 2]]},
         {"num_variables": 1, "clauses": [[1], [-1]]},
         {"num_variables": 3, "clauses": [[1, 2], [-1, 3], [-2, -3]]},
     ]}, check_sat_batch),
    ("sat_batch", "sat_batch (random 3-SAT)",
     {"random_3sat": {"count": 20, "num_variables": 20, "num_clauses": 80, "seed": 1}},
     check_sat_random),
    ("compression", "compression (lz4 + zstd-fastest)",
     {"synthetic_size": 1_000_000, "chunk_size": 262144,
      "variants": ["lz4", "zstd-fastest"]}, check_compression),
    ("regex", "regex (match, bad pattern, backreference)",
     {"patterns": ["a+", "^[0-9]+$", "(bad", "(a+)\\1b"],
      "texts": ["aaa", "123", "abc", "45", "aab", "ab", "aaaab"],
      "mode": "match"}, check_regex),
]


def main():
    failures = 0

    for workload, name, config, check in TESTS:
        logger.info("%s", name)
        try:
            job = post_job(workload, config)
        except Exception as error:
            logger.error("FAIL could not submit the job: %s", error)
            failures += 1
            continue

        assigned = len(job["assignments"])
        logger.info("%d tasks, %d sent to workers", job["task_count"], assigned)
        if assigned == 0:
            logger.error("FAIL no worker is connected. Open /worker in a browser tab first.")
            failures += 1
            continue

        result = wait_for_result(job["job"]["job_id"])
        if result is None:
            logger.error(
                "FAIL no result after %ss. Check the worker tab console (F12).",
                TIMEOUT_SECONDS,
            )
            failures += 1
            continue

        problems = check(result)
        if problems:
            failures += 1
            for problem in problems:
                logger.error("FAIL %s", problem)
        else:
            logger.info("PASS")

    logger.info("%d of %d passed", len(TESTS) - failures, len(TESTS))
    sys.exit(1 if failures else 0)


main()
