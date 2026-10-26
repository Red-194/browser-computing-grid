"""A simulated grid, to compare scheduling algorithms without any devices.

It is not a model of the scheduler: it runs the *real* scheduler classes, the
real PCBs, the real speed tracker, capacity policy and timeout logic. Only the
workers, the network and the clock are pretend. Time is virtual, so a run that
would take an hour finishes in milliseconds, and the same seed always gives the
same result.

What the numbers mean: the worker speeds below are assumptions (some taken from
our measurements, see SCENARIOS). They show how the algorithms behave when
workers differ, fail or stall. They do not measure the real grid.
"""
import heapq
import random
from collections import Counter
from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import uuid4

from ...models.pcb import JobPCB, JobStatus, WorkerPCB
from ...models.worker import WorkerStates
from . import build
from .capacity import CapacityPolicy
from .reallocation import find_timed_out, take_back
from .stats import SpeedTracker

INFINITY = float("inf")


@dataclass
class SimWorker:
    uuid: str
    rate: float  # seconds per unit of work (smaller is faster)
    cores: int = 4
    latency: float = 0.05  # seconds for a task to arrive / an answer to come back
    dies_at: float | None = None  # connection lost (tab closed)
    hangs_at: float | None = None  # stays connected but never answers again
    slows_at: float | None = None  # becomes slower from this time (background tab)
    slow_factor: float = 1.0


@dataclass
class SimTask:
    cost: float  # the real amount of work
    known_cost: float | None = None  # what the scheduler is told; defaults to `cost`


@dataclass
class SimResult:
    scheduler: str
    completed: bool
    makespan: float  # virtual seconds until the last task was accepted
    ideal: float  # perfect-balance lower bound (no latency, no failures)
    accepted: Counter = field(default_factory=Counter)  # tasks accepted per worker
    retries: int = 0
    timeouts: int = 0
    wasted_seconds: float = 0.0  # compute whose answer was thrown away

    @property
    def efficiency(self) -> float:
        return self.ideal / self.makespan if self.completed and self.makespan > 0 else 0.0


