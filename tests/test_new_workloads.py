"""Tests for sat_batch, compression, regex and nqueens.

The WASM kernels are not run here. Small Python stand-ins play the worker, so
we can check split -> execute -> aggregate end to end with known answers.
"""
import base64
import json
import re
import zlib
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.jobs import JobSubmission
from app.services.loader import get_aggregator, get_splitter


def run_job(workload, config, worker):
    """Split a job, run each task with `worker`, and return the parsed result."""
    job = JobSubmission(workload=workload, config=config)
    job.job_id = uuid4()

    tasks = get_splitter(workload).split(job)
    aggregator = get_aggregator(workload, job.config)

    for task in tasks:
        result = worker(task.config.model_dump())
        result["_task_id"] = task.task_id
        result["_execution_time_ms"] = 1.5
        aggregator.add_result(result)

    assert aggregator.is_complete(len(tasks))
    return tasks, json.loads(aggregator.get_result())


# ---------------------------------------------------------------- job models


def test_each_workload_gets_its_own_config_class():
    job = JobSubmission(workload="nqueens", config={"n": 6, "split_depth": 1})
    assert type(job.config).__name__ == "NQueensConfig"

    job = JobSubmission(workload="regex", config={"patterns": ["a"], "texts": ["a"]})
    assert type(job.config).__name__ == "RegexConfig"


def test_wrong_config_for_workload_is_rejected():
    with pytest.raises(ValidationError):
        JobSubmission(workload="regex", config={"n": 8})


def test_config_needs_exactly_one_data_source():
    with pytest.raises(ValidationError):
        JobSubmission(workload="compression", config={})
    with pytest.raises(ValidationError):
        JobSubmission(
            workload="compression",
            config={"data_base64": "AAAA", "synthetic_size": 10},
        )
    with pytest.raises(ValidationError):
        JobSubmission(workload="sat_batch", config={})


def test_nqueens_split_depth_cannot_exceed_n():
    with pytest.raises(ValidationError):
        JobSubmission(workload="nqueens", config={"n": 4, "split_depth": 5})


# ------------------------------------------------------------------ n-queens


def count_queens(n, prefix):
    """Plain Python version of the Rust kernel."""
    def ok(cols, col):
        row = len(cols)
        return all(col != c and abs(col - c) != row - r for r, c in enumerate(cols))

    cols = []
    for c in prefix:
        if c >= n or not ok(cols, c):
            return {"solutions": 0, "nodes": 0}
        cols.append(c)

    nodes = 0

    def search(cols):
        nonlocal nodes
        if len(cols) == n:
            return 1
        total = 0
        for col in range(n):
            if ok(cols, col):
                nodes += 1
                total += search(cols + [col])
        return total

    return {"solutions": search(cols), "nodes": nodes}


@pytest.mark.parametrize("n,expected", [(4, 2), (6, 4), (8, 92)])
@pytest.mark.parametrize("depth", [0, 1, 2, 3])
def test_nqueens_total_does_not_depend_on_split_depth(n, expected, depth):
    _, result = run_job(
        "nqueens",
        {"n": n, "split_depth": depth},
        lambda cfg: count_queens(cfg["n"], cfg["prefix"]),
    )
    assert result["solutions"] == expected


def test_nqueens_depth_two_task_count_for_n8():
    tasks, _ = run_job(
        "nqueens",
        {"n": 8, "split_depth": 2},
        lambda cfg: count_queens(cfg["n"], cfg["prefix"]),
    )
    # 8 columns for row 0, then 6 or 5 safe columns for row 1.
    assert len(tasks) == 42
    assert all(len(t.config.prefix) == 2 for t in tasks)
    assert [t.task_id for t in tasks] == list(range(42))


def test_nqueens_ignores_duplicate_results():
    job = JobSubmission(workload="nqueens", config={"n": 4, "split_depth": 1})
    aggregator = get_aggregator("nqueens", job.config)
    aggregator.add_result({"_task_id": 0, "solutions": 1, "nodes": 5})
    aggregator.add_result({"_task_id": 0, "solutions": 1, "nodes": 5})
    assert json.loads(aggregator.get_result())["solutions"] == 1


# ------------------------------------------------------------------- sat_batch


