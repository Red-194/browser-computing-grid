# Project context and direction

Working notes so the project's aim, current state and open design questions don't have to be re-explained. Items marked **Decided** come from the project owner. Items marked **Proposed** are suggestions that still need a decision. Items marked **Finding** are things that were checked or measured.

Last updated: 2026-10-24.

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
- **PCBs connected to the controller** (teammate's commit `a567e86`, "failure recovery somehow works"): pull-style dispatch by free slots, attempt numbers sent to workers and returned, requeue on disconnect and heartbeat timeout. Reviewed and corrected on 2026-10-26 (see "Review of the controller integration" in section 5). **Not yet verified live** with real worker tabs.

Next (Decided): live test of recovery from a killed worker (two real worker tabs, close one mid-job), then the timeout checker, then a speed-aware scheduler.

## 4. What the current scheduler placeholder cannot do

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

- **Worker capacity equals the core count** (`WorkerPCB(capacity=cores)`, with an odd fallback `getattr(worker, "cores", len(job_pcb.tasks))`). Each 8-core device gets 8 slots, not the default of 2 chosen for the PCB module, so a slow device can hold 8 tasks while a fast one idles at the end of a job. The project owner has not decided this.
- **No timeout checker.** A worker that stays connected but is stuck holds its tasks forever. `TaskPCB.is_timed_out()` exists but nothing calls it. Recovery only happens on disconnect or heartbeat timeout.
- **The submit freeze is unchanged.** `submit_job` runs the splitter to completion first (`tasks = get_splitter(...).split(job)`), and only then calls `dispatch_pending`, which sends at most the free slots' worth of tasks before replying. So a huge job still blocks the server while the list is built. Sending only a few tasks first just makes the reply smaller, not the splitting faster. **Decision 2026-10-26 (project owner): splitting is not a real overhead for our use cases, so no lazy splitting, no background splitting thread and no immediate-reply redesign are planned** (see the measurements and decision under section 10).
- **Test gaps:** no test yet for a heartbeat timeout through the monitor loop, or for the real WebSocket endpoint (an attempt to drive it with the test client hung).
- **The live test is not done:** start the server, open worker tabs on this PC and on a second device, submit a job with enough tasks, close the second device's tab part way, and check the job still finishes with the right result and that the lost tasks show a retry; then reload a tab, and repeat with a single worker.

### Candidate scheduler ideas (Proposed, none confirmed new)

1. Schedule by expected finish time including the chance the worker disappears (speed and reliability together).
2. Use browser signals (tab hidden, throttled) as scheduling inputs.
3. Adaptive task size per worker.
4. Redundancy that does two jobs: speculative duplicates of the slowest tasks cut the tail wait and also act as correctness checks. (Related: BOINC adaptive replication, MapReduce backup tasks.)
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
