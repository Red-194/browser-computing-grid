from typing import Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


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


class SATConfig(BaseModel):
    """A CNF formula and the amount of work to partition across workers.

    Literals use the standard DIMACS convention: positive integers represent
    positive variables and negative integers represent negated variables.
    """

    num_variables: int = Field(gt=0)
    clauses: list[list[int]]
    split_depth: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_formula(self):
        if self.split_depth > self.num_variables:
            raise ValueError("split_depth cannot exceed num_variables")

        for clause in self.clauses:
            for literal in clause:
                if literal == 0:
                    raise ValueError("SAT clauses cannot contain literal 0")
                if abs(literal) > self.num_variables:
                    raise ValueError(
                        "SAT literal exceeds the declared num_variables"
                    )

        return self


class SATJob(BaseModel):
    job_id: UUID | None = None
    workload: Literal["sat"]
    config: SATConfig


# Acronym-preserving aliases make the public workload API natural to use.
SatConfig = SATConfig
SatJob = SATJob


# ---------------------------------------------------------------------------
# SAT batch: many independent SAT instances, one task per instance
# ---------------------------------------------------------------------------


class SATInstance(BaseModel):
    num_variables: int = Field(gt=0)
    clauses: list[list[int]]

    @model_validator(mode="after")
    def validate_literals(self):
        for clause in self.clauses:
            for literal in clause:
                if literal == 0 or abs(literal) > self.num_variables:
                    raise ValueError("SAT literal is 0 or exceeds num_variables")
        return self


class Random3SAT(BaseModel):
    """Make `count` random 3-SAT formulas. About 4.26 clauses per variable
    is the hardest region, where run time varies the most."""

    count: int = Field(gt=0, le=10_000)
    num_variables: int = Field(ge=3)
    num_clauses: int = Field(gt=0)
    seed: int = 0


class SATBatchConfig(BaseModel):
    # Give either your own instances or a random generator, not both.
    instances: list[SATInstance] | None = None
    random_3sat: Random3SAT | None = None

    @model_validator(mode="after")
    def validate_source(self):
        if (self.instances is None) == (self.random_3sat is None):
            raise ValueError("give exactly one of instances or random_3sat")
        if self.instances is not None and len(self.instances) == 0:
            raise ValueError("instances cannot be empty")
        return self


class SATBatchJob(BaseModel):
    job_id: UUID | None = None
    workload: Literal["sat_batch"]
    config: SATBatchConfig


# ---------------------------------------------------------------------------
# Compression: chunks of data x compression variants
# ---------------------------------------------------------------------------

CompressionVariant = Literal["lz4", "zstd-fastest"]
MAX_SYNTHETIC_BYTES = 64 * 1024 * 1024


class CompressionConfig(BaseModel):
    # Each chunk is tried with every variant (a parameter sweep).
    variants: list[CompressionVariant] = ["lz4", "zstd-fastest"]
    # Big enough that compression time is worth the network transfer.
    chunk_size: int = Field(default=256 * 1024, gt=0)

    # Give either real data or a size for made-up test data.
    data_base64: str | None = None
    synthetic_size: int | None = Field(default=None, gt=0, le=MAX_SYNTHETIC_BYTES)
    seed: int = 0

    @model_validator(mode="after")
    def validate_config(self):
        if (self.data_base64 is None) == (self.synthetic_size is None):
            raise ValueError("give exactly one of data_base64 or synthetic_size")
        if not self.variants or len(set(self.variants)) != len(self.variants):
            raise ValueError("variants must be non-empty and have no repeats")
        return self


class CompressionJob(BaseModel):
    job_id: UUID | None = None
    workload: Literal["compression"]
    config: CompressionConfig


# ---------------------------------------------------------------------------
# Regex: patterns x batches of texts
# ---------------------------------------------------------------------------


class SyntheticTexts(BaseModel):
    """Random lowercase strings of different lengths."""

    count: int = Field(gt=0, le=1_000_000)
    min_length: int = Field(default=10, ge=0)
    max_length: int = Field(default=200, ge=0)
    seed: int = 0

    @model_validator(mode="after")
    def validate_lengths(self):
        if self.min_length > self.max_length:
            raise ValueError("min_length cannot exceed max_length")
        return self


class RegexConfig(BaseModel):
    patterns: list[str] = Field(min_length=1)
    # Give either your own texts or a random generator, not both.
    texts: list[str] | None = None
    synthetic_texts: SyntheticTexts | None = None
    texts_per_task: int = Field(default=100, gt=0)
    # "match" = does the text match? "scan" = count every match.
    mode: Literal["match", "scan"] = "match"
    # Stops runaway backtracking (ReDoS) in the browser.
    backtrack_limit: int = Field(default=1_000_000, gt=0, le=4_000_000_000)

    @model_validator(mode="after")
    def validate_source(self):
        if (self.texts is None) == (self.synthetic_texts is None):
            raise ValueError("give exactly one of texts or synthetic_texts")
        if self.texts is not None and len(self.texts) == 0:
            raise ValueError("texts cannot be empty")
        return self


class RegexJob(BaseModel):
    job_id: UUID | None = None
    workload: Literal["regex"]
    config: RegexConfig


# ---------------------------------------------------------------------------
# N-Queens branch and bound: one task per valid prefix of queens
# ---------------------------------------------------------------------------


class NQueensConfig(BaseModel):
    n: int = Field(ge=1, le=24)
    # Queens fixed on the first split_depth rows. More depth = more, smaller tasks.
    split_depth: int = Field(default=2, ge=0)

    @model_validator(mode="after")
    def validate_depth(self):
        if self.split_depth > self.n:
            raise ValueError("split_depth cannot exceed n")
        return self


