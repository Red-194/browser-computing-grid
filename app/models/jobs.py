from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class MandelbrotConfig(BaseModel):
    width: int
    height: int

    x_min: float
    x_max: float
    y_min: float
    y_max: float

    max_iterations: int
    tile_size: int


class MandelbrotJob(BaseModel):
    job_id: UUID | None = None
    workload: Literal["mandelbrot"]
    config: MandelbrotConfig


JobSubmission = Annotated[
    MandelbrotJob,
    Field(discriminator="workload"),
]