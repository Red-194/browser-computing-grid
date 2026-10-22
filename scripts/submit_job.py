"""Submit one job file and print the result.

    python scripts/submit_job.py examples/nqueens.json
    python scripts/submit_job.py examples/nqueens.json http://192.168.1.23:8000

Start the server and open a /worker tab first.
"""
import json
import sys
import time
import urllib.request

if len(sys.argv) < 2:
    sys.exit("usage: python scripts/submit_job.py <job.json> [server url]")

path = sys.argv[1]
base = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8000"

with open(path) as file:
    body = file.read().encode()

request = urllib.request.Request(
    base + "/jobs", data=body, headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(request) as response:
    job = json.load(response)

job_id = job["job"]["job_id"]
print(f"job {job_id}: {job['task_count']} tasks, {len(job['assignments'])} sent to workers")
if not job["assignments"]:
    sys.exit("No worker is connected. Open /worker in a browser tab, then try again.")

start = time.time()
while time.time() - start < 300:
    with urllib.request.urlopen(f"{base}/jobs/{job_id}/result") as response:
        result = json.load(response)
    if "message" not in result:  # "still processing" replies have a message
        print(f"done in {time.time() - start:.1f}s")
        print(json.dumps(result, indent=2)[:3000])
        sys.exit(0)
    time.sleep(1)

sys.exit("No result after 300s. Check the worker tab console (F12).")
