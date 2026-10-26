"""The endpoints the jobs page polls: per-task status, and result status codes."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import jobs
from app.main import app
from app.models.pcb import JobPCB


class FakeAggregator:
    result_type = "application/json"

    def get_result(self):
        return b'{"ok": true}'


@pytest.fixture
def client():
    for registry in (jobs.job_pcbs, jobs.aggregators, jobs.job_tasks):
        registry.clear()
    yield TestClient(app)
    for registry in (jobs.job_pcbs, jobs.aggregators, jobs.job_tasks):
        registry.clear()


def add_job(task_ids=(0, 1, 2, 3)):
    job_id = uuid4()
    job_pcb = JobPCB.create(job_id, "test", list(task_ids))
    jobs.job_pcbs[str(job_id)] = job_pcb
    jobs.aggregators[str(job_id)] = FakeAggregator()
    return job_id, job_pcb


def test_tasks_endpoint_labels_each_task_state(client):
    job_id, job_pcb = add_job()
    job_pcb.task(0).complete(job_pcb.task(0).assign("w1"), worker_uuid="w1")  # done
    job_pcb.task(1).assign("w2")  # running
    job_pcb.task(3).assign("w1")  # then failed for good
    job_pcb.task(3).fail("bad config")

    reply = client.get(f"/jobs/{job_id}/tasks")

    assert reply.status_code == 200
    assert reply.json()["tasks"] == [
        {"task_id": 0, "worker_id": "w1", "status": "Completed"},
        {"task_id": 1, "worker_id": "w2", "status": "Assigned"},
        {"task_id": 2, "worker_id": None, "status": "Pending"},
        {"task_id": 3, "worker_id": None, "status": "Failed"},
    ]


def test_tasks_endpoint_for_an_unknown_job_is_404(client):
    assert client.get(f"/jobs/{uuid4()}/tasks").status_code == 404


def test_result_is_202_while_the_job_is_running(client):
    job_id, _ = add_job()

    reply = client.get(f"/jobs/{job_id}/result")

    assert reply.status_code == 202
    assert reply.json()["message"] == "Job is still processing."


def test_result_is_200_when_done(client):
    job_id, job_pcb = add_job(task_ids=(0,))
    task = job_pcb.task(0)
    task.complete(task.assign("w1"), worker_uuid="w1")

    reply = client.get(f"/jobs/{job_id}/result")

    assert reply.status_code == 200
    assert reply.json() == {"ok": True}


def test_result_for_a_failed_job_still_says_so(client):
    job_id, job_pcb = add_job(task_ids=(0,))
    job_pcb.task(0).assign("w1")
    job_pcb.task(0).fail("bad config")

    reply = client.get(f"/jobs/{job_id}/result")

    assert reply.json()["message"] == "Job failed."
    assert reply.json()["status"] == "failed"


def test_result_for_an_unknown_job_is_404(client):
    assert client.get(f"/jobs/{uuid4()}/result").status_code == 404
