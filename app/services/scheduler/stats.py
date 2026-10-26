"""What the controller has learned about each worker.

Modelled on BOINC's per-host, per-application runtime estimate: for every
(worker, workload) pair we keep the mean and variance of "seconds per unit of
work". When a worker has too few samples we fall back to the workload-wide
average (scaled by how fast that worker has been on other workloads), and when
there is nothing at all we say so, so the scheduler can try the worker out.

Times here are plain seconds. Anything that takes a clock accepts `now` so tests
and the simulator can use a virtual one.
"""
import math
import time
from dataclasses import dataclass

# Weight of a new sample in the running average. Early samples use 1/n instead
# so the first few results are a plain average.
EWMA_ALPHA = 0.3
# Samples needed before a worker's own history is trusted (BOINC uses 10; with
# a handful of devices and short jobs we cannot wait that long).
MIN_SAMPLES = 3
# How much old reliability evidence is kept each time new evidence arrives.
RELIABILITY_DECAY = 0.9
# Timeouts in a row before a worker is left out for a while.
QUARANTINE_AFTER = 3
QUARANTINE_SECONDS = 30.0
# Each repeat offence doubles the time (30 s, 60 s, 120 s, ...) up to this cap.
# A good result starts it again from the beginning.
QUARANTINE_MAX_SECONDS = 600.0

# Smallest amount of work counted, so a zero cost never divides by zero.
MIN_COST = 1e-9


@dataclass
class Estimate:
    """A guess at how long a task will take on a worker."""

    mean: float  # seconds
    std: float  # seconds
    source: str  # worker_workload, scaled_workload_average, workload_average
    samples: int  # samples behind the number the guess came from


class _Rate:
    """Running mean and variance of seconds per unit of work."""

    def __init__(self):
        self.n = 0
        self.mean = 0.0
        self.var = 0.0

    def add(self, value: float) -> None:
        self.n += 1
        if self.n == 1:
            self.mean = value
            self.var = 0.0
            return
        alpha = max(EWMA_ALPHA, 1.0 / self.n)
        diff = value - self.mean
        self.mean += alpha * diff
        self.var = (1 - alpha) * (self.var + alpha * diff * diff)

    @property
    def std(self) -> float:
        return math.sqrt(max(self.var, 0.0))


class _Record:
    """Reliability evidence for one worker (decayed counts)."""

    def __init__(self):
        self.successes = 0.0
        self.timeouts = 0.0
        self.failures = 0.0
        self.consecutive_timeouts = 0
        self.quarantined_until = 0.0
        self.strikes = 0  # times quarantined since the last good result
        self.total_timeouts = 0
        self.total_failures = 0
        self.total_successes = 0

    def decay(self) -> None:
        self.successes *= RELIABILITY_DECAY
        self.timeouts *= RELIABILITY_DECAY
        self.failures *= RELIABILITY_DECAY


