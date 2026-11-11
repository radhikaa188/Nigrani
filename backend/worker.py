"""
Background worker process for Nigrani platform (Stage 3, Task 25).

Connects to Redis via RQ and executes jobs with concurrency 1.
Run from repository root:
    python backend/worker.py
Or from backend directory:
    python worker.py
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys

# Ensure backend directory and repository root are in sys.path for job & sandbox imports
BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
for _p in (str(REPO_ROOT), str(BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rq import SimpleWorker  # noqa: E402
from rq.queue import Queue  # noqa: E402

from app.queue import (  # noqa: E402
    DEFAULT_QUEUE_NAME,
    get_default_queue_name,
    get_redis_connection,
    get_redis_url,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("nigrani.worker")


def run_worker(queue_name: str | None = None, burst: bool = False) -> None:
    """Run an RQ worker listening on the specified queue."""
    redis_url = get_redis_url()
    logger.info("Connecting to Redis at %s", redis_url)
    conn = get_redis_connection()

    effective_queue = queue_name or get_default_queue_name()
    queue = Queue(effective_queue, connection=conn)
    logger.info(
        "Starting worker (PID %s, concurrency=1, burst=%s) listening on queue '%s'...",
        os.getpid(),
        burst,
        effective_queue,
    )

    # SimpleWorker runs jobs sequentially in-process (concurrency 1, Windows and Linux compatible)
    worker = SimpleWorker([queue], connection=conn)
    worker.work(burst=burst)
    logger.info("Worker stopped.")


def main() -> None:
    """CLI entrypoint for worker script."""
    parser = argparse.ArgumentParser(description="Nigrani RQ Background Worker")
    parser.add_argument(
        "--queue",
        "-q",
        default=DEFAULT_QUEUE_NAME,
        help=f"Queue name to listen on (default: {DEFAULT_QUEUE_NAME})",
    )
    parser.add_argument(
        "--burst",
        "-b",
        action="store_true",
        help="Run in burst mode: exit as soon as all jobs are processed",
    )
    args = parser.parse_args()

    run_worker(queue_name=args.queue, burst=args.burst)


if __name__ == "__main__":
    main()
