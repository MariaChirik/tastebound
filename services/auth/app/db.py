import logging
import sqlite3
import threading
import time

log = logging.getLogger(__name__)


class SqliteDb:
    dialect = "sqlite"

    def __init__(self, path=":memory:"):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()

    def query(self, sql, params=()):
        with self._lock:
            cursor = self._conn.execute(sql, params)
            rows = cursor.fetchall()
            self._conn.commit()
            return rows


class PostgresDb:
    dialect = "postgres"

    def __init__(self, url):
        import psycopg  # імпорт тут, щоб тести не залежали від драйвера

        self._psycopg = psycopg
        self._url = url

    def query(self, sql, params=()):
        with self._psycopg.connect(self._url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql.replace("?", "%s"), params)
                return cursor.fetchall() if cursor.description else []


def connect(url, retries=15, delay=2):
    if not url:
        log.warning("DATABASE_URL не задано, дані зберігаються лише в пам'яті")
        return SqliteDb()
    db = PostgresDb(url)
    for attempt in range(1, retries + 1):
        try:
            db.query("SELECT 1")
            return db
        except Exception as err:  # psycopg.OperationalError, поки база стартує
            if attempt == retries:
                raise
            log.warning("База ще недоступна (%s), спроба %d з %d", err, attempt, retries)
            time.sleep(delay)
    return db
