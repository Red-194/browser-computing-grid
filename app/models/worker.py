from dataclasses import dataclass, field
from datetime import datetime
from fastapi import WebSocket

class WorkerStates:
    IDLE = "Idle"
    BUSY = "Busy"
    OFFLINE = "Offline"

@dataclass
class WorkerMetadata:
    browser: str | None = None
    os: str | None = None

@dataclass
class Worker:
    uuid: str
    ip: str
    cores: int
    memory: float
    state: str = WorkerStates.IDLE
    latency: float = 0.0
    last_heartbeat: datetime | None = None
    websocket: WebSocket | None = field(default=None, repr=False, compare=False)
    metadata: WorkerMetadata | None = None