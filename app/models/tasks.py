from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MonteCarloTaskConfig(BaseModel):
    samples: int
    seed: int


class MatrixMultiplyTaskConfig(BaseModel):
    rows: int
    cols: int
    block_size: int

    row_block: int
    col_block: int

    random: bool = True


class MandelbrotTaskConfig(BaseModel):
    width: int
    height: int

    x_min: float
    x_max: float
    y_min: float
    y_max: float

    max_iterations: int
    tile_size: int

    row_block: int
    col_block: int


TaskConfig = Annotated[
    MonteCarloTaskConfig
    | MatrixMultiplyTaskConfig
    | MandelbrotTaskConfig,
    Field(discriminator=None),
]


class Task(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    task_id: int
    workload: Literal[
        "monte_carlo",
        "matrix_multiply",
        "mandelbrot",
    ]
    config: TaskConfig