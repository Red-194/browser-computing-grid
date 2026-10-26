"""Control blocks (PCBs) for tasks, workers and jobs.

A control block is the controller's record of one task, worker or job. These
classes hold state only. They do not send anything or know about WebSockets, so
the scheduler can be tested without a browser.

Task life:

    WAITING --assign--> RUNNING --complete--> DONE
       ^                   |
       +----- requeue -----+--- (too many retries) ---> FAILED

DONE and FAILED are final.

Every assign() starts a new numbered attempt. A result only counts if it
carries the number of the current attempt. A result from an older attempt
(the task was taken away and given to someone else) is "stale": it is ignored,
but kept so it can be compared with the accepted answer. Tasks are
deterministic, so two different answers for one task mean a worker is faulty.

Every block can be turned into plain dicts with to_dict() and rebuilt with
from_dict(). Times are time.monotonic() values: they only mean something to the
process that made them, so a restored block should have its times reset.
"""
import bisect
import time
from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID

from .worker import WorkerStates

TaskKey = tuple[UUID, int]


class TaskState(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class JobStatus(str, Enum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class CompletionOutcome(str, Enum):
    ACCEPTED = "accepted"
    STALE = "stale"


class InvalidTransition(ValueError):
    """A control block was asked to make a move its state does not allow."""


DEFAULT_MAX_RETRIES = 3

# How many tasks one worker may hold at once. More than one lets a worker start
# its next task straight away instead of waiting for the network.
DEFAULT_WORKER_CAPACITY = 2


@dataclass
class StaleResult:
    """An answer that arrived for an attempt that is no longer current."""

    attempt: int
    worker_uuid: str | None
    digest: str | None

    def to_dict(self) -> dict:
        return {
            "attempt": self.attempt,
            "worker_uuid": self.worker_uuid,
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StaleResult":
        return cls(data["attempt"], data["worker_uuid"], data["digest"])


@dataclass
class TaskPCB:
    job_id: UUID
    task_id: int
    workload: str
    state: TaskState = TaskState.WAITING
    worker_uuid: str | None = None
    attempt: int = 0  # number of the current (or latest) attempt; 0 = never assigned
    retries: int = 0
    max_retries: int = DEFAULT_MAX_RETRIES
    last_error: str | None = None
    assigned_at: float | None = None
    finished_at: float | None = None
    accepted_digest: str | None = None
    stale_results: list[StaleResult] = field(default_factory=list)
    # Speculative copies running on other workers: attempt -> (worker, started).
    # The first answer from the original or any copy wins.
    backups: dict[int, tuple[str, float]] = field(default_factory=dict)
    issued: int = 0  # highest attempt number handed out (copies included)
    last_worker: str | None = None  # the worker it was last taken back from
    # The job that owns this task, so it can keep its counts and waiting list
    # up to date without rescanning every task (set by JobPCB).
    _job: "JobPCB | None" = field(default=None, repr=False, compare=False)

    @property
    def key(self) -> TaskKey:
        return (self.job_id, self.task_id)

    def _move_to(self, new: "TaskState") -> None:
        """The only place a task's state changes."""
        old = self.state
        self.state = new
        if self._job is not None and old != new:
            self._job._moved(self.task_id, old, new)

    @property
    def is_final(self) -> bool:
        return self.state in (TaskState.DONE, TaskState.FAILED)

    def assign(self, worker_uuid: str, now: float | None = None) -> int:
        """Hand the task to a worker. Returns the new attempt number, which the
        worker must send back with its result."""
        self._require(TaskState.WAITING, "assign")
        self._move_to(TaskState.RUNNING)
        self.worker_uuid = worker_uuid
        self.assigned_at = _now(now)
        self.issued = max(self.issued, self.attempt) + 1
        self.attempt = self.issued
        return self.attempt

    def assign_backup(self, worker_uuid: str, now: float | None = None) -> int:
        """Also run this RUNNING task on another worker (work stealing).

        The original keeps running; whichever answers first is accepted and the
        other answer becomes a stale result. Returns the copy's attempt number.
        """
        self._require(TaskState.RUNNING, "assign a backup")
        if worker_uuid == self.worker_uuid or any(w == worker_uuid for w, _ in self.backups.values()):
            raise InvalidTransition(f"worker {worker_uuid} already runs task {self.key}")
        self.issued = max(self.issued, self.attempt) + 1
        self.backups[self.issued] = (worker_uuid, _now(now))
        return self.issued

    def holders(self) -> list[tuple[str, int]]:
        """Every (worker, attempt) currently running this task."""
        if self.state != TaskState.RUNNING or self.worker_uuid is None:
            return []
        return [(self.worker_uuid, self.attempt)] + [
            (worker, attempt) for attempt, (worker, _) in self.backups.items()
        ]

    def complete(
        self,
        attempt: int,
        worker_uuid: str | None = None,
        digest: str | None = None,
        now: float | None = None,
    ) -> CompletionOutcome:
        """A result arrived for `attempt`.

        It is accepted only if the task is RUNNING and this is the current
        attempt (and, if given, from the worker that holds it). Anything else
        is STALE: not an error, just not the answer we are waiting for.
        `digest` is a fingerprint of the answer, made by the caller.
        """
        is_backup = (
            attempt in self.backups
            and (worker_uuid is None or worker_uuid == self.backups[attempt][0])
        )
        current = self.state == TaskState.RUNNING and (
            is_backup
            or (
                attempt == self.attempt
                and (worker_uuid is None or worker_uuid == self.worker_uuid)
            )
        )

        if current:
            self.backups = {}
            self.attempt = attempt
            if worker_uuid is not None:
                self.worker_uuid = worker_uuid
            self._move_to(TaskState.DONE)
            self.finished_at = _now(now)
            self.accepted_digest = digest
            return CompletionOutcome.ACCEPTED

        already_counted = self.state == TaskState.DONE and attempt == self.attempt
        if not already_counted:  # a repeat of the accepted answer adds nothing
            self.stale_results.append(StaleResult(attempt, worker_uuid, digest))
        return CompletionOutcome.STALE

    def disagreements(self) -> list[StaleResult]:
        """Stale answers whose fingerprint differs from the accepted answer.

        Only meaningful once the task is DONE. Each entry means two workers
        returned different answers for the same deterministic task.
        """
        if self.state != TaskState.DONE or self.accepted_digest is None:
            return []
        return [
            stale
            for stale in self.stale_results
            if stale.digest is not None and stale.digest != self.accepted_digest
        ]

    def requeue(
        self,
        reason: str,
        now: float | None = None,
        attempt: int | None = None,
    ) -> TaskState | None:
        """Take the task back from its worker (worker lost, timed out, errored).

        It goes back to WAITING and the retry count goes up. Once the retries
        are used up it becomes FAILED instead. Returns the new state.

        If `attempt` is given and it is no longer the current running attempt
        (someone else already handled the loss), nothing happens and None is
        returned. Without `attempt`, requeueing a task that is not RUNNING
        raises InvalidTransition.
        """
        if attempt is not None and self.state != TaskState.RUNNING:
            return None

        if attempt is not None and attempt in self.backups:
            # A speculative copy was lost: the original is still running.
            del self.backups[attempt]
            return TaskState.RUNNING

        if attempt is not None and attempt != self.attempt:
            return None

        self._require(TaskState.RUNNING, "requeue")

        if self.backups:
            # The original was lost but a copy is still running: it takes over.
            promoted = min(self.backups)
            self.worker_uuid, self.assigned_at = self.backups.pop(promoted)
            self.attempt = promoted
            self.last_error = reason
            return TaskState.RUNNING

        self.last_error = reason
        self.last_worker = self.worker_uuid
        self.worker_uuid = None
        self.assigned_at = None

        if self.retries >= self.max_retries:
            self._move_to(TaskState.FAILED)
            self.finished_at = _now(now)
        else:
            self.retries += 1
            self._move_to(TaskState.WAITING)

        return self.state

    def fail(self, reason: str, now: float | None = None) -> None:
        """Give up on the task without retrying (for example a bad config)."""
        if self.is_final:
            raise InvalidTransition(
                f"task {self.key} is already {self.state.value}, cannot fail"
            )
        self.last_error = reason
        self._move_to(TaskState.FAILED)
        self.worker_uuid = None
        self.assigned_at = None
        self.finished_at = _now(now)

    def is_timed_out(self, timeout: float, now: float | None = None) -> bool:
        """True if the task has been RUNNING for longer than `timeout` seconds."""
        if self.state != TaskState.RUNNING or self.assigned_at is None:
            return False
        return _now(now) - self.assigned_at > timeout

    def to_dict(self) -> dict:
        return {
            "job_id": str(self.job_id),
            "task_id": self.task_id,
            "workload": self.workload,
            "state": self.state.value,
            "worker_uuid": self.worker_uuid,
            "attempt": self.attempt,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "last_error": self.last_error,
            "assigned_at": self.assigned_at,
            "finished_at": self.finished_at,
            "accepted_digest": self.accepted_digest,
            "stale_results": [s.to_dict() for s in self.stale_results],
            "backups": {str(a): list(v) for a, v in self.backups.items()},
            "issued": self.issued,
            "last_worker": self.last_worker,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskPCB":
        return cls(
            job_id=UUID(data["job_id"]),
            task_id=data["task_id"],
            workload=data["workload"],
            state=TaskState(data["state"]),
            worker_uuid=data["worker_uuid"],
            attempt=data["attempt"],
            retries=data["retries"],
            max_retries=data["max_retries"],
            last_error=data["last_error"],
            assigned_at=data["assigned_at"],
            finished_at=data["finished_at"],
            accepted_digest=data["accepted_digest"],
            stale_results=[StaleResult.from_dict(s) for s in data["stale_results"]],
            backups={int(a): tuple(v) for a, v in data.get("backups", {}).items()},
            issued=data.get("issued", data["attempt"]),
            last_worker=data.get("last_worker"),
        )

    def _require(self, expected: TaskState, action: str) -> None:
        if self.state != expected:
            raise InvalidTransition(
                f"task {self.key} is {self.state.value}, cannot {action} "
                f"(needs {expected.value})"
            )


@dataclass
class WorkerPCB:
    """One worker. It may hold up to `capacity` tasks at once.

    State: OFFLINE when disconnected, IDLE when online with nothing running,
    BUSY when it holds at least one task. Whether it can take another task is
    `has_free_slot`, which stays true while it holds fewer than `capacity`.
    """

    uuid: str
    state: str = WorkerStates.IDLE
    capacity: int = DEFAULT_WORKER_CAPACITY
    running: dict[TaskKey, int] = field(default_factory=dict)  # task -> attempt
    last_seen: float = 0.0
    completed_tasks: int = 0

    def __post_init__(self):
        if self.capacity < 1:
            raise ValueError("worker capacity must be at least 1")

    @property
    def is_online(self) -> bool:
        return self.state != WorkerStates.OFFLINE

    @property
    def has_free_slot(self) -> bool:
        return self.is_online and len(self.running) < self.capacity

    def assign(self, task_key: TaskKey, attempt: int) -> None:
        """The worker starts attempt `attempt` of a task."""
        if not self.has_free_slot:
            raise InvalidTransition(
                f"worker {self.uuid} is {self.state} with "
                f"{len(self.running)}/{self.capacity} tasks, cannot take another"
            )
        if task_key in self.running:
            raise InvalidTransition(
                f"worker {self.uuid} already holds task {task_key}"
            )
        self.running[task_key] = attempt
        self.state = WorkerStates.BUSY

    def release(self, task_key: TaskKey, completed: bool = True) -> bool:
        """The worker is no longer holding this task (it answered, or we gave up
        on it). Returns False if it was not holding it, which is not an error:
        a worker can answer for a task we already took away."""
        if task_key not in self.running:
            return False
        del self.running[task_key]
        if completed:
            self.completed_tasks += 1
        if not self.running and self.is_online:
            self.state = WorkerStates.IDLE
        return True

    def mark_offline(self) -> list[tuple[TaskKey, int]]:
        """The worker disconnected. Returns every (task key, attempt) it was
        holding so the scheduler can requeue exactly those attempts."""
        lost = list(self.running.items())
        self.state = WorkerStates.OFFLINE
        self.running = {}
        return lost

    def mark_online(self, now: float | None = None) -> None:
        """The worker (re)connected. A reconnecting worker starts with no tasks."""
        self.state = WorkerStates.IDLE
        self.running = {}
        self.last_seen = _now(now)

    def touch(self, now: float | None = None) -> None:
        """Record that we heard from the worker (heartbeat, pong, result)."""
        self.last_seen = _now(now)

    def silent_for(self, now: float | None = None) -> float:
        return _now(now) - self.last_seen

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "state": self.state,
            "capacity": self.capacity,
            "running": [
                {"job_id": str(job_id), "task_id": task_id, "attempt": attempt}
                for (job_id, task_id), attempt in self.running.items()
            ],
            "last_seen": self.last_seen,
            "completed_tasks": self.completed_tasks,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkerPCB":
        return cls(
            uuid=data["uuid"],
            state=data["state"],
            capacity=data["capacity"],
            running={
                (UUID(r["job_id"]), r["task_id"]): r["attempt"]
                for r in data["running"]
            },
            last_seen=data["last_seen"],
            completed_tasks=data["completed_tasks"],
        )


@dataclass
class JobPCB:
    """One job and the control blocks of all its tasks."""

    job_id: UUID
    workload: str
    tasks: dict[int, TaskPCB] = field(default_factory=dict)

    def __post_init__(self):
        # Kept up to date by TaskPCB._move_to, so these never need a full scan.
        self._counts = {state: 0 for state in TaskState}
        self._waiting: list[int] = []  # task ids, sorted
        for task_id in sorted(self.tasks):
            task = self.tasks[task_id]
            task._job = self
            self._counts[task.state] += 1
            if task.state == TaskState.WAITING:
                self._waiting.append(task_id)

    def _moved(self, task_id: int, old: TaskState, new: TaskState) -> None:
        self._counts[old] -= 1
        self._counts[new] += 1
        if old == TaskState.WAITING:
            index = bisect.bisect_left(self._waiting, task_id)
            if index < len(self._waiting) and self._waiting[index] == task_id:
                del self._waiting[index]
        if new == TaskState.WAITING:
            bisect.insort(self._waiting, task_id)

    @classmethod
    def create(
        cls,
        job_id: UUID,
        workload: str,
        task_ids: list[int],
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> "JobPCB":
        return cls(
            job_id=job_id,
            workload=workload,
            tasks={
                task_id: TaskPCB(job_id, task_id, workload, max_retries=max_retries)
                for task_id in task_ids
            },
        )

    def task(self, task_id: int) -> TaskPCB:
        return self.tasks[task_id]

    def waiting(self, limit: int | None = None) -> list[TaskPCB]:
        """Tasks ready to be given to a worker, lowest task id first. With
        `limit`, only the first `limit` of them."""
        ids = self._waiting if limit is None else self._waiting[:limit]
        return [self.tasks[task_id] for task_id in ids]

    def has_waiting(self) -> bool:
        return bool(self._waiting)

    def count(self, state: TaskState) -> int:
        return self._counts[state]

    def failed_tasks(self) -> list[TaskPCB]:
        return [t for t in self.tasks.values() if t.state == TaskState.FAILED]

    @property
    def status(self) -> JobStatus:
        """FAILED as soon as any task has failed, since the job can no longer
        be completed; DONE when every task is done; otherwise RUNNING."""
        if self._counts[TaskState.FAILED]:
            return JobStatus.FAILED
        if self.tasks and self._counts[TaskState.DONE] == len(self.tasks):
            return JobStatus.DONE
        return JobStatus.RUNNING

    def progress(self) -> dict:
        return {
            "total": len(self.tasks),
            **{state.value: self.count(state) for state in TaskState},
        }

    def to_dict(self) -> dict:
        return {
            "job_id": str(self.job_id),
            "workload": self.workload,
            "tasks": [t.to_dict() for t in self.tasks.values()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JobPCB":
        tasks = [TaskPCB.from_dict(t) for t in data["tasks"]]
        return cls(
            job_id=UUID(data["job_id"]),
            workload=data["workload"],
            tasks={t.task_id: t for t in tasks},
        )


def _now(now: float | None) -> float:
    return time.monotonic() if now is None else now
