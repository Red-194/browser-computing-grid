from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field


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


class MonteCarloJob(BaseModel):
    job_id: UUID | None = None
    workload: Literal["monte_carlo"]
    config: MonteCarloConfig


class MatrixMultiplyJob(BaseModel):
    job_id: UUID | None = None
    workload: Literal["matrix_multiply"]
    config: MatrixMultiplyConfig


class MandelbrotJob(BaseModel):
    job_id: UUID | None = None
    workload: Literal["mandelbrot"]
    config: MandelbrotConfig


JobSubmission = Annotated[
    MonteCarloJob | MatrixMultiplyJob | MandelbrotJob,
    Field(discriminator="workload")
]