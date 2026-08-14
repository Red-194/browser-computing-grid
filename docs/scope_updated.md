# Adaptive Browser Compute Grid --- Final Year Project Scope & Plan

## 1. One-Line Pitch

A zero-install, browser-native distributed computing grid with
workload-aware adaptive scheduling and crash-fault recovery, executing
CPU-oriented WebAssembly workloads across heterogeneous devices.

------------------------------------------------------------------------

# 2. Project Overview

The project is a browser-based distributed computing framework that
allows ordinary computers to participate in distributed computation
through a web browser.

A central controller manages a collection of browser workers. Each
worker executes computational microtasks through WebAssembly and reports
execution results and runtime telemetry back to the controller.

The system is designed specifically for heterogeneous and relatively
weak machines, including university laboratory computers with
approximately 4--8 GB of RAM.

The primary research focus is the scheduling problem created by this
environment.

Rather than assuming that a worker has a fixed, universally
representative capability, the system investigates whether a worker's
actual performance varies across different computational workloads and
whether this observed workload-specific performance can be used to
improve scheduling.

The project therefore has two outcomes:

1.  A functioning browser-based distributed computing grid.
2.  An adaptive workload-aware scheduling mechanism evaluated against
    conventional scheduling strategies.

The computational workloads themselves are evaluation mechanisms rather
than the primary research contribution.

------------------------------------------------------------------------

# 3. Problem Statement

Traditional distributed computing systems generally assume that
participating machines can be configured as dedicated compute nodes or
that users can install native client software.

This introduces practical barriers such as:

-   Client installation
-   Administrative configuration
-   Platform-specific binaries
-   Hardware heterogeneity
-   Resource management
-   Worker maintenance

Browser-based computing removes much of this deployment overhead because
a worker can join the system simply by opening a webpage.

However, browser workers introduce a different set of problems.

Workers may differ substantially in:

-   CPU performance
-   Number of CPU cores
-   Available memory
-   WebAssembly runtime performance
-   Current system load
-   Network latency
-   Browser state
-   Availability
-   Execution stability

Furthermore, the relative performance of two workers may change
depending on the workload being executed.

For example, one worker may perform well on a branch-heavy SAT workload
while another may perform better on byte-oriented compression.

Therefore, a scheduler that assigns work using only static hardware
information may not accurately represent the actual computational
capability of each browser worker.

The project investigates whether continuously observed workload-specific
performance can provide a better basis for task scheduling.

------------------------------------------------------------------------

# 4. Proposed Solution

The proposed system aggregates browser clients into a distributed
computing grid.

A central controller:

-   Registers workers
-   Discovers capabilities
-   Receives jobs
-   Decomposes jobs into microtasks
-   Assigns tasks
-   Monitors execution
-   Collects results
-   Tracks worker performance
-   Detects failures
-   Reassigns unfinished work

Browser workers:

-   Connect to the controller
-   Report hardware/runtime information
-   Receive WebAssembly tasks
-   Execute tasks
-   Report progress and results
-   Send heartbeat and telemetry information
-   Reconnect after temporary disconnection

The scheduler compares three increasingly sophisticated approaches:

1.  Round Robin
2.  Static Capability-Aware Scheduling
3.  Adaptive Workload-Aware Scheduling

------------------------------------------------------------------------

# 5. System Architecture

``` text
                         ┌─────────────────────────────┐
                         │       Central Controller    │
                         │                             │
                         │  Worker Registry            │
                         │  Job Manager                │
                         │  Task Queue                 │
                         │  Scheduler                  │
                         │  Performance Model          │
                         │  Failure Detector           │
                         │  Result Aggregator          │
                         └──────────────┬──────────────┘
                                        │
                              WebSocket │
                                        │
             ┌──────────────────────────┼──────────────────────────┐
             │                          │                          │
             ▼                          ▼                          ▼
    ┌────────────────┐        ┌────────────────┐        ┌────────────────┐
    │ Browser Worker │        │ Browser Worker │        │ Browser Worker │
    │                │        │                │        │                │
    │ JS Runtime     │        │ JS Runtime     │        │ JS Runtime     │
    │ Telemetry      │        │ Telemetry      │        │ Telemetry      │
    │ Wasm Runtime   │        │ Wasm Runtime   │        │ Wasm Runtime   │
    └────────────────┘        └────────────────┘        └────────────────┘
             │                          │                          │
             ▼                          ▼                          ▼
        CPU-oriented               CPU-oriented               CPU-oriented
        Wasm workload              Wasm workload              Wasm workload
```

The controller remains the central coordination point.

Peer-to-peer communication is not required.

------------------------------------------------------------------------

# 6. Controller

