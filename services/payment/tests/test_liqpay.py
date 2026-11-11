import base64
import io
import json
import urllib.parse

from app import create_app, default_gateway, liqpay


def test_checkout_contains_sandbox_order_and_return_url():
    gateway = liqpay.LiqPay("pub", "priv", result_url="http://localhost:8080/#orders",
                            server_url="https://example.com/cb")
    checkout = gateway.checkout("tastebound-1-ann@x.ua", 135.0, "Замовлення №1")
    assert checkout["url"] == liqpay.CHECKOUT_URL
    params = liqpay.decode(checkout["data"], checkout["signature"], "priv")
    assert params == {"version": 3, "public_key": "pub", "action": "pay", "amount": 135.0,
                      "currency": "UAH", "description": "Замовлення №1",
                      "order_id": "tastebound-1-ann@x.ua", "sandbox": 1,
                      "result_url": "http://localhost:8080/#orders",
                      "server_url": "https://example.com/cb"}


def test_status_and_refund_requests_are_signed(monkeypatch):
    sent = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(url, data, timeout):
        form = urllib.parse.parse_qs(data.decode())
        payload = form["data"][0]
        assert liqpay.sign(payload, "priv") == form["signature"][0]
        sent.append(json.loads(base64.b64decode(payload)))
        return Response(json.dumps({"status": "sandbox"}).encode())

    monkeypatch.setattr(liqpay.urllib.request, "urlopen", fake_urlopen)
    gateway = liqpay.LiqPay("pub", "priv")
    assert gateway.status("ref-1") == "sandbox"
    assert gateway.refund("ref-1", 50.0) == "sandbox"
    assert [p["action"] for p in sent] == ["status", "refund"]
    assert sent[1]["amount"] == 50.0


def test_decode_rejects_empty_data():
    assert liqpay.decode("", "sig", "priv") is None


def test_gateway_is_enabled_only_with_both_keys(monkeypatch):
    monkeypatch.delenv("LIQPAY_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LIQPAY_PRIVATE_KEY", raising=False)
    assert default_gateway() is None
    monkeypatch.setenv("LIQPAY_PUBLIC_KEY", "pub")
    assert default_gateway() is None
    monkeypatch.setenv("LIQPAY_PRIVATE_KEY", "priv")
    assert isinstance(default_gateway(), liqpay.LiqPay)


def test_health_reports_liqpay_mode():
    from fake_redis import FakeRedis

    client = create_app(store=FakeRedis(), gateway=liqpay.LiqPay("pub", "priv")).test_client()
    assert client.get("/health").get_json()["liqpay"] is True
