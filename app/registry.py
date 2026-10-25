from .models.worker import Worker

workers: dict[str, Worker] = {}
job_pcbs: dict[str, object] = {}
job_tasks: dict[str, dict[int, object]] = {}
worker_pcbs: dict[str, object] = {}
aggregators: dict[str, object] = {}
task_counts: dict[str, int] = {}
completed_jobs: set[str] = set()
job_start_times: dict[str, float] = {}