def brute_force_sat(num_variables, clauses):
    for bits in range(1 << num_variables):
        value = lambda lit: bool(bits >> (abs(lit) - 1) & 1) == (lit > 0)
        if all(any(value(lit) for lit in clause) for clause in clauses):
            return True
    return False


def fake_sat_worker(cfg):
    sat = brute_force_sat(cfg["num_variables"], cfg["clauses"])
    return {"satisfiable": sat, "model": [1] if sat else None}


def test_sat_batch_sends_plain_sat_tasks():
    tasks, result = run_job(
        "sat_batch",
        {
            "instances": [
                {"num_variables": 2, "clauses": [[1, 2]]},
                {"num_variables": 1, "clauses": [[1], [-1]]},
            ]
        },
        fake_sat_worker,
    )
    assert all(t.workload == "sat" for t in tasks)
    assert all(t.config.fixed_assignments == [] for t in tasks)
    assert result["instances"] == 2
    assert result["satisfiable"] == 1
    assert result["unsatisfiable"] == 1
    assert [r["satisfiable"] for r in result["results"]] == [True, False]


def test_sat_batch_random_generator_is_repeatable():
    config = {"random_3sat": {"count": 5, "num_variables": 8, "num_clauses": 34, "seed": 7}}
    first, _ = run_job("sat_batch", config, fake_sat_worker)
    second, _ = run_job("sat_batch", config, fake_sat_worker)

    assert len(first) == 5
    assert [t.config.clauses for t in first] == [t.config.clauses for t in second]
    for task in first:
        assert len(task.config.clauses) == 34
        for clause in task.config.clauses:
            assert len({abs(lit) for lit in clause}) == 3  # 3 different variables


def test_sat_batch_rejects_bad_literal():
    with pytest.raises(ValidationError):
        JobSubmission(
            workload="sat_batch",
            config={"instances": [{"num_variables": 2, "clauses": [[3]]}]},
        )


# ----------------------------------------------------------------- compression


def fake_compression_worker(cfg):
    data = base64.b64decode(cfg["data_base64"])
    packed = zlib.compress(data, 1 if cfg["variant"] == "lz4" else 6)
    return {
        "variant": cfg["variant"],
        "chunk_id": cfg["chunk_id"],
        "original_size": len(data),
        "compressed_size": len(packed),
        "roundtrip_ok": zlib.decompress(packed) == data,
        "error": None,
    }


def test_compression_makes_one_task_per_chunk_and_variant():
    tasks, result = run_job(
        "compression",
        {
            "variants": ["lz4", "zstd-fastest"],
            "chunk_size": 1000,
            "synthetic_size": 4500,
        },
        fake_compression_worker,
    )
    assert len(tasks) == 5 * 2  # 5 chunks (last one is short) x 2 variants
    assert {t.config.variant for t in tasks} == {"lz4", "zstd-fastest"}
    for variant in ("lz4", "zstd-fastest"):
        assert result[variant]["chunks"] == 5
        assert result[variant]["original_bytes"] == 4500
        assert result[variant]["roundtrip_failures"] == 0
        assert result[variant]["ratio"] < 1  # test data is compressible


def test_compression_uses_given_data_and_keeps_bytes_exact():
    raw = bytes(range(256)) * 10
    tasks, result = run_job(
        "compression",
        {
            "variants": ["lz4"],
            "chunk_size": 1000,
            "data_base64": base64.b64encode(raw).decode(),
        },
        fake_compression_worker,
    )
    rebuilt = b"".join(base64.b64decode(t.config.data_base64) for t in tasks)
    assert rebuilt == raw
    assert result["lz4"]["original_bytes"] == len(raw)


def test_compression_reports_worker_errors_and_failures():
    job = JobSubmission(
        workload="compression", config={"synthetic_size": 10, "variants": ["lz4"]}
    )
    aggregator = get_aggregator("compression", job.config)
    aggregator.add_result(
        {"_task_id": 0, "variant": "lz4", "error": "boom"}
    )
    aggregator.add_result(
        {
            "_task_id": 1, "variant": "lz4", "original_size": 10,
            "compressed_size": 5, "roundtrip_ok": False, "error": None,
        }
    )
    report = json.loads(aggregator.get_result())["lz4"]
    assert report["errors"] == ["boom"]
    assert report["roundtrip_failures"] == 1


