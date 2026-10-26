from .models.worker import Worker

workers: dict[str, Worker] = {}
aggregators: dict[str, object] = {}
task_counts: dict[str, int] = {}
completed_jobs: set[str] = set()
job_start_times: dict[str, float] = {}

# Track each task's assigned worker and current status.
task_assignments: dict[str, dict[int, dict]] = {}