The controller is responsible for coordinating the distributed system.

## 6.1 Worker Registration and Deregistration

The controller maintains a registry of active workers.

Worker registration information may include:

-   Worker UUID
-   CPU core count
-   Device memory
-   Browser
-   Operating system
-   Current state
-   Network information
-   Runtime capability information

Workers can explicitly disconnect or disappear unexpectedly.

------------------------------------------------------------------------

## 6.2 Worker State Management

Workers can occupy states such as:

-   Idle
-   Busy
-   Offline
-   Throttled
-   Suspended

State transitions are driven by:

-   Registration
-   Task assignment
-   Task completion
-   Heartbeat status
-   Worker disconnection
-   Runtime telemetry

------------------------------------------------------------------------

## 6.3 Heartbeat Monitoring

Workers periodically send heartbeat messages.

The controller uses heartbeats to determine whether a worker remains
responsive.

If a worker fails to respond within the configured timeout:

1.  The worker is marked unavailable.
2.  Any unfinished task assigned to the worker is identified.
3.  The task is returned to the queue.
4.  Another worker can execute the task.

------------------------------------------------------------------------

## 6.4 Latency Measurement

The controller measures communication latency between itself and
workers.

Latency can be used as:

-   Worker health information
-   A scheduling factor
-   A network-cost component for data-bearing workloads

------------------------------------------------------------------------

## 6.5 Capability Discovery

Static worker capabilities include:

-   CPU cores
-   Available/device memory
-   Browser
-   Operating system

These values form the basis of the static capability-aware scheduler.

However, they are not treated as a complete representation of worker
performance.

------------------------------------------------------------------------

## 6.6 Runtime Performance Tracking

The controller records execution information from completed tasks,
including:

-   Task type
-   Worker
-   Execution duration
-   Successful completion
-   Timeout
-   Failure
-   Reassignment
-   Recent performance

This information forms the basis of workload-specific performance
estimates.

------------------------------------------------------------------------

# 7. Scheduler

Three scheduling strategies are included.

The purpose is not simply to provide multiple algorithms, but to
establish increasingly strong baselines and determine whether
workload-aware runtime information provides measurable benefit.

------------------------------------------------------------------------

## 7.1 Round Robin Scheduler

Round Robin distributes tasks sequentially among available workers.

Example:

``` text
Task 1 → Worker A
Task 2 → Worker B
Task 3 → Worker C
Task 4 → Worker A
Task 5 → Worker B
...
```

### Purpose

-   Simple baseline
-   Fair distribution
-   Demonstrates the impact of ignoring worker heterogeneity
-   Provides a reference for makespan and utilization

Round Robin does not use observed worker performance.

------------------------------------------------------------------------

# 8. Static Capability-Aware Scheduler

The second scheduler uses information available before or independently
of workload execution.

Potential factors include:

-   CPU core count
-   Available memory
-   Current latency
-   Worker health
-   Current load

A deterministic capability score can be calculated from these factors.

The scheduler then prefers workers with higher estimated static
capability.

### Purpose

This establishes whether basic hardware-aware scheduling is sufficient.

It also creates the baseline against which the adaptive scheduler is
evaluated.

------------------------------------------------------------------------

# 9. Adaptive Workload-Aware Scheduler

The adaptive scheduler is the proposed research component.

Instead of maintaining only one capability value per worker, the system
maintains performance information associated with both:

-   Worker
-   Workload type

Conceptually:

``` text
Worker A
    SAT       → estimated throughput X
    Zstd      → estimated throughput Y
    Regex     → estimated throughput Z

Worker B
    SAT       → estimated throughput X
    Zstd      → estimated throughput Y
    Regex     → estimated throughput Z
```

The estimates are updated from real task execution.

A worker that performs particularly well on a workload gradually becomes
more attractive for that workload.

A worker whose performance degrades can have its estimated capability
reduced.

------------------------------------------------------------------------

## 9.1 Adaptive Information

The scheduler can use:

-   Historical execution time
-   Recent execution time
-   Successful completion
-   Timeout
-   Failure
-   Reassignment
-   Worker health
-   Current load
-   Workload category

------------------------------------------------------------------------

## 9.2 Online Updating

No offline training dataset is required.

The scheduler updates its estimates as tasks complete.

Candidate lightweight methods include:

-   Exponentially Weighted Moving Average
-   UCB1
-   ε-Greedy
-   Bayesian updating

The final mechanism should be selected according to implementation
complexity and experimental performance.

The project does not require a full reinforcement-learning system.

------------------------------------------------------------------------

## 9.3 Exploration and Exploitation

If a bandit formulation is used, the scheduler can balance:

### Exploration

