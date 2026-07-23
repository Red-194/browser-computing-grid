# Adaptive Browser Compute Grid — Final Year Project Scope & Plan

## One-line pitch
A zero-install, browser-native distributed computing grid with capability-aware adaptive scheduling and crash-fault recovery, executing WebAssembly workloads across heterogeneous devices.

---

# Final Scope

## In Scope

### 1. Controller

- Worker registration & deregistration
- Worker registry
- Worker state management
- Heartbeat monitoring
- Latency measurement
- Capability discovery
- Job submission
- Task decomposition
- Result aggregation
- Failure detection
- Task reassignment
- Scheduler interface
- Administrative controls (worker disconnect)

---

### 2. Scheduler

Three scheduling strategies will be implemented and experimentally compared.

#### 2.1 Round Robin

A simple baseline scheduler.

Purpose:
- Fair distribution
- Baseline comparison

---

#### 2.2 Capability-Aware Scheduler

A heuristic scheduler that ranks workers using static capability information.

Scheduling factors include:

- CPU cores
- Available memory
- Current latency
- Worker health
- Current load

This scheduler provides a deterministic baseline.

---

#### 2.3 Adaptive Multi-Armed Bandit Scheduler (AI Component)

The proposed intelligent scheduler models each worker as an independent **bandit arm**.

Rather than relying solely on static hardware information, the scheduler continuously learns which workers perform best under real workloads.

Each completed task updates the worker's estimated reward.

Example reward function:

Reward =
- Low execution time
- Successful completion
- Stable availability

Penalty =
- Timeout
- Failure
- Task reassignment
- High latency

The scheduler balances:

- **Exploration**
  - Occasionally testing workers with limited history.

- **Exploitation**
  - Prioritizing workers with consistently strong performance.

Candidate algorithms:

- UCB1 (Upper Confidence Bound)
- ε-Greedy

The scheduler continuously adapts to:

- Workers joining
- Workers leaving
- Performance degradation
- Device throttling
- Network instability

No offline training or labelled dataset is required.

---

### 3. Worker Runtime

Browser-native execution engine.

Features:

- Worker registration
- Heartbeat transmission
- Ping response
- Task execution
- Progress reporting
- Result submission
- Automatic reconnect

---

### 4. Compute Runtime

Execution through WebAssembly.

Features:

- WASM module loading
- JavaScript fallback
- Sandboxed execution
- Serialization
- Dynamic compute kernels

---

### 5. Optional Native Monitor

A lightweight cross-platform companion application.

Purpose:

Provide richer runtime information unavailable through browser APIs.

Examples:

- CPU utilization
- Free memory
- Battery
- Thermal state
- Operating-system statistics

The browser-only workflow remains fully functional.

The monitor simply improves scheduling precision.

---

### 6. Fault Tolerance

Crash-fault model only.

Features:

- Heartbeat timeout detection
- Worker failure detection
- Automatic task reassignment
- Periodic checkpointing
- Resume from latest checkpoint
- Re-execution when recovery is impossible

---

### 7. Networking

Current implementation:

- WebSocket (Controller ↔ Workers)
- SSE (Dashboard updates)

No peer-to-peer communication is included.

---

### 8. Dashboard

Live monitoring interface.

Features:

- Worker table
- Worker states
- Capability tier
- Task queue
- Scheduler visualization
- Recovery log
- Latency graph
- Throughput graph
- Controller controls

---

### 9. Benchmark Workload

A single embarrassingly-parallel workload.

Candidate options:

- Mandelbrot rendering
- Matrix multiplication
- Monte Carlo simulation

---

# Explicitly Out of Scope

- Full Reinforcement Learning scheduler
- WebRTC / P2P communication
- Work stealing
- Speculative execution
- Byzantine fault tolerance
- Blockchain / consensus
- Utility/design patents
- Publication as a project deliverable

---

# Evaluation Plan

| Metric | Method |
|---------|--------|
| Throughput scaling | Fixed workload, vary number of workers |
| Makespan | Compare all three schedulers |
| Scheduler adaptation | Measure how quickly the bandit converges toward selecting higher-performing workers |
| Regret analysis | Compare cumulative regret of the bandit scheduler against an oracle policy (optional if time permits) |
| Failure recovery | Kill a worker mid-task and measure recovery latency |
| Load balancing | Compare workload distribution across heterogeneous devices |
| WASM vs JavaScript | Measure execution speed improvement |
| Checkpoint overhead | Measure additional runtime introduced by checkpointing |
| Scheduler overhead | Measure scheduling decision time and controller CPU usage |

---

# Hardware

Development

- Raspberry Pi 5
- Weak laptop
- Strong laptop

Final Demonstration

~20 laboratory computers

---

# Timeline

### Phase 1

Controller completion

- Worker states
- Disconnect handling
- Heartbeat timeout

---

### Phase 2

Distributed execution

- Job submission
- Task decomposition
- Result aggregation

---

### Phase 3

Schedulers

- Round Robin
- Capability-aware
- Multi-Armed Bandit

---

### Phase 4

WebAssembly runtime

---

### Phase 5

Fault tolerance

---

### Phase 6

Optional native monitor

---

### Phase 7

Evaluation on laboratory machines

---

### Phase 8

Documentation and demonstration

---

# Report Narrative

## Problem

Distributed computing remains difficult to deploy due to installation requirements, administrative overhead, and heterogeneous hardware.

---

## Proposed Solution

A browser-native distributed computing framework capable of utilizing heterogeneous devices through zero-install browser workers.

---

## Contributions

- Browser-native distributed execution
- Capability-aware scheduling
- Adaptive Multi-Armed Bandit scheduler
- Crash-fault recovery
- WebAssembly execution
- Experimental evaluation on heterogeneous hardware

---

## Scope

Crash-fault tolerance only.

Byzantine fault tolerance is identified as future work.

---

## Evidence

The system will be evaluated using throughput, scheduling efficiency, scheduler adaptation, fault recovery, load balancing, and WASM performance across heterogeneous real hardware.