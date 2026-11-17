"""python -m app.workers.clean_worker (migrations are run by the API container)."""
import logging
import signal
import threading

from app.services.clean_task_queue import run_worker


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    run_worker(stop)


if __name__ == "__main__":
    main()
