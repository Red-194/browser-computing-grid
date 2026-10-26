from typing import Annotated, Literal, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .jobs import RayScene

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


class SATTaskConfig(BaseModel):
    num_variables: int
    clauses: list[list[int]]
    fixed_assignments: list[int]


SatTaskConfig = SATTaskConfig


class CompressionTaskConfig(BaseModel):
    variant: str
    chunk_id: int
    data_base64: str


class RegexTaskConfig(BaseModel):
    pattern_id: int
    batch_id: int
    pattern: str
    texts: list[str]
    mode: str
    backtrack_limit: int


class NQueensTaskConfig(BaseModel):
    n: int
    prefix: list[int]


class RayTracingTaskConfig(BaseModel):
    width: int
    height: int
    tile_size: int
    row_block: int
    col_block: int
    samples_per_pixel: int
    max_bounces: int
    scene: RayScene


TaskConfig = Annotated[
    Union[
        MandelbrotTaskConfig,
        SATTaskConfig,
        CompressionTaskConfig,
        RegexTaskConfig,
        NQueensTaskConfig,
        RayTracingTaskConfig,
    ],
    Field(discriminator=None),
]


class Task(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    task_id: int
    # "sat_batch" tasks are sent to workers as plain "sat" tasks.
    workload: Literal[
        "mandelbrot", "sat", "compression", "regex", "nqueens", "raytracing"
    ]
    config: TaskConfig
