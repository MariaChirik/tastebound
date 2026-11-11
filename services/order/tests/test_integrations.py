import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.integrations import (
    HttpCatalog,
    HttpPayments,
    HttpTracking,
    NullEvents,
    NullTracking,
    ServiceUnavailable,
    call,
)

DISHES = [{"id": 1, "name": "Борщ", "restaurant": "Хата", "price": 135.0, "orderable": True}]
PLACES = [{"name": "Хата", "lat": 50.45, "lng": 30.52, "overloaded": False}]


class Handler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *args):
        pass

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        Handler.seen.append(("GET", self.path, self.headers.get("Authorization")))
        if self.path.startswith("/dishes"):
            self.reply(200, DISHES)
        elif self.path == "/restaurants":
            self.reply(200, PLACES)
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"null")
        Handler.seen.append(("POST", self.path, self.headers.get("Authorization"), body))
        if self.path == "/pay":
            self.reply(201, {"status": "paid"})
        elif self.path.endswith("/broken"):
            self.send_response(500)
            self.send_header("Content-Length", "4")
            self.end_headers()
            self.wfile.write(b"oops")
        else:
            self.reply(200, {"ok": True})


@pytest.fixture(scope="module")
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % httpd.server_port
    httpd.shutdown()


def test_call_returns_status_and_json(server):
    assert call("GET", server + "/restaurants") == (200, PLACES)
    assert call("GET", server + "/missing") == (404, {"error": "not found"})


def test_call_survives_error_without_json(server):
    assert call("POST", server + "/broken", {}) == (500, None)


def test_unreachable_service_raises():
    with pytest.raises(ServiceUnavailable):
        call("GET", "http://127.0.0.1:9/health", timeout=1)


def test_catalog_client(server):
    catalog = HttpCatalog(server + "/")
    assert catalog.dishes([1, 2]) == DISHES
    assert ("GET", "/dishes?ids=1,2", None) in Handler.seen
    assert catalog.restaurant("Хата") == PLACES[0]
    assert catalog.restaurant("Невідомий") is None


def test_catalog_errors_become_unavailable():
    with pytest.raises(ServiceUnavailable):
        HttpCatalog("http://127.0.0.1:9").dishes([1])


def test_payments_forward_user_token(server):
    payments = HttpPayments(server)
    assert payments.pay("Bearer abc", 7, 135.0, "card") == (201, {"status": "paid"})
    assert Handler.seen[-1] == ("POST", "/pay", "Bearer abc",
                                {"order_id": "7", "amount": 135.0, "method": "card"})
    for action, path in ((payments.check, "/payments/7/check"), (payments.refund, "/refund/7"),
                         (payments.cash_received, "/payments/7/cash")):
        assert action("Bearer abc", 7)[0] == 200
        assert Handler.seen[-1][1] == path


def test_tracking_failures_do_not_break_orders(server):
    HttpTracking(server).update("Bearer abc", 7, {"status": "cooking"})
    assert Handler.seen[-1][1] == "/orders/7/status"
    HttpTracking("http://127.0.0.1:9").update("", 7, {"status": "cooking"})
    NullTracking().update("", 7, {})
    NullEvents().publish("ann", "hello")
