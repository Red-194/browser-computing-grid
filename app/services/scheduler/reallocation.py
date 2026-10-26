"""Taking work back from a worker that has been silent about it too long.

Heartbeats catch a worker that disappears. They do not catch one that stays
connected but never answers (a stuck tab, a throttled background tab, a task
that is far bigger than the average). For that every running task gets a
deadline, worked out from how long this worker normally takes. When it passes,
the task goes back to WAITING (an older attempt's late answer is then ignored),
the worker is marked as having timed out, and the task is handed out again,
preferably to someone else.

BOINC does the same with job deadlines ("delay bounds"): an instance that
misses its deadline is marked timed out and a new instance is created.

The functions here take their registries and clock as arguments, so the
simulator can run the exact same logic with a virtual clock.
"""
import asyncio
import logging
import time

from ...models.pcb import JobStatus, TaskState
from . import stats
from .cost import cost_of

logger = logging.getLogger("grid.reallocation")

# Used when the worker has not been measured: deliberately generous.
DEFAULT_TIMEOUT = 60.0
# Never time out sooner than this, however fast the worker usually is.
MIN_TIMEOUT = 10.0
# Deadline = (mean + K * std) * SAFETY of the expected compute time.
STD_MULTIPLIER = 3.0
SAFETY_FACTOR = 2.0
# How often the background monitor looks.
CHECK_INTERVAL = 1.0


def deadline_seconds(task_pcb, worker_pcb, cost, tracker) -> float:
    """How long this running task may take before it is taken back.

    A task queued behind others on the same worker also waits for them, so the
    allowance grows with the number of tasks the worker holds.
    """
    estimate = tracker.estimate(task_pcb.worker_uuid, task_pcb.workload, cost)
    if estimate is None:
        per_task = DEFAULT_TIMEOUT
    else:
        per_task = max(MIN_TIMEOUT, (estimate.mean + STD_MULTIPLIER * estimate.std) * SAFETY_FACTOR)
    queued = max(1, len(worker_pcb.running)) if worker_pcb is not None else 1
    return per_task * queued


def find_timed_out(job_pcbs, worker_pcbs, costs_of, tracker, now=None):
    """Running tasks past their deadline, as a list of TaskPCBs.

    costs_of(task_pcb) -> cost of that task (the caller knows how to look it up).
    """
    late = []
    for job_pcb in job_pcbs:
        if job_pcb.status != JobStatus.RUNNING:
            continue
        for task_pcb in job_pcb.tasks.values():
            if task_pcb.state != TaskState.RUNNING or task_pcb.worker_uuid is None:
                continue
            worker_pcb = worker_pcbs.get(task_pcb.worker_uuid)
            limit = deadline_seconds(task_pcb, worker_pcb, costs_of(task_pcb), tracker)
            if task_pcb.is_timed_out(limit, now):
                late.append(task_pcb)
    return late


def take_back(task_pcb, worker_pcbs, tracker, now=None, cost=1.0) -> bool:
    """Requeue one timed-out task and free the worker's slot for it.

    The slot is freed at once (the worker may still answer; that answer will be
    ignored as stale). The worker is marked as having timed out, and after a few
    in a row it is left out of scheduling for a while. Returns True if the task
    was requeued (another event may have handled it first).
    """
    worker_uuid = task_pcb.worker_uuid
    attempt = task_pcb.attempt
    waited = None if task_pcb.assigned_at is None else (
        (time.monotonic() if now is None else now) - task_pcb.assigned_at
    )
    state = task_pcb.requeue(
        f"timed out on worker {worker_uuid}", now=now, attempt=attempt
    )
    if state is None:
        return False

    worker_pcb = worker_pcbs.get(worker_uuid)
    if worker_pcb is not None:
        worker_pcb.release(task_pcb.key, completed=False)
    tracker.record_timeout(worker_uuid, now)
    tracker.record_lower_bound(worker_uuid, task_pcb.workload, cost, waited)
    return True


class TimeoutMonitor:
    """Background loop that applies the deadlines to the live registries."""

    def __init__(self, interval: float = CHECK_INTERVAL):
        self.interval = interval

    async def check_once(self, now=None) -> int:
        # Imported here: app.jobs imports this package.
        from ... import jobs
        from ...registry import job_pcbs, job_tasks, worker_pcbs

        def cost_of_task(task_pcb):
            task = job_tasks.get(str(task_pcb.job_id), {}).get(task_pcb.task_id)
            return cost_of(task) if task is not None else 1.0

        late = find_timed_out(
            list(job_pcbs.values()), worker_pcbs, cost_of_task, stats.tracker, now
        )
        taken = 0
        for task_pcb in late:
            worker_uuid = task_pcb.worker_uuid
            if take_back(task_pcb, worker_pcbs, stats.tracker, now, cost_of_task(task_pcb)):
                taken += 1
                jobs.sync_worker_state(worker_uuid)
                logger.warning(
                    "Task %s of job %s timed out on worker %s; requeued",
                    task_pcb.task_id,
                    task_pcb.job_id,
                    worker_uuid,
                )
        if taken:
            await jobs.dispatch_pending()
        await jobs.speculate_pending()
        return taken

    async def run(self) -> None:
        while True:
            try:
                await self.check_once()
            except Exception:  # keep the monitor alive whatever happens
                logger.error("Timeout check failed", exc_info=True)
            await asyncio.sleep(self.interval)
