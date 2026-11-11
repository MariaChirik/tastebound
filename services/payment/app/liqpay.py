import base64
import hashlib
import json
import urllib.parse
import urllib.request

CHECKOUT_URL = "https://www.liqpay.ua/api/3/checkout"
API_URL = "https://www.liqpay.ua/api/request"
PAID_STATUSES = ("success", "sandbox")
FAILED_STATUSES = ("failure", "error", "reversed")


def sign(data, private_key):
    digest = hashlib.sha1(f"{private_key}{data}{private_key}".encode()).digest()
    return base64.b64encode(digest).decode()


def encode(params, private_key):
    data = base64.b64encode(json.dumps(params, ensure_ascii=False).encode()).decode()
    return data, sign(data, private_key)


def decode(data, signature, private_key):
    if not data or sign(data, private_key) != signature:
        return None
    return json.loads(base64.b64decode(data))


class LiqPay:
    def __init__(self, public_key, private_key, result_url="", server_url="", timeout=10):
        self.public_key = public_key
        self.private_key = private_key
        self.result_url = result_url
        self.server_url = server_url
        self.timeout = timeout

    def _params(self, **extra):
        params = {"version": 3, "public_key": self.public_key, **extra}
        return params

    def checkout(self, reference, amount, description):
        params = self._params(action="pay", amount=amount, currency="UAH",
                              description=description, order_id=reference, sandbox=1)
        if self.result_url:
            params["result_url"] = self.result_url
        if self.server_url:
            params["server_url"] = self.server_url
        data, signature = encode(params, self.private_key)
        return {"url": CHECKOUT_URL, "data": data, "signature": signature}

    def _request(self, **params):
        data, signature = encode(self._params(**params), self.private_key)
        body = urllib.parse.urlencode({"data": data, "signature": signature}).encode()
        with urllib.request.urlopen(API_URL, data=body, timeout=self.timeout) as response:
            return json.loads(response.read())

    def status(self, reference):
        return self._request(action="status", order_id=reference).get("status")

    def refund(self, reference, amount):
        return self._request(action="refund", order_id=reference, amount=amount).get("status")