class SpeedTracker:
    def __init__(self, min_samples: int = MIN_SAMPLES):
        self.min_samples = min_samples
        self._per_worker: dict[tuple[str, str], _Rate] = {}
        self._per_workload: dict[str, _Rate] = {}
        self._records: dict[str, _Record] = {}

    # ---------------------------------------------------------- recording

    def record_result(self, worker: str, workload: str, cost: float, seconds: float) -> None:
        """A task finished: `seconds` of compute for `cost` units of work."""
        if seconds is None or seconds <= 0:
            return
        rate = seconds / max(cost, MIN_COST)
        self._per_worker.setdefault((worker, workload), _Rate()).add(rate)
        self._per_workload.setdefault(workload, _Rate()).add(rate)

        record = self._record(worker)
        record.decay()
        record.successes += 1
        record.total_successes += 1
        record.consecutive_timeouts = 0
        record.quarantined_until = 0.0
        record.strikes = 0

    def record_lower_bound(self, worker: str, workload: str, cost: float, seconds: float) -> None:
        """A task has taken at least `seconds` and was given up on. Counted as a
        speed sample (the real time can only be longer), so a worker that has
        slowed down stops being believed to be fast."""
        if seconds is None or seconds <= 0:
            return
        rate = seconds / max(cost, MIN_COST)
        self._per_worker.setdefault((worker, workload), _Rate()).add(rate)
        self._per_workload.setdefault(workload, _Rate()).add(rate)

    def record_timeout(self, worker: str, now: float | None = None) -> None:
        record = self._record(worker)
        record.decay()
        record.timeouts += 1
        record.total_timeouts += 1
        record.consecutive_timeouts += 1
        # Only a worker that is not already quarantined can be quarantined again:
        # several of its tasks timing out together count as one offence.
        if (
            record.consecutive_timeouts >= QUARANTINE_AFTER
            and _now(now) >= record.quarantined_until
        ):
            seconds = min(QUARANTINE_SECONDS * 2 ** record.strikes, QUARANTINE_MAX_SECONDS)
            record.quarantined_until = _now(now) + seconds
            record.strikes += 1

    def record_failure(self, worker: str) -> None:
        """The worker was lost or a send to it failed."""
        record = self._record(worker)
        record.decay()
        record.failures += 1
        record.total_failures += 1

    def clear_quarantine(self, worker: str) -> None:
        """A worker that reconnects gets a fresh start."""
        record = self._records.get(worker)
        if record is not None:
            record.consecutive_timeouts = 0
            record.quarantined_until = 0.0
            record.strikes = 0

    # ----------------------------------------------------------- questions

    def samples(self, worker: str, workload: str) -> int:
        rate = self._per_worker.get((worker, workload))
        return rate.n if rate else 0

    def total_samples(self, workload: str) -> int:
        rate = self._per_workload.get(workload)
        return rate.n if rate else 0

    def speed_factor(self, worker: str) -> float:
        """How this worker compares with the average worker (below 1 = faster).

        Geometric mean, over the workloads it has run, of its own seconds per
        unit divided by the workload average. 1.0 if we know nothing.
        """
        logs = []
        for (name, workload), rate in self._per_worker.items():
            if name != worker or rate.n < 1:
                continue
            average = self._per_workload.get(workload)
            if average and average.mean > 0 and rate.mean > 0:
                logs.append(math.log(rate.mean / average.mean))
        return math.exp(sum(logs) / len(logs)) if logs else 1.0

    def estimate(self, worker: str, workload: str, cost: float) -> Estimate | None:
        """Expected compute time for `cost` units, or None if nothing is known."""
        cost = max(cost, MIN_COST)

        own = self._per_worker.get((worker, workload))
        if own and own.n >= self.min_samples:
            return Estimate(own.mean * cost, own.std * cost, "worker_workload", own.n)

        average = self._per_workload.get(workload)
        if average is None or average.n < 1:
            return None

        has_history = any(name == worker for (name, _) in self._per_worker)
        if has_history:
            factor = self.speed_factor(worker)
            return Estimate(
                average.mean * factor * cost,
                average.std * factor * cost,
                "scaled_workload_average",
                average.n,
            )
        return Estimate(average.mean * cost, average.std * cost, "workload_average", average.n)

    def reliability(self, worker: str) -> float:
        """Between 0 and 1. New workers start at 1; timeouts and losses lower it."""
        record = self._records.get(worker)
        if record is None:
            return 1.0
        good = record.successes + 1.0
        return good / (good + record.timeouts + record.failures)

    def is_quarantined(self, worker: str, now: float | None = None) -> bool:
        record = self._records.get(worker)
        return record is not None and _now(now) < record.quarantined_until

    def snapshot(self) -> dict:
        """Everything we know, for the stats endpoint."""
        workers: dict[str, dict] = {}
        for (worker, workload), rate in self._per_worker.items():
            entry = workers.setdefault(worker, {"workloads": {}})
            entry["workloads"][workload] = {
                "samples": rate.n,
                "seconds_per_unit": rate.mean,
                "std": rate.std,
            }
        for worker, record in self._records.items():
            entry = workers.setdefault(worker, {"workloads": {}})
            entry.update(
                {
                    "reliability": round(self.reliability(worker), 3),
                    "successes": record.total_successes,
                    "timeouts": record.total_timeouts,
                    "failures": record.total_failures,
                    "consecutive_timeouts": record.consecutive_timeouts,
                    "quarantined": self.is_quarantined(worker),
                    "speed_factor": round(self.speed_factor(worker), 3),
                }
            )
        return {
            "workers": workers,
            "workloads": {
                workload: {"samples": rate.n, "seconds_per_unit": rate.mean, "std": rate.std}
                for workload, rate in self._per_workload.items()
            },
        }

    def reset(self) -> None:
        self._per_worker.clear()
        self._per_workload.clear()
        self._records.clear()

    def _record(self, worker: str) -> _Record:
        return self._records.setdefault(worker, _Record())


def _now(now: float | None) -> float:
    return time.monotonic() if now is None else now


# The tracker the running server uses. Tests and the simulator build their own.
tracker = SpeedTracker()
