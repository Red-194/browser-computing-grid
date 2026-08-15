from typing import Any
from uuid import UUID

from pydantic import BaseModel


class MonteCarloConfig(BaseModel):
    samples: int
    seed: int | None = None


class MatrixMultiplyConfig(BaseModel):
    rows: int
    cols: int
    block_size: int
    random: bool = True


class MandelbrotConfig(BaseModel):
    width: int
    height: int
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    max_iterations: int
    tile_size: int


class JobSubmission(BaseModel):
    job_id: UUID | None = None
    workload: str
    config: dict[str, Any]