# ------------------------------------------------------------------------ regex


def fake_regex_worker(cfg):
    pattern = re.compile(cfg["pattern"])
    matched = total = 0
    for text in cfg["texts"]:
        count = len(pattern.findall(text)) if cfg["mode"] == "scan" else int(
            bool(pattern.search(text))
        )
        matched += count > 0
        total += count
    return {
        "pattern_id": cfg["pattern_id"],
        "batch_id": cfg["batch_id"],
        "texts_scanned": len(cfg["texts"]),
        "matched_texts": matched,
        "total_matches": total,
        "limit_hits": 0,
        "compile_error": None,
    }


def test_regex_makes_one_task_per_pattern_and_batch():
    tasks, result = run_job(
        "regex",
        {
            "patterns": [r"^\d+$", "a+"],
            "texts": ["123", "abc", "45", "aaa", "x"],
            "texts_per_task": 2,
            "mode": "match",
        },
        fake_regex_worker,
    )
    assert len(tasks) == 2 * 3  # 2 patterns x 3 batches (2 + 2 + 1 texts)
    digits, letters = result["patterns"]
    assert digits["pattern"] == r"^\d+$"
    assert digits["texts_scanned"] == 5
    assert digits["matched_texts"] == 2
    assert letters["matched_texts"] == 2  # "abc" and "aaa"


def test_regex_scan_mode_counts_all_matches():
    _, result = run_job(
        "regex",
        {"patterns": ["a"], "texts": ["aaa", "ab"], "mode": "scan"},
        fake_regex_worker,
    )
    assert result["patterns"][0]["total_matches"] == 4


def test_regex_synthetic_texts_vary_in_length_and_repeat():
    config = {
        "patterns": ["a"],
        "synthetic_texts": {"count": 50, "min_length": 5, "max_length": 40, "seed": 3},
        "texts_per_task": 10,
    }
    first, _ = run_job("regex", config, fake_regex_worker)
    second, _ = run_job("regex", config, fake_regex_worker)

    texts = [text for t in first for text in t.config.texts]
    assert len(texts) == 50
    assert all(5 <= len(text) <= 40 for text in texts)
    assert len({len(text) for text in texts}) > 5
    assert texts == [text for t in second for text in t.config.texts]


def test_regex_carries_compile_error_through():
    job = JobSubmission(
        workload="regex", config={"patterns": ["(bad"], "texts": ["x"]}
    )
    aggregator = get_aggregator("regex", job.config)
    aggregator.add_result(
        {
            "_task_id": 0, "pattern_id": 0, "batch_id": 0, "texts_scanned": 0,
            "matched_texts": 0, "total_matches": 0, "limit_hits": 0,
            "compile_error": "unclosed group",
        }
    )
    assert json.loads(aggregator.get_result())["patterns"][0]["compile_error"] == "unclosed group"


def test_compression_upload_endpoint_sends_exact_file_bytes():
    from fastapi.testclient import TestClient

    from app import jobs
    from app.main import app

    sent = []

    async def fake_send(worker, task, attempt=None):
        sent.append(task)

    from app.models.worker import WorkerStates

    class FakeWorker:
        uuid = "w1"
        state = WorkerStates.IDLE

    original = (jobs.send_task, jobs.workers.copy())
    jobs.send_task = fake_send
    jobs.workers["w1"] = FakeWorker()
    try:
        raw = bytes(range(256)) * 20  # 5120 bytes, not text
        client = TestClient(app)
        response = client.post(
            "/jobs/compression/upload",
            files={"file": ("sample.bin", raw)},
            data={"variants": "lz4", "chunk_size": "2000"},
        )
        assert response.status_code == 200
        assert response.json()["filename"] == "sample.bin"
        assert b"".join(base64.b64decode(t.config.data_base64) for t in sent) == raw
        assert len(sent) == 3

        bad = client.post(
            "/jobs/compression/upload",
            files={"file": ("empty.bin", b"")},
        )
        assert bad.status_code == 422
        bad = client.post(
            "/jobs/compression/upload",
            files={"file": ("x.bin", b"abc")},
            data={"variants": "gzip"},
        )
        assert bad.status_code == 422
    finally:
        jobs.send_task, workers = original
        jobs.workers.clear()
        jobs.workers.update(workers)
