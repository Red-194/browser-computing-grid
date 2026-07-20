from dataclasses import dataclass, field
from datetime import datetime
from fastapi import WebSocket

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
    status: str = "Idle"
    latency: float = 0.0
    last_heartbeat: datetime | None = None
    websocket: WebSocket | None = field(default=None, repr=False, compare=False)
    metadata: WorkerMetadata | None = None