class Simulation:
    def __init__(
        self,
        scheduler: str,
        workers: list[SimWorker],
        tasks: list[SimTask],
        *,
        workload: str = "job",
        use_timeouts: bool = True,
        adaptive_capacity: bool = True,
        seed: int = 0,
        jitter: float = 0.1,
        tick: float = 1.0,
        max_time: float = 3600.0,
        max_retries: int = 3,
    ):
        self.scheduler_name = scheduler
        self.sim_workers = {w.uuid: w for w in workers}
        self.tasks = tasks
        self.workload = workload
        self.use_timeouts = use_timeouts
        self.seed = seed
        self.jitter = jitter
        self.tick = tick
        self.max_time = max_time

        self.clock = 0.0
        self.tracker = SpeedTracker()
        kwargs = {} if scheduler in ("random", "round_robin") else {"tracker": self.tracker}
        self.scheduler = build(scheduler, **kwargs)
        self.policy = CapacityPolicy(self.tracker) if adaptive_capacity else None

        self.job = JobPCB.create(uuid4(), workload, list(range(len(tasks))), max_retries=max_retries)
        self.worker_pcbs = {w.uuid: WorkerPCB(w.uuid, capacity=w.cores) for w in workers}
        self.worker_objects = [
            SimpleNamespace(uuid=w.uuid, cores=w.cores, state=WorkerStates.IDLE) for w in workers
        ]

        self._events: list = []
        self._order = 0
        self._free_at = {w.uuid: 0.0 for w in workers}  # when its compute thread is free
        self._busy = Counter()
        self._accepted = Counter()
        self._wasted = 0.0
        self._finished_at = 0.0

    # ------------------------------------------------------------- running

    def run(self) -> SimResult:
        random.seed(self.seed)  # RandomScheduler draws from the global generator
        for worker in self.sim_workers.values():
            if worker.dies_at is not None:
                self._push(worker.dies_at, "dies", worker.uuid)
        self._dispatch()
        if self.use_timeouts:
            self._push(self.tick, "tick", None)

        while self._events and self.job.status == JobStatus.RUNNING:
            when, _, kind, data = heapq.heappop(self._events)
            if when > self.max_time:
                break
            self.clock = when
            if kind == "result":
                self._on_result(*data)
            elif kind == "dies":
                self._on_death(data)
            elif kind == "tick":
                self._on_tick()

        return self._report()

    def _push(self, when: float, kind: str, data) -> None:
        self._order += 1
        heapq.heappush(self._events, (when, self._order, kind, data))

    # ------------------------------------------------------------ dispatch

    def _known_cost(self, task_id: int) -> float:
        task = self.tasks[task_id]
        return task.known_cost if task.known_cost is not None else task.cost

    def _dispatch(self) -> None:
        waiting = self.job.waiting()
        if not waiting:
            return
        costs = {t.key: self._known_cost(t.task_id) for t in waiting}
        if self.policy is not None:
            typical = costs[waiting[0].key]
            for worker in self.worker_objects:
                self.policy.apply(worker, self.worker_pcbs[worker.uuid], self.workload, typical)

        assignments = self.scheduler.schedule(
            waiting, self.worker_objects, self.worker_pcbs, costs=costs, now=self.clock
        )
        for task_pcb, worker in assignments:
            attempt = task_pcb.assign(worker.uuid, now=self.clock)
            self.worker_pcbs[worker.uuid].assign(task_pcb.key, attempt)
            self._start(self.sim_workers[worker.uuid], task_pcb, attempt)

    def _start(self, worker: SimWorker, task_pcb, attempt: int) -> None:
        """Work out when this worker would finish the task, and schedule the answer."""
        begin = max(self.clock + worker.latency, self._free_at[worker.uuid])
        slow = worker.slow_factor if worker.slows_at is not None and begin >= worker.slows_at else 1.0
        noise = random.Random(f"{self.seed}-{task_pcb.task_id}-{attempt}").uniform(
            1 - self.jitter, 1 + self.jitter
        )
        duration = self.tasks[task_pcb.task_id].cost * worker.rate * slow * noise
        end = begin + duration
        self._free_at[worker.uuid] = end

        delivered = end + worker.latency
        alive_until = min(
            worker.dies_at if worker.dies_at is not None else INFINITY,
            worker.hangs_at if worker.hangs_at is not None else INFINITY,
        )
        if delivered <= alive_until:
            self._busy[worker.uuid] += duration
            self._push(delivered, "result", (worker.uuid, task_pcb.task_id, attempt, duration))
        # otherwise the answer never arrives: the worker died or is stuck

    # -------------------------------------------------------------- events

    def _on_result(self, uuid: str, task_id: int, attempt: int, duration: float) -> None:
        task_pcb = self.job.task(task_id)
        outcome = task_pcb.complete(attempt, worker_uuid=uuid, now=self.clock)
        if outcome.value == "stale":
            self._wasted += duration
            return
        self.worker_pcbs[uuid].release(task_pcb.key)
        self.tracker.record_result(uuid, self.workload, self._known_cost(task_id), duration)
        self._accepted[uuid] += 1
        self._finished_at = self.clock
        self._dispatch()

    def _on_death(self, uuid: str) -> None:
        lost = self.worker_pcbs[uuid].mark_offline()
        if lost:
            self.tracker.record_failure(uuid)
        for (_, task_id), attempt in lost:
            self.job.task(task_id).requeue("worker died", now=self.clock, attempt=attempt)
        self._dispatch()

    def _on_tick(self) -> None:
        late = find_timed_out(
            [self.job],
            self.worker_pcbs,
            lambda t: self._known_cost(t.task_id),
            self.tracker,
            self.clock,
        )
        taken = [t for t in late if take_back(t, self.worker_pcbs, self.tracker, self.clock)]
        if taken:
            self._dispatch()
        if self.job.status == JobStatus.RUNNING:
            self._push(self.clock + self.tick, "tick", None)

    # -------------------------------------------------------------- report

    def _report(self) -> SimResult:
        completed = self.job.status == JobStatus.DONE
        speed = sum(1.0 / w.rate for w in self.sim_workers.values())
        ideal = sum(t.cost for t in self.tasks) / speed if speed else INFINITY
        return SimResult(
            scheduler=self.scheduler_name,
            completed=completed,
            makespan=self._finished_at if completed else self.clock,
            ideal=ideal,
            accepted=Counter(self._accepted),
            retries=sum(t.retries for t in self.job.tasks.values()),
            timeouts=sum(
                self.tracker.snapshot()["workers"].get(w, {}).get("timeouts", 0)
                for w in self.sim_workers
            ),
            wasted_seconds=self._wasted,
        )


# ---------------------------------------------------------------- scenarios


def _rate_from_mb_per_s(mb_per_s: float) -> float:
    return 1.0 / (mb_per_s * 1_000_000)


def _equal_tasks(count: int, cost: float) -> list[SimTask]:
    return [SimTask(cost) for _ in range(count)]


def scenario_homogeneous():
    """Four identical workers, equal tasks: the algorithms should tie."""
    workers = [SimWorker(f"w{i}", rate=0.01) for i in range(4)]
    return dict(workers=workers, tasks=_equal_tasks(200, 100), workload="job")