class NQueensJob(BaseModel):
    job_id: UUID | None = None
    workload: Literal["nqueens"]
    config: NQueensConfig


# ---------------------------------------------------------------------------
# 3D CPU ray tracing, rendered into independent 2D image tiles
# ---------------------------------------------------------------------------


RayVec3 = tuple[float, float, float]


class RayCamera(BaseModel):
    position: RayVec3 = (0.0, 1.0, 6.5)
    look_at: RayVec3 = (0.0, 0.25, -1.0)
    vertical_fov_degrees: float = Field(default=42.0, gt=1.0, lt=179.0)

    @model_validator(mode="after")
    def validate_direction(self):
        if self.position == self.look_at:
            raise ValueError("camera position and look_at must differ")
        return self


class RaySphere(BaseModel):
    center: RayVec3
    radius: float = Field(gt=0.0)
    color: RayVec3
    reflectivity: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_color(self):
        if any(channel < 0.0 or channel > 1.0 for channel in self.color):
            raise ValueError("sphere color channels must be between 0 and 1")
        return self


class RayLight(BaseModel):
    position: RayVec3
    color: RayVec3 = (1.0, 1.0, 1.0)
    intensity: float = Field(default=1.0, gt=0.0)

    @model_validator(mode="after")
    def validate_color(self):
        if any(channel < 0.0 or channel > 1.0 for channel in self.color):
            raise ValueError("light color channels must be between 0 and 1")
        return self


class RayScene(BaseModel):
    camera: RayCamera = Field(default_factory=RayCamera)
    spheres: list[RaySphere] = Field(default_factory=list)
    lights: list[RayLight] = Field(default_factory=list)
    background: RayVec3 = (0.58, 0.72, 0.95)

    @model_validator(mode="after")
    def validate_background(self):
        if any(channel < 0.0 or channel > 1.0 for channel in self.background):
            raise ValueError("background color channels must be between 0 and 1")
        return self


def benchmark_ray_scene() -> RayScene:
    """A sky, floor, lit objects, and a reflective sphere for varied tile cost."""
    return RayScene(
        spheres=[
            # A large sphere acts as a simple ground plane.
            RaySphere(center=(0.0, -1001.0, -1.0), radius=1000.0,
                      color=(0.72, 0.72, 0.68), reflectivity=0.04),
            RaySphere(center=(-1.55, 0.0, -1.25), radius=0.85,
                      color=(0.88, 0.16, 0.10), reflectivity=0.08),
            RaySphere(center=(0.0, 0.0, -1.5), radius=0.82,
                      color=(0.10, 0.28, 0.82), reflectivity=0.18),
            RaySphere(center=(1.55, 0.0, -1.25), radius=0.85,
                      color=(0.82, 0.78, 0.68), reflectivity=0.82),
            RaySphere(center=(-0.35, -0.43, 0.05), radius=0.42,
                      color=(0.12, 0.62, 0.22), reflectivity=0.05),
        ],
        lights=[
            RayLight(position=(-3.5, 5.0, 3.5), intensity=42.0),
            RayLight(position=(4.0, 3.0, -0.5), color=(0.72, 0.82, 1.0), intensity=24.0),
        ],
    )


class RayTracingConfig(BaseModel):
    width: int = Field(default=640, gt=0)
    height: int = Field(default=480, gt=0)
    tile_size: int = Field(default=64, gt=0)
    samples_per_pixel: int = Field(default=2, ge=1)
    max_bounces: int = Field(default=2, ge=0)
    scene: RayScene = Field(default_factory=benchmark_ray_scene)


class RayTracingJob(BaseModel):
    job_id: UUID | None = None
    workload: Literal["raytracing"]
    config: RayTracingConfig


# Config class for each workload name. Add new workloads here.
WORKLOAD_CONFIGS = {
    "mandelbrot": MandelbrotConfig,
    "sat": SATConfig,
    "sat_batch": SATBatchConfig,
    "compression": CompressionConfig,
    "regex": RegexConfig,
    "nqueens": NQueensConfig,
    "raytracing": RayTracingConfig,
}


class JobSubmission(BaseModel):
    """Validated request model for every workload accepted by ``POST /jobs``.

    This remains a concrete model (rather than a type union) because callers
    and the existing public tests construct ``JobSubmission(...)`` directly.
    """

    job_id: UUID | None = None
    workload: Literal[
        "mandelbrot", "sat", "sat_batch", "compression", "regex", "nqueens",
        "raytracing",
    ]
    config: Union[
        MandelbrotConfig,
        SATConfig,
        SATBatchConfig,
        CompressionConfig,
        RegexConfig,
        NQueensConfig,
        RayTracingConfig,
    ]

    @model_validator(mode="before")
    @classmethod
    def parse_config_for_workload(cls, data: Any):
        # Read a plain dict config with the class that matches the workload,
        # so two workloads with similar fields can never be mixed up.
        if isinstance(data, dict):
            config_class = WORKLOAD_CONFIGS.get(data.get("workload"))
            if config_class is not None and isinstance(data.get("config"), dict):
                data = {**data, "config": config_class.model_validate(data["config"])}
        return data

    @model_validator(mode="after")
    def validate_workload_config(self):
        if not isinstance(self.config, WORKLOAD_CONFIGS[self.workload]):
            raise ValueError(
                f"{self.workload} jobs require a "
                f"{WORKLOAD_CONFIGS[self.workload].__name__}"
            )
        return self
