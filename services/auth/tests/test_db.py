import sys
import types

import pytest

from app import db as dbmod


class FakeCursor:
    def __init__(self, log, fail):
        self.log, self.fail, self.description = log, fail, None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        if self.fail():
            raise ConnectionError("database is starting")
        self.log.append((sql, params))
        self.description = ("column",) if sql.startswith("SELECT") else None

    def fetchall(self):
        return [(1,)]


def fake_psycopg(monkeypatch, failures=0):
    log, state = [], {"left": failures}

    def fail():
        if state["left"]:
            state["left"] -= 1
            return True
        return False

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return FakeCursor(log, fail)

    module = types.SimpleNamespace(connect=lambda url: Conn())
    monkeypatch.setitem(sys.modules, "psycopg", module)
    return log


def test_without_url_data_lives_in_memory():
    db = dbmod.connect(None)
    assert db.dialect == "sqlite"
    db.query("CREATE TABLE t (x INTEGER)")
    db.query("INSERT INTO t (x) VALUES (?)", (5,))
    assert db.query("SELECT x FROM t") == [(5,)]


def test_postgres_placeholders_are_converted(monkeypatch):
    log = fake_psycopg(monkeypatch)
    db = dbmod.connect("postgresql://user:pass@db/test", retries=1)
    assert db.dialect == "postgres"
    assert db.query("SELECT * FROM t WHERE a = ? AND b = ?", (1, 2)) == [(1,)]
    assert log[-1] == ("SELECT * FROM t WHERE a = %s AND b = %s", (1, 2))
    assert db.query("UPDATE t SET a = ?", (3,)) == []


def test_connect_waits_until_database_is_ready(monkeypatch):
    fake_psycopg(monkeypatch, failures=2)
    db = dbmod.connect("postgresql://db/test", retries=5, delay=0)
    assert db.dialect == "postgres"


def test_connect_gives_up_after_all_retries(monkeypatch):
    fake_psycopg(monkeypatch, failures=10)
    with pytest.raises(ConnectionError):
        dbmod.connect("postgresql://db/test", retries=3, delay=0)
