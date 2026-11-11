from fake_redis import FakeRedis
from itsdangerous import URLSafeTimedSerializer

from app import HISTORY_SIZE, create_app, deliver
from app.mailer import SmtpMailer
from app.security import TokenAuth
from app.worker import run_once

SECRET = "test-secret"


def headers(email, role="client"):
    token = URLSafeTimedSerializer(SECRET).dumps({"email": email, "role": role})
    return {"Authorization": f"Bearer {token}"}


ADMIN = headers("admin@x.ua", "admin")
ANN = headers("ann@x.ua")


class FakeMailer:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, to, text):
        if self.fail:
            raise OSError("smtp down")
        self.sent.append((to, text))


def make_client(store=None, mailer=None):
    return create_app(store=store or FakeRedis(), auth=TokenAuth(SECRET),
                      mailer=mailer or FakeMailer()).test_client()


def test_health():
    assert make_client().get("/health").get_json()["service"] == "notification"


def test_only_admin_can_use_queue_api():
    client = make_client()
    body = {"user": "ann@x.ua", "message": "Готово"}
    assert client.post("/notifications", json=body).status_code == 401
    assert client.post("/notifications", json=body, headers=ANN).status_code == 403
    assert client.post("/notifications", json=body, headers=ADMIN).status_code == 202
    assert client.post("/notifications", json={"user": "a"}, headers=ADMIN).status_code == 400
    assert client.get("/notifications/pending", headers=ADMIN).get_json()["pending"] == 1


def test_process_sends_email_and_saves_history():
    mailer = FakeMailer()
    client = make_client(mailer=mailer)
    client.post("/notifications", json={"user": "ann@x.ua", "message": "Прийнято"},
                headers=ADMIN)
    client.post("/notifications", json={"user": "ann@x.ua", "message": "Доставлено"},
                headers=ADMIN)
    body = client.post("/notifications/process", headers=ADMIN).get_json()
    assert body["sent"] == 2
    assert mailer.sent == [("ann@x.ua", "Прийнято"), ("ann@x.ua", "Доставлено")]
    items = client.get("/users/ann@x.ua", headers=ANN).get_json()["items"]
    assert [item["message"] for item in items] == ["Доставлено", "Прийнято"]


def test_user_reads_only_own_history():
    client = make_client()
    assert client.get("/users/bob@x.ua", headers=ANN).status_code == 403
    assert client.get("/users/ann@x.ua").status_code == 401
    assert client.get("/users/ann@x.ua", headers=ANN).get_json()["items"] == []


def test_mail_failure_still_keeps_notification_in_app():
    store = FakeRedis()
    result = deliver(store, "ann@x.ua|Готується", mailer=FakeMailer(fail=True))
    assert result["email"] is False
    assert len(store.data["notifications:user:ann@x.ua"]) == 1


def test_history_keeps_only_last_messages():
    store = FakeRedis()
    for n in range(HISTORY_SIZE + 5):
        deliver(store, f"ann@x.ua|msg {n}", mailer=FakeMailer())
    assert len(store.data["notifications:user:ann@x.ua"]) == HISTORY_SIZE


def test_worker_takes_one_message_from_queue():
    store, mailer = FakeRedis(), FakeMailer()
    store.rpush("notifications:queue", "ann@x.ua|Замовлення №1 готується")
    assert run_once(store, mailer=mailer)["message"] == "Замовлення №1 готується"
    assert run_once(store, mailer=mailer) is None
    assert mailer.sent == [("ann@x.ua", "Замовлення №1 готується")]


def test_smtp_mailer_builds_letter(monkeypatch):
    sent = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            sent.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def send_message(self, message):
            sent.append((message["To"], message["Subject"], message.get_content().strip()))

    monkeypatch.setattr("app.mailer.smtplib.SMTP", FakeSmtp)
    SmtpMailer("mailpit", 1025).send("ann@x.ua", "Доставлено")
    assert sent[0] == ("connect", "mailpit", 1025)
    assert sent[1][0] == "ann@x.ua"
    assert sent[1][2].startswith("Доставлено")