Occasionally assign work to workers with limited history in order to
improve knowledge of their capability.

### Exploitation

Prefer workers that have demonstrated strong performance for the current
workload.

This allows the system to adapt without requiring an offline model.

------------------------------------------------------------------------

# 10. Workload-Aware Worker Affinity

The central research hypothesis is that worker capability is not
necessarily represented adequately by a single scalar hardware score.

Different workloads stress different aspects of a CPU and runtime.

For example:

``` text
             Worker A       Worker B       Worker C

SAT             High          Medium          Low
Zstd            Medium        High            Medium
Regex           High          Low             Medium
Search          High          Medium          High
```

If these differences are significant, the scheduler can exploit them.

This produces a research question that can be experimentally tested
rather than assumed.

------------------------------------------------------------------------

# 11. Worker Runtime

The worker is a browser-based execution environment.

## Features

-   Worker registration
-   Heartbeat transmission
-   Ping response
-   Task reception
-   Task execution
-   Execution timing
-   Progress reporting
-   Result submission
-   Automatic reconnect
-   Runtime telemetry
-   Browser-state information where available

The worker should not require permanent software installation.

A browser tab can join the grid and leave the grid simply by being
opened or closed.

------------------------------------------------------------------------

# 12. Compute Runtime

Computational tasks execute through WebAssembly.

## Features

-   Wasm module loading
-   Sandboxed execution
-   Input serialization
-   Output serialization
-   Dynamic workload selection
-   Execution timing
-   Optional progress reporting
-   Result validation

Where appropriate, JavaScript may be used as a fallback or reference
implementation.

The computational core should preferably be written in C, C++, or Rust
and compiled to WebAssembly.

------------------------------------------------------------------------

# 13. Workload Philosophy

The project should not spend a large amount of engineering effort
developing computational algorithms.

The workload is an evaluation instrument for the distributed system.

The preferred workloads therefore have:

-   Existing implementations
-   Existing benchmark datasets
-   Straightforward Wasm compilation
-   Low memory requirements
-   Small or manageable task payloads
-   Strong parallelism
-   High computation-to-transfer ratio
-   Little practical GPU advantage
-   Relevance to university computing/research

The total workload should be capable of becoming large while each
individual microtask remains manageable for a 4--8 GB worker.

The desired shape is:

``` text
Large aggregate workload
          │
          ├───────────────┬───────────────┐
          ▼               ▼               ▼
       Task A           Task B           Task C
       Small            Small            Small
          │               │               │
          ▼               ▼               ▼
       Worker A         Worker B         Worker C
```

The grid therefore aggregates many modest machines rather than requiring
one extremely powerful worker.

------------------------------------------------------------------------

# 14. Workload Suite

A small workload suite should be used instead of relying on one
benchmark.

The suite should expose different computational characteristics so that
workload-specific worker affinity can actually be measured.

## 14.1 SAT / SMT Solving

Examples:

-   Z3
-   MiniSat
-   Other Wasm-compatible solver builds

Characteristics:

-   Branch-heavy
-   High execution-time variance
-   Small task descriptions
-   Potentially long CPU execution
-   Strong scheduling value
-   Good fault/requeue behavior

A large collection of independent instances can be distributed
naturally.

------------------------------------------------------------------------

## 14.2 Lossless Compression

Examples:

-   Zstandard
-   LZ4

Characteristics:

-   Byte-oriented processing
-   Memory access
-   Different computational profile from SAT
-   Existing portable implementations
-   Parameter-sweep opportunities

Compression tasks should use chunks large enough for computation to
justify network transfer.

------------------------------------------------------------------------

## 14.3 Regex / Text Processing

Examples:

-   PCRE2
-   Other portable regex engines

Characteristics:

-   Variable-length strings
-   Branch-heavy execution
-   Lightweight memory footprint
-   Small task payloads
-   Different execution profile from SAT and compression

Possible tasks include:

-   Regex matching
-   Pattern scanning
-   Parser validation
-   ReDoS-oriented testing

------------------------------------------------------------------------

## 14.4 Combinatorial Branch-and-Bound

A small self-contained C/C++/Rust search kernel may be used for
controlled experiments.

Potential examples:

-   N-Queens
-   Graph coloring
-   Constraint search
-   Other bounded combinatorial problems

Characteristics:

-   Irregular branching
-   Data-dependent pruning
-   Very small task descriptions
-   Large aggregate search spaces
-   Strong heterogeneity and straggler effects

This workload is useful when precise control over task size is needed.

------------------------------------------------------------------------

# 15. Secondary Workload Candidates

Depending on implementation time, the following may be evaluated:

