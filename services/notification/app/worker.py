import logging

import redis

from app import QUEUE, default_store, deliver
from app.mailer import default_mailer

log = logging.getLogger("notification.worker")


def run_once(store, timeout=5, mailer=None):
    item = store.blpop(QUEUE, timeout=timeout)
    if item is None:
        return None
    _, value = item
    return deliver(store, value, mailer=mailer)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    store = default_store()
    mailer = default_mailer()
    log.info("worker started, waiting for messages in %s", QUEUE)
    while True:
        try:
            run_once(store, mailer=mailer)
        except redis.RedisError as err:
            log.warning("Redis недоступний: %s", err)


if __name__ == "__main__":
    main()
