from dataclasses import dataclass
from datetime import datetime

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
    metadata: WorkerMetadata | None = None