-   Coverage-guided fuzz testing
-   Static code analysis
-   Explicit state model checking
-   Symbolic execution
-   Phylogenetic tree reconstruction
-   Mixed-integer branch-and-bound
-   High-branching game-tree search
-   Large-scale text/log processing
-   Parser validation
-   Other CPU-oriented search workloads

These should only be included where existing implementations can be
reused without creating a major secondary engineering project.

------------------------------------------------------------------------

# 16. Workloads to Avoid as Primary Evaluation

Certain workloads are poor fits for the project's specific research
objective.

## Dense Matrix Multiplication

Avoid as a primary benchmark because:

-   BLAS implementations are heavily optimized
-   CPUs have strong SIMD/cache optimizations
-   GPUs provide major acceleration
-   Results can become dominated by specialized numerical libraries
-   Large matrices conflict with the 4--8 GB worker constraint

------------------------------------------------------------------------

## Monte Carlo

Avoid as a primary CPU/GPU comparison because its massive independent
parallelism maps naturally to GPUs.

------------------------------------------------------------------------

## N-Body Simulation

Avoid as a primary CPU-oriented benchmark because GPUs can accelerate
large particle simulations substantially.

------------------------------------------------------------------------

## Ray Tracing

Avoid because modern GPUs have dedicated hardware/software ecosystems
for ray tracing.

------------------------------------------------------------------------

## Uniform Hash Cracking

Avoid because uniform hashing is extremely GPU-friendly.

------------------------------------------------------------------------

## Full-Genome Alignment

Avoid as a primary workload because:

-   Credible GPU acceleration exists
-   Reference data can exceed worker memory constraints

------------------------------------------------------------------------

## Large AI Model Inference/Training

Avoid because:

-   Memory requirements can exceed worker capabilities
-   GPU acceleration is substantial
-   The project would become an AI runtime rather than a distributed
    scheduling project

------------------------------------------------------------------------

# 17. Task Decomposition

The controller decomposes jobs into independent microtasks.

Possible decomposition models include:

### Independent Instances

``` text
SAT instance 1
SAT instance 2
SAT instance 3
...
```

### Search Prefixes

``` text
Search prefix A
Search prefix B
Search prefix C
...
```

### Data Chunks

``` text
Dataset chunk A
Dataset chunk B
Dataset chunk C
...
```

### Parameter Combinations

``` text
Compression configuration 1
Compression configuration 2
Compression configuration 3
...
```

The decomposition method depends on the workload.

The scheduler itself should remain independent of the computational
algorithm wherever possible.

------------------------------------------------------------------------

# 18. Adaptive Task Granularity

Task size can optionally be adjusted according to observed worker
performance.

For example:

``` text
Weak Worker
    ↓
Smaller task batches

Strong Worker
    ↓
Larger task batches
```

This prevents fast workers from exhausting small tasks too quickly while
reducing the risk of assigning excessively large tasks to weak workers.

Task sizing is an implementation mechanism supporting the broader
workload-aware scheduling objective, not the sole research contribution.

------------------------------------------------------------------------

# 19. Browser-State and Runtime Telemetry

Browser workers are not equivalent to dedicated cluster nodes.

The worker can report information available through browser APIs and
runtime measurements, such as:

-   Tab visibility
-   Heartbeat latency
-   Execution-time drift
-   Task completion rate
-   Recent task duration
-   Current worker state

Where reliable browser APIs are available, visibility state can help
explain changes in observed performance.

The project should not assume that browser visibility directly exposes
CPU throttling. Instead, actual execution measurements should be treated
as the stronger signal.

------------------------------------------------------------------------

# 20. Optional Native Monitor

A lightweight cross-platform companion application may be implemented if
time permits.

Its purpose is to provide information unavailable or unreliable through
browser APIs.

Potential information:

-   CPU utilization
-   Free memory
-   Battery state
-   Thermal state
-   Operating-system statistics

The browser-only workflow must remain functional without the monitor.

The monitor is therefore an enhancement rather than a core dependency.

------------------------------------------------------------------------

# 21. Fault Tolerance

The project uses a crash-fault model.

Workers may:

-   Disconnect
-   Close the browser tab
-   Stop responding
-   Become temporarily unavailable
-   Fail during task execution

The controller detects worker failure using heartbeats.

When a worker fails:

``` text
Worker
   ↓
Heartbeat timeout
   ↓
Mark offline
   ↓
Identify unfinished task
   ↓
Requeue task
   ↓
Assign to another worker
```

The system does not attempt to tolerate malicious or Byzantine workers.

------------------------------------------------------------------------

# 22. Checkpointing

Checkpointing should only be implemented for workloads where it provides
meaningful value without excessive engineering complexity.

