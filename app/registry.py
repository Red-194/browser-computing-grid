from .models.worker import Worker

workers: dict[str, Worker] = {}
aggregators: dict[str, object] = {}
task_counts: dict[str, int] = {}
completed_jobs: set[str] = set()