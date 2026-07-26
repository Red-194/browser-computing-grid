from typing import Literal
from pydantic import BaseModel


class RegisterMessage(BaseModel):

    type: Literal["register"]
    uuid: str
    cores: int
    memory: float
    browser: str
    os: str


class RegisterAckMessage(BaseModel):

    type: Literal["register_ack"]
    uuid: str
    state: str

class HeartbeatMessage(BaseModel):
    
    type: Literal["heartbeat"]


class PingMessage(BaseModel):

    type: Literal["ping"]
    timestamp: float


class PongMessage(BaseModel):

    type: Literal["pong"]
    timestamp: float

