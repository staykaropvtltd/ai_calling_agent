import logging
import os
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("staykaro-worker")


def main():
    logger.info("Staykaro worker started")
    concurrency = int(os.getenv("WORKER_CONCURRENCY", 4))
    logger.info(f"Worker concurrency: {concurrency}")
    while True:
        logger.debug("Worker heartbeat — waiting for jobs")
        time.sleep(30)


if __name__ == "__main__":
    main()