For naturally idempotent independent tasks, re-execution is generally
simpler.

Therefore:

-   Independent microtasks should primarily use re-execution.
-   Checkpointing may be used for workloads with sufficiently large
    individual tasks.
-   Checkpoint overhead should be measured if implemented.

------------------------------------------------------------------------

# 23. Networking

The current networking architecture is centralized.

## Controller ↔ Worker

WebSocket.

Used for:

-   Registration
-   Task assignment
-   Heartbeats
-   Progress updates
-   Results
-   Worker status

## Controller → Dashboard

SSE.

Used for:

-   Worker status updates
-   Task updates
-   Scheduler information
-   Recovery events
-   Monitoring data

------------------------------------------------------------------------

# 24. Out of Scope

The following are explicitly outside the core project:

-   Full reinforcement-learning scheduler
-   WebRTC/P2P communication
-   Peer-to-peer work stealing
-   Byzantine fault tolerance
-   Blockchain
-   Consensus protocols
-   Utility/design patents
-   Large-scale GPU computing
-   Large AI model execution
-   Development of new SAT/SMT solvers
-   Development of a new fuzzing framework
-   Development of a complete compiler
-   Development of complex domain-specific computational algorithms
-   Publication as a mandatory project deliverable

The project focuses on the distributed execution and scheduling layer.

------------------------------------------------------------------------

# 25. Research Contribution

The project should distinguish between the system artifact and the
research contribution.

## System Artifact

A functioning:

-   Browser-based computing grid
-   WebAssembly execution environment
-   Worker registry
-   Task scheduler
-   Task queue
-   Fault recovery system
-   Monitoring dashboard

## Research Contribution

An experimental investigation of:

> Whether workload-specific runtime performance information can improve
> scheduling of heterogeneous browser/WebAssembly workers compared with
> static hardware-based scheduling.

The contribution is therefore not the invention of a new SAT solver,
compression algorithm, or browser computing model.

The computational workloads provide controlled environments in which the
scheduling hypothesis can be tested.

------------------------------------------------------------------------

# 26. Core Research Question

> Does workload-specific runtime performance information provide a
> significantly better basis for scheduling heterogeneous
> browser/WebAssembly workers than static hardware capability
> information?

------------------------------------------------------------------------

# 27. Supporting Research Questions

1.  Does a worker's relative performance change significantly between
    different CPU-oriented WebAssembly workloads?

2.  Can observed execution history identify workload-specific
    performance differences?

3.  Does exploiting workload-specific performance improve total job
    makespan?

4.  Does workload-aware scheduling improve worker utilization?

5.  How quickly can the scheduler adapt when a worker's performance
    changes?

6.  How does the adaptive scheduler behave when workers disconnect?

7.  Does the additional scheduling complexity justify the performance
    improvement over simpler scheduling strategies?

8.  How much controller overhead is introduced by maintaining
    workload-specific performance information?

------------------------------------------------------------------------

# 28. Experimental Hypothesis

The primary hypothesis is:

> H1: A scheduler that incorporates observed workload-specific worker
> performance can achieve lower aggregate execution time than Round
> Robin and static hardware-based scheduling when executing
> heterogeneous CPU-oriented WebAssembly workloads across heterogeneous
> browser workers.

The corresponding null hypothesis is:

> H0: Workload-specific runtime performance information does not provide
> a statistically or practically meaningful improvement over static
> capability-based scheduling for the evaluated workloads and hardware
> population.

The experiment should determine the result rather than assuming the
adaptive scheduler will always win.

------------------------------------------------------------------------

# 29. Evaluation Plan

The evaluation compares:

1.  Round Robin
2.  Static Capability-Aware
3.  Adaptive Workload-Aware

across:

-   Multiple workload types
-   Multiple worker counts
-   Heterogeneous hardware
-   Normal execution
-   Worker failures
-   Changing worker performance where feasible

------------------------------------------------------------------------

# 30. Evaluation Metrics

  -----------------------------------------------------------------------
  Metric                              Method
  ----------------------------------- -----------------------------------
  Makespan                            Total time from job submission to
                                      completion

  Throughput                          Completed tasks per unit time

  Scaling                             Measure makespan/throughput as
                                      worker count increases

  Worker utilization                  Useful computation relative to
                                      available execution time

  Load distribution                   Compare task allocation across
                                      workers

  Workload affinity                   Measure changes in worker
                                      performance rankings between
                                      workloads

  Scheduler adaptation                Measure convergence of performance
                                      estimates

  Prediction error                    Compare predicted and observed task
                                      execution times

  Failure recovery latency            Time from worker failure to
                                      successful task reassignment

  Reassignment overhead               Additional execution/work caused by
                                      worker failures

  Scheduler overhead                  Controller computation and decision
                                      latency

  Network overhead                    Bytes transferred and communication
                                      time

  Memory usage                        Peak worker memory where measurable

  WASM performance                    Compare Wasm execution against an
                                      appropriate reference

  Straggler impact                    Tail completion time and
                                      slowest-task contribution
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 31. Primary Experiment

