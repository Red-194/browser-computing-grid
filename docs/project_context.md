# Project context and direction

Working notes so the project's aim, current state and open design questions don't have to be re-explained. Items marked **Decided** come from the project owner. Items marked **Proposed** are suggestions that still need a decision. Items marked **Finding** are things that were checked or measured.

Last updated: 2026-10-26.

## 1. Aim

A **portable** computing system that processes work **securely** and **reliably** using WebAssembly.

- **Portable:** a device joins by opening a web page. Nothing is installed on workers.
- **Secure:** tasks run inside the browser's WASM sandbox. (See section 6 for what is not yet secure.)
- **Reliable:** work survives workers leaving, slow workers and failures.

The workloads (Mandelbrot, SAT, `sat_batch`, compression, regex, N-Queens) are test cases for the system. They are not the contribution. See `scope_updated.md` for the research plan (adaptive, workload-aware scheduling).

## 2. Scope for now (Decided)

- Run locally: one controller on a PC in a lab, with the lab's browsers connecting to it over the same subnet (each PC has its own IP, for example `.12`, `.13`). The worker types the controller's IP by hand.
- **Demo target: up to 10 connected devices.** Clustering, multiple servers and large-scale tuning are out of scope; they stay as future work.
- Job submission from the controller PC only.
- Out of scope for now: sign-in, the browser extension, remote access from other networks, and the website idea. (The long-term vision is a website where a user signs in and an extension builds a local coordinator; a browser extension cannot open a listening socket, so it would need a small native helper, an elected browser tab as coordinator over WebRTC, or the website itself as coordinator. Not decided.)
- Transport: plain `http://` / `ws://` for the demo. Devices must use `http://`, not `https://`, or the browser shows `ERR_SSL_PROTOCOL_ERROR`.

## 3. Where the project is

Sprint-based. Done:

- Worker connection (register, heartbeat, ping, reconnect, dashboard feed).
- Job splitting into tasks.
- Execution in the WASM runtime and aggregation of results.
- Six workloads end to end (Mandelbrot, SAT, `sat_batch`, compression, regex, N-Queens).
- Compression with real file upload (`POST /jobs/compression/upload`, `scripts/compress_file.py`).
- **Control blocks (PCBs)** in `app/models/pcb.py`, with tests in `tests/test_pcb.py` (see section 5).
- **PCBs connected to the controller** (teammate's commit `a567e86`, "failure recovery somehow works"): pull-style dispatch by free slots, attempt numbers sent to workers and returned, requeue on disconnect and heartbeat timeout. Reviewed and corrected on 2026-10-26 (see "Review of the controller integration" in section 5). **Verified live on 2026-10-26** with a laptop (Firefox and Chrome tabs) and a phone: closing a worker mid-job (N-Queens n=17) requeued its running tasks and the job finished with the correct answer, twice.

- **Adaptive, modular scheduler** (built 2026-10-26, `app/services/scheduler/`; see "Adaptive scheduler" in section 5): five selectable algorithms, a per-worker speed and reliability tracker, adaptive capacity, adaptive timeouts that reallocate stuck tasks, live switching, and a simulator. Run live on 2 to 3 workers; see "Live results" in section 5.
- **Work stealing** (built 2026-10-26): an idle worker also runs a task still running elsewhere, first answer wins. See "Work stealing" in section 5.
- **Performance work** (2026-10-26): a pool of compute threads per tab, batched task and result messages, task-error reporting, and fixes that stop the controller slowing down on large jobs. Roughly 5x to 70x faster on the test jobs. See "Performance work" in section 5.

Next: compare the algorithms on devices that really differ in speed (the phone), with stealing on and off; build a better Mandelbrot cost estimate (every tile is treated as equal cost, but about 70% finish instantly); then decide the default algorithm (still `random`) from real timings.

## 4. What the old scheduler placeholder could not do (kept for the reasoning; the adaptive scheduler in section 5 addresses these)

`RandomScheduler` (and `RoundRobinScheduler`) assign every task up front, at submit time, and never revisit it. So:

- No load balancing: a slow device gets as many tasks as a fast one and sets the job's finish time.
- No recovery: if a worker disappears, its tasks are lost and the job hangs. This was reproduced during testing after a worker tab reloaded.
- No queue: nothing waits for a worker to become free.
- No use of measured worker speed.

## 5. Scheduler design

### Decided

- Build **control blocks (PCBs)** for every task, worker and job.
- **Only the current attempt counts.** Every assignment is a numbered attempt, and a result is accepted only if it carries the current attempt number. If a task was reassigned, the new attempt wins.
- **Keep the stale answer for comparison.** A late answer from an older attempt is ignored but stored. Tasks are deterministic, so if it differs from the accepted answer, a worker is faulty. This is a free correctness check on reassigned tasks.
- Cheap result checks (well-formed results, reject error results) will be added where cheap; random re-run sampling can wait.
- Both the recovery from a killed worker and the speed-aware scheduler are required for the demo.

### Implemented (PCB module, now connected to the controller)

- `TaskPCB`: states waiting, running, done, failed. `assign()` starts a numbered attempt. `complete(attempt, worker_uuid, digest)` returns accepted or stale (never an error). `requeue(reason, attempt=...)` is safe to call twice for the same loss. Default retry limit is 3. `is_timed_out()`, `disagreements()`.
- `WorkerPCB`: states idle, busy, offline. Holds up to `capacity` tasks (default 2, `DEFAULT_WORKER_CAPACITY`). `mark_offline()` returns every `(task, attempt)` it held. `release()` returns false if the worker did not hold the task (not an error).
- `JobPCB`: owns the task blocks; `waiting()`, `progress()`, `failed_tasks()`; status is failed as soon as any task fails.
- All three can be saved and loaded as plain dicts (`to_dict()` / `from_dict()`). Times are `time.monotonic()` values and only mean something to the process that made them.
- The module imports only `WorkerStates` from `app/models/worker.py` and does no I/O.

### How the control blocks behave

What the scheduler is for: keep a list of waiting tasks, give a task to a worker when it has a free slot, keep track of who holds what, notice a worker that disappeared or a task that took too long, and put lost tasks back in the list.

Task life (DONE and FAILED are final):

```
WAITING --assign--> RUNNING --complete--> DONE
   ^                   |
   +----- requeue -----+--- (retries used up) ---> FAILED
```

| Event | What the records do |
|---|---|
| Task handed to a worker | Task goes RUNNING under a new attempt number; the worker's slot is taken |
| Result with the current attempt, from the worker holding it | Accepted: task DONE, digest stored, slot freed |
| Result with an older attempt, or from the wrong worker | Stale: ignored, stored with its worker and digest; never an error |
| Worker disconnects | `mark_offline()` returns every `(task, attempt)` it held; each is requeued for exactly that attempt |
| Task runs longer than the timeout | Requeued for that attempt. If the disconnect handler also fires, the second requeue does nothing |
| Requeue with retries left | Task back to WAITING, retry count up |
| Requeue with no retries left | Task FAILED, and so is the job (it can no longer complete) |
| Two answers differ for one task | `disagreements()` lists the stale ones; a worker is faulty (tasks are deterministic) |
| Worker answers for a task already taken away | `release()` returns false instead of failing; its slot frees only when it answers or disconnects |

Reasoning behind the "current attempt wins" rule (the project owner's proposal): the worker that was timed out or lost is the less trustworthy one, and a fenced attempt number stays safe when messages arrive out of order or from several controllers. The cost is some wasted work when the old worker had actually finished, which is small at 10 devices. Neither "first answer wins" nor "current attempt wins" detects a wrong answer, which is why stale answers are compared, not discarded.

The digest (fingerprint of an answer) is separate from the worker's uuid. The uuid says who answered; the digest says what was answered. Two workers with the same answer have the same digest. The digest must leave out per-worker details such as execution time.

### Proposed (defaults chosen, not yet confirmed)

- The retry limit of 3 and the worker capacity of 2 were chosen by the assistant, not the project owner. Both are single constants and per-record overrides.
- Records live in memory next to `app/registry.py`, behind one small interface.
- One background checker looks for timed-out tasks every second or two, instead of a timer per task.
- Task timeout starts generous (for example 60 s); a speed-based timeout can come later because devices differ by about 5x.
- Dispatch is pull-style: a task goes to a worker only when it has a free slot. Claim first (mark running), then send, and undo if the send fails.
- First worker-picking rule: next free worker. The speed-aware rule replaces it later.
- Ignore a websocket close event unless it belongs to the worker's current socket (see race conditions below).

### Not decided yet

- What "speed" means for the speed-aware scheduler (probably units of work per second, per worker, per workload) and how to start with no data (cold start).
- The digest function: it must cover only the answer (for example compressed size and round-trip result), not per-worker details like execution time.
- Result-validation module: per-workload checks. A SAT "satisfiable" model can be checked cheaply against the clauses; compression's round-trip flag is reported by the worker itself.

### Race conditions identified

1. A late result after reassignment (handled by attempt numbers and the stale outcome).
2. Two events for the same loss, such as the disconnect handler and the timeout checker (handled by `requeue(attempt=...)` returning nothing the second time).
3. Claim before send: an `await` during the send could let another event pick the same task or worker.
4. **Reload race (fixed 2026-10-26, found by reading the code; a live reproduction was attempted and the test hung, so the fix is covered by unit tests only):** when a tab reloads, the old socket's close event can arrive after the new socket registers. The disconnect handler used to look the worker up by uuid, so it marked the live worker offline, requeued its tasks and set `worker.websocket = None`, dropping the new connection. `handle_socket_closed` in `app/websocket.py` now acts only if the closing socket is the worker's current socket.
5. For several controllers (future): double claim, stale controller, split brain. These need compare-and-set on a record version, leases, and one owner per record.

### The control blocks in a decentralized setting (discussed, not built)

- The central question is who owns each record and how other nodes learn about changes. Options: shard by owner (each controller owns its own jobs and connected workers; simple, but a dead controller loses its records unless they are copied), a shared store (any controller can take over, but it depends on that store), or fully peer to peer (as Pando does with WebRTC; hardest to make reliable).
- Already in the design: attempt numbers (act as fencing tokens), records that can be saved and loaded as plain dicts, and operations that are safe to repeat (stale results and repeated requeues are normal outcomes, not errors).
- Still needed for several controllers: a version number on each record with compare-and-set, leases that must be renewed instead of failure detection, and time that does not depend on one machine's clock (the PCB uses the local monotonic clock, which is right for local timeouts only).
- Worker data splits in two: connection state (online, busy) belongs to the controller the worker is connected to; speed history is what other controllers would want to share.
- Decision for now (Decided): do not build any of this. The 10-device demo uses one controller. The record format keeps the option open.

### Integration plan (done by the teammate in `a567e86`; kept here for the reasoning)

Status 2026-10-26: steps 1 to 4 below are implemented in `app/jobs.py` and `app/websocket.py`. The shadow-mode idea in the last paragraph was not used.

1. When a job is submitted, create its records and put its tasks in a waiting list.
2. Dispatch pull-style: a task goes to a worker with a free slot; claim (mark running) first, then send, and undo if the send fails.
3. On a result, accept it by attempt and free the slot; keep stale answers for comparison.
4. On disconnect or timeout, requeue exactly the affected attempts.

A possible safe first step is a "shadow mode": the records observe what the controller already does (job submitted, task sent, result received, worker connected or lost) without changing dispatch, so the records can be checked against real traffic before they take over. This was tried briefly, then reverted at the owner's request because the discussion was not finished. Note that the current up-front dispatch can hand one worker more tasks than its capacity, so worker slots cannot be mirrored in shadow mode.

Checks to run after each step: `pytest tests/`, `python scripts/test_all_workloads.py` with at least one worker tab, and a real test with two devices.

Still to build after the wiring: the digest function and per-workload result validation, per-worker per-workload speed tracking, the speed-aware picking rule, and the timeout checker.

### Review of the controller integration (2026-10-26)

What the teammate's commits `a567e86` and `d2cb275` built: `submit_job` creates a `JobPCB` and calls `dispatch_pending()`, which hands out only as many tasks as each worker has free slots and runs again after every result and every worker failure. `send_task` includes the attempt number and `worker.js` returns it with the result. A disconnect or heartbeat timeout calls `handle_worker_failure`, which requeues exactly the lost attempts. The random and round-robin schedulers respect free slots. Logging is configurable (`app/logging_config.py`). `tests/test_execution_pcb.py` has two tests.

**Fixed on 2026-10-26** (uncommitted when this was written):

- **Reload race** (see race condition 4 above), plus two things the fix needed: a worker that registers again has the tasks of its old session requeued (`attach_worker_pcb`), and `dispatch_pending()` runs after a worker registers, because nothing used to hand out waiting tasks when a worker joined or came back (a job with a single reloaded worker would have stayed idle).
- **Failed jobs looked like hung jobs.** `GET /jobs/{id}/result` returned "Job is still processing." for any status other than done. It now returns `{"message": "Job failed.", "status": "failed", "failed_tasks": [...]}` (up to 10 tasks with retries and last error). `scripts/submit_job.py`, `scripts/test_all_workloads.py` and `app/static/js/jobs.js` only look for the old messages, so on a failed job they keep polling until their own timeout and do not show the new message.
- **Small cleanups:** removed a dead `TypeError` fallback in `dispatch_pending` that re-sent a task without the attempt number (it could also hide a real `TypeError` and send a task twice); removed the duplicated `_task_id` and execution-time wrapping in `app/websocket.py` (`handle_task_result` does it); default log level is now INFO instead of DEBUG (heartbeat and ping notes are DEBUG, so they no longer flood the log); `GET /jobs/{id}` now returns the job's workload, status and progress (or "Job not found."); removed two unused imports in `app/monitoring.py`.
- **New tests:** `tests/test_reconnect_and_failed_job.py` and `tests/test_dispatch_edge_cases.py` cover a late socket close, re-registering, first registration, failed-job replies, a late answer from a replaced attempt, an answer with no attempt number, an answer for an unknown job, failed sends (retried until the job fails, and a send that works on the second try), the same worker loss reported twice, and the job status reply. A test fake in `tests/test_new_workloads.py` now accepts the `attempt` argument like the real `send_task`.

**Still open:**

- **Worker capacity equals the core count** (`WorkerPCB(capacity=cores)`, with an odd fallback `getattr(worker, "cores", len(job_pcb.tasks))`). Each 8-core device got 8 slots, so a slow device could hold 8 tasks while a fast one idled at the end of a job. **Resolved 2026-10-26** by the adaptive capacity policy (owner's choice: adaptive, 1 up to cores); the fallback to the task count was removed from the dispatch path.
- **No timeout checker.** A worker that stays connected but is stuck held its tasks forever. **Resolved 2026-10-26** by `TimeoutMonitor` (adaptive deadlines; see "Adaptive scheduler").
- **The submit freeze is unchanged.** `submit_job` runs the splitter to completion first (`tasks = get_splitter(...).split(job)`), and only then calls `dispatch_pending`, which sends at most the free slots' worth of tasks before replying. So a huge job still blocks the server while the list is built. Sending only a few tasks first just makes the reply smaller, not the splitting faster. **Decision 2026-10-26 (project owner): splitting is not a real overhead for our use cases, so no lazy splitting, no background splitting thread and no immediate-reply redesign are planned** (see the measurements and decision under section 10).
- **Test gaps:** no test yet for a heartbeat timeout through the monitor loop, or for the real WebSocket endpoint (an attempt to drive it with the test client hung).
- **The live test is not done:** start the server, open worker tabs on this PC and on a second device, submit a job with enough tasks, close the second device's tab part way, and check the job still finishes with the right result and that the lost tasks show a retry; then reload a tab, and repeat with a single worker.

### Adaptive scheduler (built 2026-10-26)

Requested by the owner: adaptive like BOINC, modular, several algorithms to try, use PCB state to adapt (for example reallocate by time), project notes written. Decisions made with the owner: choose the algorithm at startup and switch it live; adaptive per-worker capacity from 1 up to the core count; scope = core plus simulator (speculative duplicate tasks left for a later phase because they need the PCB to allow more than one running attempt per task).

**Layout** (`app/services/scheduler/`): `base.py` (interface and helpers), `stats.py` (speed and reliability tracker), `cost.py` (work per task), `capacity.py` (slots per worker), `adaptive.py` (shared machinery), `fastest_first.py`, `boinc.py`, `ucb.py`, `random.py` and `round_robin.py` (baselines), `reallocation.py` (timeouts), `simulator.py`, `__init__.py` (registry). Also `app/scheduler_routes.py` and `scripts/simulate_schedulers.py`.

**Interface kept from the teammate's integration:** `schedule(tasks, workers, worker_pcbs, costs=None, now=None) -> [(TaskPCB, worker)]`. To add an algorithm: subclass `Scheduler` (or `AdaptiveScheduler` and override `pick`, `order` or `before`) and `register()` it in `__init__.py`.

**Using it**
- Start-up default: environment variable `GRID_SCHEDULER` (default `random`, so behavior is unchanged until you choose).
- Live: `GET /scheduler` (active and available), `PUT /scheduler` with `{"name": "boinc"}`, `GET /scheduler/stats` (what has been measured per worker and workload). No authentication, like the rest of the API.
- `python scripts/simulate_schedulers.py [--scenario NAME] [--seeds N] [--no-timeouts]`.

**What it learns (`stats.py`).** Modelled on BOINC's per-host, per-application runtime estimate (mean and variance of seconds per unit of work). For each (worker, workload): running mean and variance of seconds per unit, fed by the `execution_time_ms` each result already carries. Estimate fallback: the worker's own history once it has 3 samples (BOINC uses 10; we have few devices and short jobs), else the workload average scaled by how fast that worker has been on other workloads, else the plain workload average, else unknown. Reliability per worker comes from timeouts and losses (decayed). After 3 timeouts in a row a worker is quarantined from the adaptive algorithms for 30 s, doubling on each repeat offence up to 10 min, reset by a good result or a reconnect. Task size ("cost") comes from `cost.py`: compression = chunk bytes, regex = characters scanned, Mandelbrot = tile pixels times iterations, SAT = 1 (its size cannot be known up front). N-Queens uses a curve fitted to measured node counts, `exp(0.341 r + 0.0542 r^2)` for `r` rows left to place (about 490 nodes at r = 8, 5 million at r = 14, within about 2x at r = 15); without it every N-Queens task looked the same size and the scheduler could not tell a tiny task from a huge one.

**Algorithms**
- `random`, `round_robin`: the baselines. Round-robin now truly rotates one task per worker (before, it favoured the first worker's slots). They ignore speed and quarantine.
- `fastest_first`: each task goes to the worker with the earliest expected finish (its queue plus this task).
- `boinc`: the same, plus BOINC's ideas: biggest tasks first so they land on fast workers (job size matching); retried tasks go first and only to reliable workers (accelerated retry); a worker nobody has measured gets the smallest task first.
- `ucb`: fastest-first with an optimism bonus for lightly sampled workers, so a worker that recovered gets noticed.
- The three adaptive ones also **hold a task back** when a busy worker would finish it clearly sooner than the best free worker (at least 30% sooner and at least 1 s sooner), so a slow device does not take the last tasks of a job. The 1 s floor exists because of a bug the simulator exposed: without it the rule made the adaptive algorithms 19% slower on network-bound jobs.

**Adaptive capacity (`capacity.py`).** `slots_for` (used by the simulator) lets a worker hold enough tasks to cover about 2 s of its measured task time, between 1 and its cores; 2 until it has been measured. The live controller uses `slots_for_pool`: a tab reports its compute-thread count as `cores`, and each thread gets between 1 and `MAX_PER_THREAD` (64) tasks to cover 2 s of its measured task time; 1 per thread until the worker has been measured, so a new tab does not grab a small job. Applied in `dispatch_pending` before each scheduling pass.

**Adaptive reallocation (`reallocation.py`).** A background `TimeoutMonitor` (started in `lifespan`) checks every second. Each running task gets a deadline of `max(10 s, (mean + 3 std) * 2)` from its worker's measured time (60 s if unmeasured), multiplied by the number of tasks the worker holds (a queued task also waits for the ones ahead). On expiry the task is requeued with its attempt number, the worker's slot is freed at once, the worker is marked as having timed out, and the task is dispatched again. A late answer from the slow worker is then a harmless stale result. PCB signals used: task state, attempt, retries and `assigned_at`; worker running set, capacity and online state.

**What the simulator found.** `simulator.py` runs the real scheduler, PCB, tracker, capacity and timeout code against a virtual clock. Worker speeds are assumptions (some taken from our measurements), so this shows behavior and not real speed. Results are averages over 5 to 8 seeds.
- **The algorithm often does not matter.** With small per-worker queues each finished task frees exactly one slot, so there is only one possible recipient and every algorithm makes the same choice. Identical workers, and network-bound jobs (tiny tasks against a roughly 100 ms round trip, like our compression benchmark), gave the same finish time for all five. Pull-style dispatch with adaptive capacity is already self-balancing; cutting overhead helps such jobs, not scheduling.
- **Heterogeneous compute-heavy tasks:** adaptive 79.3 s against 80.6 s (random) and 80.9 s (round-robin) on 3 devices 5x, 2x and 1x as fast; efficiency 0.95 against 0.93. A small gain, almost all from the hold-back rule near the end of the job.
- **Known, uneven task sizes** (like compression chunks, regex batches, Mandelbrot tiles): `boinc` clearly wins: 23.7 s at efficiency 0.97 with a tight spread, against 30.6 s (round-robin), 32.6 (ucb), 34.6 (random) and 34.8 (fastest_first) at 0.67 to 0.77. Size matching makes the difference.
- **Unknown, heavy-tailed task sizes** (N-Queens, SAT): no algorithm is reliably better. Finish time is decided by which worker gets the one huge task near the end (24 s to 41 s for the same algorithm across seeds). Speculative re-execution of stragglers would address this.
- **Faults:** a worker that disconnects is handled equally by all five (that is the requeue code, not the scheduler). A worker that stays connected but hangs, or a tab throttled to 8x slower: the baselines **fail** (0 of 6 runs finish, because they keep sending it work, every task sent to it times out and tasks run out of retries) while the adaptive ones finish 6 of 6 (about 204 s and 269 s) by quarantining it. Without the timeout monitor nobody finishes the hung-worker scenario.
- **Waste:** in the throttled-tab scenario the slowed worker keeps computing tasks that were already taken back (about 200 s of compute per run discarded). The worker protocol has no way to cancel a task; adding one would remove this.

**Known limitations and open items**
- The default stays `random`. Pick the default only after the live comparison on real tabs.
- The tracker's workload key is the job's workload name, so lz4 and zstd tasks of one compression job share a speed estimate. A key that includes the variant would separate them.
- All constants (EWMA weight, 3-sample threshold, 2 s queue target, deadline factors, hold-back ratio and 1 s floor, quarantine times) are single named constants, to be tuned after the live runs.
- Hold-back and the timeout deadline use rough queue-position estimates (a busy worker is assumed to have all its tasks ahead of the new one).
- Not built: a cancel message to workers (a copy that loses a race keeps computing until it finishes), and adaptive replication (verifying trusted workers less).
- Tests: `tests/test_scheduler_stats.py`, `test_scheduler_algorithms.py`, `test_scheduler_integration.py`, `test_scheduler_simulation.py`.
- `scripts/submit_job.py`, `compress_file.py` and `test_all_workloads.py` failed to start (`ModuleNotFoundError: No module named 'app'`) after the logging change, because Python puts `scripts/` on the path, not the project root. Fixed on 2026-10-26 by adding the project root to `sys.path` at the top of each.
- The dispatch code no longer falls back to "one slot per task" for a worker without a core count (it now falls back to 1); the adaptive capacity policy sets the real value anyway.

**Fixes found by running it live (2026-10-26)**
- A task taken back from a worker went straight back to the same worker when that was the only one with a free slot (one task timed out three times in a row, about 54 s wasted). `TaskPCB.last_worker` records where it was taken from, and the adaptive algorithms now keep it waiting for another worker (`AdaptiveScheduler.should_avoid`) unless no other usable worker exists.
- A timeout taught the scheduler nothing, so a worker that had slowed down kept being believed fast and got work it could not finish in time. A timeout now also records a speed sample equal to the time waited (`SpeedTracker.record_lower_bound`; the true time can only be longer).
- `POST /disconnect/{uuid}` used to be undone at once, because the tab reconnects by itself after 3 s. It now tells the tab not to (`reconnect=false` is the default; `?reconnect=true` imitates a network blip). The tab shows "Disconnected by controller (reload to reconnect)".

### Work stealing (built 2026-10-26)

Requested by the owner for unevenly splitting workloads (N-Queens, SAT): when workers free up quickly and others are still on long tasks, idle workers should help. Built as speculative duplicates, the MapReduce "backup task" idea.

- **Control block:** a RUNNING task can have copies on other workers (`TaskPCB.backups`: attempt to (worker, start time); `issued` is the highest attempt number handed out). The first answer from the original or any copy is accepted; every other answer is a stale result, so the digest comparison still works. If the original's worker is lost or times out and a copy exists, the copy takes over with no retry counted; if a copy is lost the original keeps running.
- **Decision (`AdaptiveScheduler.speculate`):** only when a job has nothing waiting, and only a fully idle worker steals, from another worker, at most one copy per compute thread. It steals when it expects to finish in under 70% of the time the holder still needs and to save at least 0.5 s. A task already overdue is assumed to need as long again.
- **Controller:** `jobs.speculate_pending` sends the copies and frees the other holder's slot when one copy wins. It runs once a second from the timeout monitor. Log lines: `Work stealing: task ... also sent to ...` and `... answered first, copy on ... dropped`.
- **Scope:** on for `fastest_first`, `boinc` and `ucb`; off for `random` and `round_robin` so they stay plain baselines. Turn it on or off while running with `PUT /scheduler {"stealing": false}`.
- **Tests:** `tests/test_work_stealing.py`.
- **Not built:** cancelling the losing copy (the worker keeps computing it), and splitting a task that is already running.

### Live results (2026-10-26, laptop Firefox and Chrome tabs; the phone for some runs)

**Final measured results, with raw data and statistics, are in [results/scheduler_results.md](results/scheduler_results.md)** (headline: on Mandelbrot with a laptop tab and a phone, the adaptive algorithms take about 13 s against 28 s for `random`, 2.2x). The notes below are the running log from the same day, before the cost-model and avoid-rule fixes.

Finding: **work stealing works as designed but its benefit is small and not yet proven.**
- Mechanism: copies are sent, the first answer wins, the loser's slot is freed, results stay correct (N-Queens answers matched the known counts for n = 12 to 17).
- With two equal-speed workers all five algorithms tie (about 8 s on N-Queens n=16, compute-bound).
- Mandelbrot whole-set view (192 tasks, about 70% finish in under 1 ms, about 25% take about 1 s) with Chrome made about 3x slower by lowering its CPU priority and loading the CPU: random 30 to 31 s, round_robin 33 s, fastest_first without stealing 34 s, fastest_first with stealing 31 s (two rounds each). Stealing gave about 8%. The adaptive algorithms did **not** beat random here, because the cost model treats every Mandelbrot tile as equal cost; it cannot tell the heavy tiles from the empty ones.
- Slowing a worker in the middle of a job (N-Queens n=17, 17 tasks): about 120 s with or without stealing, 115 s after the fixes above. The queue was never empty, so no worker was idle to steal; the timeout path did the work.
- A caution for later runs: both browsers on one laptop share its CPU, so their speeds are not independent, and run-to-run noise is 1 to 2 s. A device that really differs (the phone) is needed for a clean comparison.

### Performance work (2026-10-26)

A profile and a few live runs showed that most of the time was not in the scheduling algorithms.

| Change | Where |
|---|---|
| **A tab runs a pool of compute threads** (`min(cores - 1, 8)`; `?threads=N` overrides). Before, a tab ran one WASM thread whatever its core count. The tab reports the pool size as its `cores`. | `worker.js` |
| **Capacity counts per thread** (`slots_for_pool`). Before, a 7 s task got one slot per tab, so one task ran at a time. | `capacity.py`, `jobs.py` |
| **Task errors are reported** (`task_error`): the attempt is requeued at once and counts as a retry, so a task that always fails ends FAILED instead of waiting for a timeout. | `worker.js`, `websocket.py`, `jobs.handle_task_error` |
| **Batching:** the controller sends all tasks claimed for a worker in one `tasks` message; tabs send results in `task_results` batches, flushed every 10 ms. The single-task messages still work. | `jobs.py`, `websocket.py`, `worker.js` |
| **The controller no longer slows down on large jobs.** `dispatch_pending` ran after every result and recomputed every waiting task's cost (19 million `cost_of` calls for 19,688 tasks). Costs are now computed once per task; `JobPCB` keeps state counts and a sorted waiting list up to date instead of rescanning; the scheduler sees a window of 256 to 1,000 waiting tasks instead of all of them. | `jobs.py`, `pcb.py` |
| **Work stealing is capped** at one copy per compute thread (it once made 547 copies in a few jobs). | `adaptive.py` |
| **`GRID_LOG_LEVEL`** overrides the log level (default still `DEBUG`). Logging cost is small: 8.3 s against 7.8 s on the 19,688-task job. | `logging_config.py` |

Measured on the same two browsers (laptop):

| Job | Start of session | After |
|---|---|---|
| N-Queens n=16, `split_depth` 4 (19,688 tiny tasks) | 182 s | 2.5 s |
| Mandelbrot whole set (192 tasks) | 23.3 s | 3.3 to 4.3 s |
| N-Queens n=17, `split_depth` 1 (17 big tasks) | 55 to 60 s | 8 to 12 s |
| N-Queens n=14, `split_depth` 3 (1,364 tasks) | 2.0 s | 0.5 to 1.4 s |

What was learned: a deeper pipeline mattered more than fewer messages. With 4 tasks per thread, batching made the tiny-task job slower (5.0 s to 8.5 s), because a thread finishes its 4 tasks in microseconds and then waits for the next batch; with up to 64 per thread it took 2.4 s. The cost is that a worker with a stale speed estimate can hoard tasks; the N-Queens cost model and the per-thread start of 1 limit that.

Open items: the Mandelbrot cost estimate (sample a few pixels of each tile on the controller); `MAX_PER_THREAD`, the 10 ms result flush, the 256 to 1,000 window and the stealing thresholds are untuned constants; a task that exhausts its retries on worker losses still fails the whole job (a flaky phone could do it); no grace period before requeueing when a socket blips; timeouts count from assignment, not from when the task starts in the tab. Tests: `tests/test_batching.py`, `tests/test_work_stealing.py`, plus additions to `test_reconnect_and_failed_job.py` and `test_scheduler_stats.py`.

### Candidate scheduler ideas (Proposed, none confirmed new)

1. Schedule by expected finish time including the chance the worker disappears (speed and reliability together).
2. Use browser signals (tab hidden, throttled) as scheduling inputs.
3. Adaptive task size per worker.
4. Redundancy that does two jobs: speculative duplicates of the slowest tasks cut the tail wait and also act as correctness checks. (Related: BOINC adaptive replication, MapReduce backup tasks.) Duplicates are built (see "Work stealing"); the correctness-check use of the stale answers is not yet used by anything.
5. Probe new workers with small tasks to learn their profile quickly.

Preferred pair for the demo: ideas 1 and 2, built after the baseline speed-aware scheduler works and only claimed if they beat it.

## 6. Known security and reliability gaps (not yet built)

- Worker results are not verified. A faulty or malicious worker can return wrong answers.
- The worker connects over plain `ws://`, so task data and results are unencrypted.
- No authentication on worker registration or job submission.
- A worker's uuid is generated in the browser, stored in `localStorage`, and trusted as sent. Anyone can claim any uuid. Over plain HTTP on a LAN, `crypto.randomUUID()` is unavailable (it needs a secure context), so `worker.js` falls back to a 64-bit `Math.random()` id; the remote test device used this (`e60e-a0e8-02c8-595f`) while the local one got a proper uuid. A fix would use `crypto.getRandomValues`, which works over HTTP. Later, a secret token issued at first registration would give real identity. Device specs (cores, memory) make a poor identity: they are not unique across identical lab PCs, can be faked, and some browsers report memory as 0.
- On worker disconnect the controller only marks it Offline. It does not reassign unfinished tasks.
- No task-level or job-level timeouts.
- Heartbeats run on a main-thread timer in the worker page; hidden tabs are throttled by browsers and might look dead. Not yet tested.

## 7. Novelty and prior work (literature check, 2026-10-24)

The searches were shallow and only summaries were read. Nothing here has been confirmed with the papers in full.

- **Claim to test:** workload-specific measured performance schedules heterogeneous browser/WASM workers better than a single hardware score. This can fail, and a negative result is still reportable.
- **BOINC already keeps a per-host, per-application runtime estimate** (mean and variance of runtime per unit of work, with a fallback to the app-wide average and then to peak speed when there are few samples). So "learn each worker's speed per workload" is not new in general; see [BOINC platform paper](https://arxiv.org/pdf/1903.01699).
- **Wasimoff** (Semjonov et al., PerCom Workshops 2024) is the closest browser/WASM system: volunteers join by opening a URL, tasks run as WASM in browser workers. Its public source ([github.com/wasimoff/wasimoff](https://github.com/wasimoff/wasimoff), `broker/scheduler/`) has `AnyFree`, `RoundRobin` and `SimpleMatch` strategies that use no measured speed or per-workload data, a buffered task queue, dispatch only to providers with free capacity, and up to 10 retries with exponential backoff (no retry on application errors). Read through a summarizing tool, so not verified in full; the paper itself could not be read (the ACM and repository pages returned 403 errors).
- **Other related work:** [Pando](https://arxiv.org/abs/1803.08426v1) and [JSDoop](https://arxiv.org/pdf/1910.07402) (browser volunteer computing), a [2022 volunteer-computing scheduler using observed performance](https://link.springer.com/article/10.1007/s41870-022-01090-w), [Gavel](https://www.usenix.org/system/files/osdi20-narayanan_deepak.pdf) (heterogeneity-aware cluster scheduling), [Speed-Oblivious Online Scheduling](https://proceedings.mlr.press/v202/lindermayr23a/lindermayr23a.pdf) (ICML 2023), [Learning to Schedule Online Tasks with Bandit Feedback](https://arxiv.org/abs/2402.16463), and a bandit method for learning worker speeds in [distributed learning (ISIT 2022)](https://www.imperial.ac.uk/media/imperial-college/research-centres-and-groups/ipc-lab/EBWG_ISIT22.pdf).
- **What may still be new (narrow, to be confirmed):** adapting a BOINC-style per-host, per-workload estimator to short-lived browser WASM workers, together with failure recovery, evaluated against baselines. A queue, retries and capacity-based dispatch are standard and are not contributions. Suggested next literature step: obtain the Wasimoff PerCom paper through university access, then check online-learning and BOINC estimation papers.
- **Experiment design (Proposed):** several workloads that stress different things (SAT, compression, N-Queens), heterogeneous devices, baselines of random, round-robin, a hardware score, a single learned speed per worker and a workload-specific learned profile, repeated runs with the spread reported.

## 8. Scaling notes (for later; not needed for the 10-device demo)

- TCP connections themselves scale well; a single process can hold far more than 200. The expected limits are in this code, not in TCP.
- `notify_dashboards()` in `app/websocket.py` is called on every pong and rebuilds the full worker list, so cost grows with the square of the worker count.
- CPU work (base64, JSON, task building) shares the event loop with heartbeats and could delay them.
- For data-heavy workloads such as compression, all bytes flow through the controller.
- Multiple servers would improve resilience and capacity but need shared task and worker state (today it is process memory in `app/registry.py`). A "server" is a role, not special hardware; a second server can be an ordinary lab PC.
- For decentralized designs: attempt numbers (already in the PCB), leases instead of failure detection, idempotent operations, and one owner per record.

## 9. Reference measurements (2026-10-24)

Two devices on a phone hotspot: a local PC (127.0.0.1) and a remote device (10.98.248.184), 32 MB synthetic data, 256 KiB chunks, 123 tasks per variant, median of 3.

| Variant | Setup | Wall time | Compute speed (bytes / worker time) |
|---|---|---|---|
| lz4 | Remote only | 7.06 s | 11.9 MB/s |
| lz4 | Local only | 6.29 s | 59.2 MB/s |
| lz4 | Both | 5.85 s | 15.0 MB/s |
| zstd-fastest | Remote only | 7.97 s | 8.5 MB/s |
| zstd-fastest | Local only | 6.18 s | 26.8 MB/s |
| zstd-fastest | Both | 5.80 s | 11.4 MB/s |

Observations:

- Compression results were identical on every setup (lz4 ratio 0.566, zstd-fastest 0.5216), with no round-trip failures.
- The local PC was about 5x faster than the remote on lz4 and about 3x on zstd, although both devices reported 8 cores. This is one measurement on two devices, so it is a hint that relative speed depends on the workload and that specs predict speed poorly, not a result.
- Wall time was dominated by the controller. Generating and splitting 32 MB took about 2.3 s of roughly 6 s, so splitting across both devices gained only about 7%. Any evaluation needs to separate worker time from controller time.
- The compression kernel was checked against reference decoders (Python `lz4` and `zstandard`): outputs from `lz4_flex` and `ruzstd` decoded back to the original bytes.
- Compression uses `lz4_flex` (LZ4 block format, size prepended) and `ruzstd` at its `Fastest` level only, because both are pure Rust and compile to WASM cleanly. Each chunk is compressed independently.

## 10. Backlog and notes for later

Not scheduled. Nothing here has been built.

### N-Queens kernel optimization (noted 2026-10-25)

`runtime/src/kernels/nqueens.rs` already uses the standard bitmask search, so remaining gains are constant factors. None of these were measured.

- Mirror symmetry: search only the left half of the first queen's columns and double the count (the middle column for odd N needs separate handling). Roughly 2x less work. The splitter would apply it when making prefixes. Full rotation and reflection symmetry could give up to about 8x but is fiddly.
- Count the last row directly with a popcount instead of recursing into it.
- The `nodes` counter is useful for showing how uneven tasks are; keep it or compute it only in a separate mode.
- Smaller tweaks (32-bit masks for small N, a loop instead of recursion) should give little.
- Cautions: N-Queens is a measuring tool for the scheduler, not the contribution; a faster kernel only means a larger N is needed for the same workload. Keep the current version as the baseline for experiments. Test against known counts (N=12 is 14,200; N=14 is 365,596) and a simple reference implementation, because symmetry changes are easy to get subtly wrong. Measure before and after.

### Regex findings (checked 2026-10-25)

- 15 small-input cases ran correctly through the real pipeline (one text, empty text, empty pattern, backreference, non-ASCII, synthetic texts with count 1 or length 0). No hangs or errors were reproduced; the exact failure the project owner saw is still unknown (input, expected result, got result and device were not given).
- Scan mode counts zero-length matches differently from Python and JavaScript: `a*` on `baaac` gives 3 in the grid and 4 in Python. The Rust `fancy-regex` engine skips an empty match right after a non-empty one. Options: document it, or change the kernel to match Python.
- If a WASM kernel ever throws, `app/static/js/worker.js` only logs the error to the browser console and never reports it to the controller, so the job would hang with no error message. Not triggered by valid input so far. Worth fixing as part of the reliability work.

### Splitting overhead: decision (2026-10-26)

The splitter is fast for realistic jobs. Measured: N-Queens n=20 `split_depth=3` makes 4,964 tasks in 0.076 s (the project owner's own run, from the new DEBUG log lines); depth 4 makes 61,760 tasks in 0.09 s; depth 5 makes 654,548 tasks in 1.2 s; only multi-million-task jobs are slow (n=16 depth 7 is about 4,000,000 tasks in 27 s). The compression workload is the one exception: its cost is generating and encoding the data, not the task count (about 2.3 s for 32 MB).

**Decided:** do not build lazy splitting (the scheduler pulling tasks from a generator), a background splitting thread, or an immediate-reply submit. They would only matter for oversized jobs, which are settings mistakes, or for large compression uploads. Lazy splitting stays on the list as an optional optimization (it would also cut the controller overhead seen in the compression benchmark and cut memory, since every task payload is kept until the job ends) to revisit only if big-file compression becomes part of the demo.

**Not decided:** a cap on the number of tasks a job may create, as a small safety net against a bad `split_depth` freezing the server (proposed limit 100,000; one check, no effect on normal jobs). TCP and threads were discussed: a thread keeps the server responsive but does not reduce memory or time, and the cap is what prevents an out-of-memory crash.

New DEBUG log lines in `submit_job` record when the splitter starts and how long it took ("splitter finished: N tasks in X s").

### Server freezes when a large job is submitted (found 2026-10-25, not fixed; see the decision above and the review in section 5)

A teammate submitted a request through the interactive API page (`/docs`, Swagger) and the server did not respond for a long time. Reproduced:

- `POST /jobs` splits the job inside the async handler (`submit_job` in `app/jobs.py`), on the same thread that serves every other request. While it runs, the whole server is frozen: `GET /worker` timed out, the process sat at 100% CPU with memory growing past 1 GB, and workers would miss heartbeats and drop offline.
- Worst case is N-Queens. The API allows `n` up to 24 and `split_depth` up to `n` with no cap on the task count. `nqueens n=20 split_depth=12` got no reply in 90 s. Task counts for the prefix list: n=10 depth 5 gives 3,916; n=12 depth 6 gives 52,856; n=14 depth 6 gives 241,484; n=16 depth 6 gives 838,816 (2.8 s to build); n=16 depth 7 gives 3,998,456 (27 s to build, before building task objects or messages).
- Swagger's default body for `POST /jobs` is a Mandelbrot job with every number 0. It returns a plain `500 Internal Server Error` (the splitter raises `ValueError` for `tile_size: 0`) instead of a clear 422.
- Big jobs echo everything back: a Mandelbrot job with 250,000 tasks returned a 16 MB response, which makes the Swagger page slow.
- The submit request also waits until every task has been sent to its worker, so a large job over a slow link (for example a phone hotspot) is slow to answer even when nothing is wrong.

Fix options (Proposed, none done): (1) cap the number of tasks a job may create, checked before splitting, so a bad request gets a clear 422; (2) run the splitting off the main thread (for example `asyncio.to_thread`) so the server and heartbeats keep working; (3) put sensible examples in the API schema so the `/docs` default is not all zeros, and return a clear error for values like `tile_size: 0`; (4) shorten the reply for large jobs. Suggested first: 1 and 3. Number 2 also supports the reliability aim.

The server must be started from the project root, because `app/main.py` mounts `app/static` and `runtime/pkg`, and `app/routes.py` reads `app/templates`, all as paths relative to the launch folder. From another folder (for example `./docs`) it stops with `ModuleNotFoundError: No module named 'app'`, and with `--app-dir ..` it stops with `Directory 'app/static' does not exist`. `docs/commands.md` already says to run from the root. It is also stale: it says Mandelbrot is the only workload, lists only five packages in `requirements.txt`, and its "force kill" command (`Stop-Process -Name "python"`) stops every Python process on the machine.

### Regex minimum sizes (checked 2026-10-25)

- Smallest job: one pattern and one text, one task. An empty-string pattern and an empty-string text are both valid.
- Minimums: at least 1 pattern; at least 1 text (an empty list is rejected); synthetic `count` at least 1; `min_length` and `max_length` 0 or more with `min_length` not above `max_length`; `texts_per_task` at least 1; `backtrack_limit` at least 1. Giving neither or both of `texts` and `synthetic_texts` is rejected. All rejections are clear 422 errors.
- A single regex task takes a fraction of a millisecond, so a tiny job costs more to send than to run.

## 11. Practical notes

- `runtime/pkg/` is intentionally committed. The app serves it at `/runtime` and the Dockerfile copies it without building. Rebuild it with the commands in `commands.md` (`cargo build --release --target wasm32-unknown-unknown`, then `wasm-bindgen`), not `wasm-pack`. `runtime/target/` is a build artifact and is ignored.
- To test across devices, start the controller with `--host 0.0.0.0` and open `http://<controller-ip>:8000/worker` (plain `http://`) on the other device. Windows Firewall may need an inbound rule for port 8000.
- Tests: `pytest tests/` (Python), `cargo test` in `runtime/` (Rust), and `python scripts/test_all_workloads.py` for a live check that needs a server and at least one worker tab.
- Preference: do not add a `Co-Authored-By` line to commit messages.
