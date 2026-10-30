"""Worker process: listens on all four stage queues.

Uses RQ's SimpleWorker (no fork per job) so the OCR engine and embedding model
stay loaded between jobs. Run more replicas to scale (WORKER_REPLICAS).
"""
import logging

from rq import SimpleWorker

from app.contracts import Stage
from app.jobs import queue, redis_conn


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Later stages first, so documents already in flight finish before new ones start.
    queues = [queue(s) for s in (Stage.INDEX, Stage.VALIDATE, Stage.EXTRACT, Stage.PARSE)]
    SimpleWorker(queues, connection=redis_conn()).work(with_scheduler=True)


if __name__ == "__main__":
    main()