The central experiment should use the same workload and same
heterogeneous worker population under all three schedulers.

``` text
                 Same Job
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   Round Robin   Static      Adaptive
                 Capability   Workload-Aware
        │           │           │
        └───────────┼───────────┘
                    ▼
             Compare Results
```

The experiment should then be repeated across multiple workload types.

The key question is whether the adaptive scheduler's advantage
generalizes across workloads rather than appearing only on one
benchmark.

------------------------------------------------------------------------

# 32. Workload Affinity Experiment

For each worker:

1.  Execute representative calibration tasks from each workload
    category.
2.  Record execution performance.
3.  Rank workers for each workload.
4.  Compare the rankings.

Example:

``` text
             SAT       Zstd       Regex

Worker A     1st        3rd        1st
Worker B     2nd        1st        3rd
Worker C     3rd        2nd        2nd
```

If rankings change substantially, this supports the premise that a
single scalar worker capability score is insufficient.

The adaptive scheduler can then be evaluated on whether it successfully
exploits those differences.

------------------------------------------------------------------------

# 33. Scaling Experiment

Use a fixed aggregate workload.

Run with increasing worker counts:

``` text
1 worker
2 workers
4 workers
8 workers
12 workers
16 workers
20 workers
```

Measure:

-   Makespan
-   Throughput
-   Utilization
-   Scheduling overhead
-   Network overhead

The experiment should show whether the grid provides useful aggregate
scaling.

------------------------------------------------------------------------

# 34. Heterogeneity Experiment

Construct worker groups containing different machine classes.

For example:

``` text
Weak workers
Medium workers
Strong workers
```

Compare scheduler behavior.

Round Robin should distribute tasks without regard to capability.

Static capability-aware scheduling should favor stronger machines.

Adaptive workload-aware scheduling should additionally account for
workload-specific performance.

------------------------------------------------------------------------

# 35. Failure Recovery Experiment

During execution:

1.  Start a sufficiently large job.
2.  Allow workers to process tasks.
3.  Disconnect or terminate selected workers.
4.  Measure:
    -   Failure detection time
    -   Reassignment time
    -   Additional execution
    -   Final makespan
    -   Number of requeued tasks

This demonstrates that the grid does not depend on every worker
remaining available.

------------------------------------------------------------------------

# 36. Dynamic Performance Experiment

Where practical, change worker conditions during execution.

Examples:

-   Introduce background CPU load.
-   Change worker availability.
-   Switch browser state.
-   Introduce network latency.
-   Use workers with naturally varying loads.

Observe whether the adaptive scheduler updates its performance estimates
and changes assignment decisions.

------------------------------------------------------------------------

# 37. Scheduler Overhead Experiment

Measure:

-   Decision latency
-   Number of scheduling operations
-   Controller CPU usage
-   Memory usage
-   Communication overhead

The adaptive scheduler must not introduce enough controller overhead to
eliminate the benefits gained from better task assignment.

------------------------------------------------------------------------

# 38. Optional Regret Analysis

If a bandit-based scheduler is implemented, cumulative regret can be
measured against an oracle policy.

This is optional and should not be required if it adds excessive
complexity.

The primary evaluation remains:

-   Makespan
-   Throughput
-   Utilization
-   Adaptation
-   Failure recovery

------------------------------------------------------------------------

# 39. Hardware

## Development Hardware

-   Raspberry Pi 5
-   Weak laptop
-   Strong laptop
-   Other available personal/devices

## Final Demonstration

Approximately 20 laboratory computers.

The final evaluation should intentionally include heterogeneous machines
where possible.

The project should not assume that all laboratory computers have
identical hardware.

------------------------------------------------------------------------

# 40. University Use Case

The intended deployment model is opportunistic university computing.

A university already possesses many computers that may be idle or
underutilized at various times.

Instead of installing permanent native distributed-computing clients,
the system can allow a machine to participate by opening a webpage.

Conceptually:

``` text
                 University Compute Server
                           │
                           ▼
                  Browser Compute Grid
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
     Lab PC 1           Lab PC 2           Lab PC 3
     Browser            Browser            Browser
        │                  │                  │
       Wasm               Wasm               Wasm
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ▼
                     Aggregate Compute
```

The system is not intended to replace dedicated HPC clusters.

Its useful niche is workloads that:

