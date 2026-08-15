from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

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
    MandelbrotTaskConfig,
    Field(discriminator=None),
]


class Task(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    task_id: int
    workload: Literal["mandelbrot"]
    config: TaskConfig