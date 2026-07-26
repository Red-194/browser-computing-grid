from typing import Annotated, Literal

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
    workload: Literal["monte_carlo"]
    config: MonteCarloConfig


class MatrixMultiplyJob(BaseModel):
    workload: Literal["matrix_multiply"]
    config: MatrixMultiplyConfig


class MandelbrotJob(BaseModel):
    workload: Literal["mandelbrot"]
    config: MandelbrotConfig


JobSubmission = Annotated[
    MonteCarloJob | MatrixMultiplyJob | MandelbrotJob,
    Field(discriminator="workload")
]