import redis

from app import mailer, worker
from app.mailer import LogMailer, SmtpMailer, default_mailer


def test_default_mailer_follows_settings(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert isinstance(default_mailer(), LogMailer)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_STARTTLS", "true")
    monkeypatch.setenv("SMTP_USER", "bot")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    m = default_mailer()
    assert (m.host, m.port, m.starttls, m.username) == ("smtp.example.com", 587, True, "bot")


def test_real_smtp_uses_tls_and_login(monkeypatch):
    calls = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            calls.append("connect")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            calls.append("starttls")

        def login(self, user, password):
            calls.append(("login", user))

        def send_message(self, message):
            calls.append(("send", message["To"]))

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSmtp)
    SmtpMailer("smtp.example.com", 587, username="bot", password="pw", starttls=True).send(
        "ann@x.ua", "Готово")
    assert calls == ["connect", "starttls", ("login", "bot"), ("send", "ann@x.ua")]
    LogMailer().send("ann@x.ua", "Готово")


def test_worker_keeps_running_when_redis_fails(monkeypatch):
    class Stop(Exception):
        pass

    attempts = []

    def fake_run_once(store, mailer=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise redis.RedisError("down")
        raise Stop()

    monkeypatch.setattr(worker, "default_store", lambda: object())
    monkeypatch.setattr(worker, "run_once", fake_run_once)
    try:
        worker.main()
    except Stop:
        pass
    assert len(attempts) == 2