def scenario_measured_lz4():
    """Three devices at the speeds we measured for lz4 (MB/s): local 59, a middle
    one 30 (assumed), remote 12. 123 chunks of 256 KiB. Each chunk computes in a
    few milliseconds but takes about 100 ms to send and return, so the job is
    bound by the network and every algorithm ties."""
    workers = [
        SimWorker("local", rate=_rate_from_mb_per_s(59.2)),
        SimWorker("middle", rate=_rate_from_mb_per_s(30.0)),
        SimWorker("remote", rate=_rate_from_mb_per_s(11.9)),
    ]
    return dict(workers=workers, tasks=_equal_tasks(123, 262144), workload="compression")


def scenario_measured_zstd():
    """The same three devices for zstd-fastest: local 26.8, middle 15 (assumed),
    remote 8.5. The gap between local and remote is narrower than for lz4."""
    workers = [
        SimWorker("local", rate=_rate_from_mb_per_s(26.8)),
        SimWorker("middle", rate=_rate_from_mb_per_s(15.0)),
        SimWorker("remote", rate=_rate_from_mb_per_s(8.5)),
    ]
    return dict(workers=workers, tasks=_equal_tasks(123, 262144), workload="compression")


def scenario_heterogeneous_compute():
    """Compute-heavy tasks (seconds each) on three devices 5x, 2x and 1x as fast.
    Here speed matters more than the network, and the end of the job is where a
    slow worker can hold everything up."""
    workers = [
        SimWorker("fast", rate=0.2),
        SimWorker("medium", rate=0.5),
        SimWorker("slow", rate=1.0),
    ]
    return dict(workers=workers, tasks=_equal_tasks(60, 10), workload="job")


def scenario_uneven_tasks():
    """N-Queens-like: task sizes follow a heavy-tailed spread but the scheduler
    is told every task costs 1 (the real estimator cannot know). Workers are 1x,
    1x, 2x and 4x as fast."""
    rng = random.Random(7)
    tasks = [SimTask(cost=rng.lognormvariate(0.0, 1.0), known_cost=1.0) for _ in range(120)]
    workers = [
        SimWorker("slow-a", rate=1.0),
        SimWorker("slow-b", rate=1.0),
        SimWorker("fast", rate=0.5),
        SimWorker("fastest", rate=0.25),
    ]
    return dict(workers=workers, tasks=tasks, workload="nqueens")


def scenario_known_uneven_sizes():
    """Like uneven_tasks, but the scheduler is told each task's true size (as it
    is for compression chunks, regex batches and Mandelbrot tiles). This is where
    giving big tasks to fast workers can pay off."""
    rng = random.Random(7)
    tasks = []
    for _ in range(120):
        size = rng.lognormvariate(0.0, 1.0)
        tasks.append(SimTask(cost=size, known_cost=size))
    workers = [
        SimWorker("slow-a", rate=1.0),
        SimWorker("slow-b", rate=1.0),
        SimWorker("fast", rate=0.5),
        SimWorker("fastest", rate=0.25),
    ]
    return dict(workers=workers, tasks=tasks, workload="regex")


def scenario_worker_dies():
    """Four equal workers; one loses its connection 20 s in (tab closed)."""
    workers = [SimWorker(f"w{i}", rate=0.05) for i in range(4)]
    workers[0].dies_at = 20.0
    return dict(workers=workers, tasks=_equal_tasks(120, 100), workload="job")


def scenario_worker_hangs():
    """Four equal workers; one stays connected but stops answering at 10 s."""
    workers = [SimWorker(f"w{i}", rate=0.05) for i in range(4)]
    workers[0].hangs_at = 10.0
    return dict(workers=workers, tasks=_equal_tasks(120, 100), workload="job")


def scenario_throttled_tab():
    """Four equal workers; one becomes 8x slower at 15 s (a tab sent to the
    background gets throttled)."""
    workers = [SimWorker(f"w{i}", rate=0.05) for i in range(4)]
    workers[0].slows_at = 15.0
    workers[0].slow_factor = 8.0
    return dict(workers=workers, tasks=_equal_tasks(160, 100), workload="job")


SCENARIOS = {
    "homogeneous": scenario_homogeneous,
    "measured_lz4": scenario_measured_lz4,
    "measured_zstd": scenario_measured_zstd,
    "heterogeneous_compute": scenario_heterogeneous_compute,
    "uneven_tasks": scenario_uneven_tasks,
    "known_uneven_sizes": scenario_known_uneven_sizes,
    "worker_dies": scenario_worker_dies,
    "worker_hangs": scenario_worker_hangs,
    "throttled_tab": scenario_throttled_tab,
}


def run_scenario(name: str, scheduler: str, **overrides) -> SimResult:
    """Run one scenario with one algorithm. `overrides` go to Simulation."""
    setup = SCENARIOS[name]()
    options = {"seed": 0, **overrides}
    return Simulation(scheduler, **setup, **options).run()
