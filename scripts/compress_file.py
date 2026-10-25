"""Upload a real file, compress it on the grid, and print the results.

    python scripts/compress_file.py path/to/file
    python scripts/compress_file.py path/to/file --variants lz4 --chunk-size 524288
    python scripts/compress_file.py path/to/file --server http://192.168.1.23:8000

Start the server and open at least one /worker tab first.
"""
import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger("grid.cli.compress_file")

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("file")
parser.add_argument("--variants", nargs="+", default=["lz4", "zstd-fastest"])
parser.add_argument("--chunk-size", type=int, default=262144)
parser.add_argument("--server", default="http://127.0.0.1:8000")
args = parser.parse_args()

path = Path(args.file)
boundary = uuid.uuid4().hex
fields = {"variants": ",".join(args.variants), "chunk_size": str(args.chunk_size)}
body = b"".join(
    f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, v in fields.items()
)
body += (
    f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
    f'filename="{path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'
).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()

request = urllib.request.Request(
    args.server + "/jobs/compression/upload",
    data=body,
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
)
try:
    with urllib.request.urlopen(request) as response:
        job = json.load(response)
except urllib.error.HTTPError as error:
    sys.exit(f"upload rejected ({error.code}): {error.read().decode()}")

job_id = job["job"]["job_id"]
logger.info(
    "Job %s: %d tasks, %d sent to workers",
    job_id,
    job["task_count"],
    len(job["assignments"]),
)
if not job["assignments"]:
    sys.exit("No worker is connected. Open /worker in a browser tab, then try again.")

start = time.time()
while time.time() - start < 600:
    with urllib.request.urlopen(f"{args.server}/jobs/{job_id}/result") as response:
        result = json.load(response)
    if "message" not in result:
        logger.info("Job %s completed in %.1f seconds", job_id, time.time() - start)
        logger.info("Result: %s", json.dumps(result, indent=2))
        sys.exit(0)
    time.sleep(1)
sys.exit("timed out waiting for the result")