-   Consist of many independent tasks
-   Tolerate worker churn
-   Do not require shared memory
-   Do not require specialized GPUs
-   Can be executed in a browser
-   Can benefit from aggregate CPU capacity

Potential university use cases include:

-   Software testing
-   SAT/SMT verification
-   Fuzz testing
-   Static analysis
-   Research-data processing
-   Combinatorial search
-   Compression jobs
-   Academic algorithm experiments

------------------------------------------------------------------------

# 41. Deployment Model

The intended deployment is zero-install.

A worker should be able to:

1.  Open the worker webpage.
2.  Connect to the controller.
3.  Register capabilities.
4.  Receive tasks.
5.  Execute WebAssembly.
6.  Return results.
7.  Close the page when participation ends.

The controller should not require permanent configuration of every
worker machine.

This provides a practical distinction from traditional native
volunteer-computing systems.

------------------------------------------------------------------------

# 42. Practical Limitations

The system is not intended to outperform dedicated computing
infrastructure on every workload.

Known limitations include:

-   Browser execution overhead
-   Network communication
-   Worker churn
-   Limited browser memory
-   Browser/runtime behavior
-   CPU contention
-   Lack of dedicated GPU access
-   Central controller scalability
-   Serialization overhead

These limitations are part of the environment being studied.

The goal is to determine whether useful aggregate computation can
nevertheless be achieved and whether adaptive scheduling can improve
performance within those constraints.

------------------------------------------------------------------------

# 43. Novelty Positioning

The project should not claim that the following concepts are
individually novel:

-   WebAssembly computation
-   Browser computing
-   Volunteer computing
-   Distributed scheduling
-   Round Robin scheduling
-   Capability-aware scheduling
-   Multi-Armed Bandits
-   Speculative execution
-   Work stealing
-   Dynamic task sizing
-   Worker fault recovery

These are established areas.

The research focus should instead be the experimentally evaluated
combination and its behavior in the specific target environment:

> heterogeneous, low-resource, browser-based WebAssembly workers
> executing multiple CPU-oriented workloads.

The strongest research direction is to investigate whether
**workload-specific runtime performance profiles** materially outperform
a single static capability representation when scheduling such workers.

The novelty claim should be adjusted according to the actual literature
review and experimental results.

------------------------------------------------------------------------

# 44. Project Contributions

## Contribution 1 --- Browser-Native Distributed Computing Grid

A functioning zero-install distributed execution platform in which
browser clients participate as WebAssembly compute workers.

## Contribution 2 --- Heterogeneous Worker Management

A controller capable of discovering, monitoring, ranking, and managing
heterogeneous browser workers.

## Contribution 3 --- Workload-Aware Performance Modeling

A runtime model that records worker performance separately across
workload categories rather than relying exclusively on static hardware
information.

## Contribution 4 --- Adaptive Scheduling

A scheduler that uses observed workload-specific performance to
influence worker selection.

## Contribution 5 --- Crash-Fault Recovery

Automatic detection and reassignment of unfinished work when browser
workers disconnect or fail.

## Contribution 6 --- Experimental Evaluation

A controlled comparison of Round Robin, static capability-aware, and
adaptive workload-aware scheduling across heterogeneous real hardware.

------------------------------------------------------------------------

# 45. What the Project Is Not

The project is not primarily:

-   A new SAT solver
-   A new compression algorithm
-   A new fuzzing framework
-   A new compiler
-   A GPU computing framework
-   An HPC cluster replacement
-   A large AI inference platform
-   A browser engine
-   A commercial product

The project is a distributed computing platform whose research
contribution lies in the scheduling and runtime adaptation layer.

------------------------------------------------------------------------

# 46. Final Project Outcome

The final outcome should consist of the following artifacts.

## 46.1 Working Grid

A controller and browser worker system capable of executing WebAssembly
microtasks across multiple machines.

## 46.2 Workload Suite

A small set of CPU-oriented workloads that can be executed through the
generic task infrastructure.

## 46.3 Scheduler Implementations

-   Round Robin
-   Static Capability-Aware
-   Adaptive Workload-Aware

## 46.4 Fault Recovery

Workers can fail without causing the entire job to fail.

## 46.5 Dashboard

The system provides live visibility into:

-   Workers
-   Tasks
-   Scheduler decisions
-   Performance
-   Failures
-   Recovery

## 46.6 Experimental Results

The project demonstrates:

-   Whether workers have workload-dependent performance
-   Whether adaptive scheduling exploits that performance
-   Whether the approach reduces makespan
-   How the system scales
-   How it behaves under worker failures
-   What overhead the adaptive scheduler introduces

------------------------------------------------------------------------

