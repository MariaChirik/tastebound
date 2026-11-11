import base64
import json

from fake_redis import FakeRedis
from itsdangerous import URLSafeTimedSerializer

from app import create_app, liqpay
from app.security import TokenAuth

SECRET = "test-secret"


def headers(email="ann@example.com", role="client"):
    token = URLSafeTimedSerializer(SECRET).dumps({"email": email, "role": role})
    return {"Authorization": f"Bearer {token}"}


ANN = headers()
BOB = headers("bob@example.com")
COURIER = headers("courier@example.com", "courier")


class FakeGateway:
    private_key = "private"

    def __init__(self, status="sandbox"):
        self.next_status = status
        self.refunds = []

    def checkout(self, reference, amount, description):
        return {"url": liqpay.CHECKOUT_URL, "data": reference, "signature": "sig"}

    def status(self, reference):
        return self.next_status

    def refund(self, reference, amount):
        self.refunds.append((reference, amount))
        return "reversed"


def make_client(store=None, gateway=None):
    return create_app(store=store or FakeRedis(), gateway=gateway,
                      auth=TokenAuth(SECRET)).test_client()


def pay(client, order_id="42", amount=250, method="card", who=ANN):
    return client.post("/pay", json={"order_id": order_id, "amount": amount, "method": method},
                       headers=who)


def test_health_returns_503_when_redis_is_down():
    assert make_client(FakeRedis(down=True)).get("/health").status_code == 503


def test_payment_requires_client_login():
    client = make_client()
    assert client.post("/pay", json={"order_id": "1", "amount": 10}).status_code == 401
    assert pay(client, who=COURIER).status_code == 403


def test_test_mode_card_payment_is_paid_at_once():
    response = pay(make_client())
    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "paid" and body["mode"] == "test"
    assert body["user"] == "ann@example.com"


def test_invalid_payment_data_is_rejected():
    client = make_client()
    assert pay(client, amount=0).status_code == 400
    assert pay(client, amount=True).status_code == 400
    assert pay(client, method="crypto").status_code == 400
    assert pay(client, order_id="").status_code == 400


def test_share_cannot_be_paid_twice():
    client = make_client()
    pay(client)
    assert pay(client).status_code == 409


def test_each_participant_pays_own_share():
    client = make_client()
    pay(client, amount=150)
    pay(client, amount=100, method="cash", who=BOB)
    shares = client.get("/payments/42", headers=ANN).get_json()
    assert [(p["user"], p["status"]) for p in shares] == [
        ("ann@example.com", "paid"), ("bob@example.com", "cash_due"),
    ]


def test_courier_confirms_cash_after_delivery():
    client = make_client()
    pay(client, method="cash")
    collected = client.post("/payments/42/cash", headers=COURIER).get_json()
    assert [p["status"] for p in collected] == ["paid"]
    assert client.post("/payments/42/cash", headers=ANN).status_code == 403


def test_liqpay_card_payment_waits_for_confirmation():
    gateway = FakeGateway(status="processing")
    client = make_client(gateway=gateway)
    body = pay(client).get_json()
    assert body["status"] == "pending"
    assert body["checkout"]["url"] == liqpay.CHECKOUT_URL
    assert body["checkout"]["data"] == "tastebound-42-ann@example.com"

    assert client.post("/payments/42/check", headers=ANN).get_json()["status"] == "pending"
    gateway.next_status = "sandbox"
    assert client.post("/payments/42/check", headers=ANN).get_json()["status"] == "paid"


def test_liqpay_failure_marks_payment_failed_and_allows_retry():
    client = make_client(gateway=FakeGateway(status="failure"))
    pay(client)
    assert client.post("/payments/42/check", headers=ANN).get_json()["status"] == "failed"
    assert pay(client).status_code == 201


def test_refund_returns_paid_shares_and_cancels_cash():
    store = FakeRedis()
    client = make_client(store)
    pay(client, amount=150)
    pay(client, amount=100, method="cash", who=BOB)
    body = client.post("/refund/42", headers=ANN).get_json()
    assert [p["status"] for p in body["payments"]] == ["refunded", "cancelled"]
    assert "ann@example.com|Кошти за замовлення №42 повернено" in store.data["notifications:queue"]


def test_refund_of_liqpay_payment_calls_gateway():
    gateway = FakeGateway(status="sandbox")
    client = make_client(gateway=gateway)
    pay(client)
    client.post("/payments/42/check", headers=ANN)
    client.post("/refund/42", headers=ANN)
    assert gateway.refunds == [("tastebound-42-ann@example.com", 250.0)]


def test_unknown_payment_returns_404():
    client = make_client()
    assert client.get("/payments/999", headers=ANN).status_code == 404
    assert client.post("/refund/999", headers=ANN).status_code == 404


def test_payment_sends_notification_to_the_queue():
    store = FakeRedis()
    pay(make_client(store), order_id="7")
    assert store.data["notifications:queue"][0].startswith("ann@example.com|Оплату замовлення №7")


def test_liqpay_signature_matches_documented_formula():
    data, signature = liqpay.encode({"version": 3, "action": "pay"}, "secret")
    assert json.loads(base64.b64decode(data)) == {"version": 3, "action": "pay"}
    assert liqpay.decode(data, signature, "secret") == {"version": 3, "action": "pay"}
    assert liqpay.decode(data, signature, "wrong-key") is None


def test_liqpay_callback_with_valid_signature_marks_paid():
    gateway = FakeGateway(status="processing")
    client = make_client(gateway=gateway)
    pay(client)
    data, signature = liqpay.encode(
        {"order_id": "tastebound-42-ann@example.com", "status": "sandbox"}, "private"
    )
    forged = client.post("/liqpay/callback", data={"data": data, "signature": "bad"})
    assert forged.status_code == 400
    client.post("/liqpay/callback", data={"data": data, "signature": signature})
    assert client.get("/payments/42", headers=ANN).get_json()[0]["status"] == "paid"
