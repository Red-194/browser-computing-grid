from typing import Literal
from pydantic import BaseModel


class RegisterMessage(BaseModel):

    type: Literal["register"]
    cores: int
    memory: int
    browser: str
    os: str


class RegisterAckMessage(BaseModel):

    type: Literal["register_ack"]
    uuid: str


class HeartbeatMessage(BaseModel):
    
    type: Literal["heartbeat"]


class PingMessage(BaseModel):

    type: Literal["ping"]
    timestamp: float


class PongMessage(BaseModel):

    type: Literal["pong"]
    timestamp: float