# 47. Final Research Narrative

## Problem

Browser-based distributed computing enables zero-install participation
but introduces highly heterogeneous and volatile workers. Static
hardware-based scheduling may therefore fail to represent actual
WebAssembly execution capability across different workloads.

## Solution

Build a browser-native WebAssembly distributed computing grid with
multiple scheduling policies and continuously observed worker
performance.

## Research

Determine whether workload-specific runtime performance information can
improve scheduling compared with Round Robin and static capability-aware
scheduling.

## Demonstration

Run CPU-oriented workloads across approximately 20 heterogeneous
laboratory machines and compare:

``` text
Round Robin
     vs.
Static Capability-Aware
     vs.
Adaptive Workload-Aware
```

under identical workloads and hardware conditions.

## Practical Outcome

A university can use the resulting system as an opportunistic computing
platform for suitable collections of independent CPU-oriented research
or software-engineering tasks without permanently installing a
distributed-computing client on every participating machine.

------------------------------------------------------------------------

# 48. Final Project Statement

> This project develops a zero-install, browser-based distributed
> computing grid that executes CPU-oriented WebAssembly workloads across
> heterogeneous client machines. The system combines centralized task
> orchestration, worker capability discovery, runtime performance
> monitoring, adaptive workload-aware scheduling, and crash-fault
> recovery. The primary research investigation evaluates whether
> workload-specific runtime performance information can provide a more
> effective basis for scheduling heterogeneous browser workers than
> static hardware capability information. The system is evaluated using
> multiple CPU-oriented workloads and real heterogeneous laboratory
> machines, with makespan, throughput, worker utilization, adaptation,
> network overhead, and failure recovery used to assess the
> effectiveness of the proposed approach.

------------------------------------------------------------------------

# 49. Timeline

## Phase 1 --- Controller

Implement:

-   Worker registration
-   Worker states
-   Worker registry
-   Heartbeats
-   Disconnect handling
-   Failure detection

## Phase 2 --- Distributed Execution

Implement:

-   Job submission
-   Task decomposition
-   Task queue
-   Assignment
-   Result aggregation
-   Task reassignment

## Phase 3 --- Baseline Scheduling

Implement:

-   Round Robin
-   Static capability-aware scheduling

## Phase 4 --- WebAssembly Runtime

Implement:

-   Wasm loading
-   Task execution
-   Input/output serialization
-   Execution timing
-   Result handling

## Phase 5 --- Workload Integration

Select and integrate approximately 2--4 workloads.

Priority should be given to workloads that can reuse existing
implementations.

## Phase 6 --- Adaptive Scheduler

Implement:

-   Workload-specific performance history
-   Runtime capability estimates
-   Adaptive worker selection
-   Optional UCB1/ε-Greedy formulation
-   Adaptive task sizing where useful

## Phase 7 --- Fault Tolerance

Implement:

-   Heartbeat timeout
-   Worker failure detection
-   Task requeue
-   Recovery
-   Optional checkpointing

## Phase 8 --- Dashboard

Implement:

-   Worker table
-   Worker states
-   Performance information
-   Scheduler visualization
-   Task queue
-   Recovery events
-   Throughput graphs
-   Latency graphs

## Phase 9 --- Evaluation

Run:

-   Scaling experiments
-   Heterogeneity experiments
-   Workload-affinity experiments
-   Scheduler comparisons
-   Failure experiments
-   Dynamic-performance experiments
-   Scheduler-overhead measurements

## Phase 10 --- Documentation and Demonstration

Complete:

-   System documentation
-   Experimental analysis
-   Final report
-   Demonstration
-   Presentation

------------------------------------------------------------------------

# 50. Scope Summary

The final scope can be summarized as:

``` text
                    BROWSER COMPUTE GRID
                            │
             ┌──────────────┴──────────────┐
             │                             │
        SYSTEM ARTIFACT              RESEARCH COMPONENT
             │                             │
     Controller + Workers          Workload-Aware Scheduler
     WebAssembly Runtime           Runtime Performance Model
     Task Queue                    Adaptive Assignment
     Fault Recovery
     Dashboard
             │                             │
             └──────────────┬──────────────┘
                            │
                     EVALUATION SUITE
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
         SAT              Zstd             Regex
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │
                     Heterogeneous
                    Browser Workers
                            │
                            ▼
                  Experimental Results
```

The central deliverable is a working distributed computing grid.

The central research question is whether **workload-aware runtime
performance information improves scheduling across heterogeneous
browser/WebAssembly workers**.

The workloads are the experimental environment.

The scheduler is the research mechanism.

The grid is the system artifact.

The evaluation determines whether the proposed approach actually
provides a measurable benefit.
