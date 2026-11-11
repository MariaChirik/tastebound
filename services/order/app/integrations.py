import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

NOTIFICATION_QUEUE = "notifications:queue"


class ServiceUnavailable(Exception):
    pass


def call(method, url, body=None, auth_header="", timeout=3):
    headers = {"Content-Type": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as err:
        try:
            payload = json.loads(err.read() or b"null")
        except ValueError:
            payload = None
        return err.code, payload
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise ServiceUnavailable(str(err)) from err


class HttpCatalog:
    def __init__(self, base_url):
        self._base = base_url.rstrip("/")

    def dishes(self, ids):
        joined = ",".join(str(i) for i in ids)
        status, body = call("GET", f"{self._base}/dishes?ids={joined}")
        if status != 200:
            raise ServiceUnavailable(f"catalog answered {status}")
        return body

    def restaurant(self, name):
        status, body = call("GET", f"{self._base}/restaurants")
        if status != 200:
            raise ServiceUnavailable(f"catalog answered {status}")
        return next((place for place in body if place["name"] == name), None)


class HttpPayments:

    def __init__(self, base_url):
        self._base = base_url.rstrip("/")

    def pay(self, auth_header, order_id, amount, method):
        return call("POST", f"{self._base}/pay",
                    {"order_id": str(order_id), "amount": amount, "method": method}, auth_header)

    def check(self, auth_header, order_id):
        return call("POST", f"{self._base}/payments/{order_id}/check", {}, auth_header)

    def refund(self, auth_header, order_id):
        return call("POST", f"{self._base}/refund/{order_id}", {}, auth_header)

    def cash_received(self, auth_header, order_id):
        return call("POST", f"{self._base}/payments/{order_id}/cash", {}, auth_header)


class RedisEvents:

    def __init__(self, url):
        import redis  # імпорт тут, щоб тести не залежали від клієнта

        self._redis = redis.from_url(url, decode_responses=True)

    def publish(self, user, message):
        try:
            self._redis.rpush(NOTIFICATION_QUEUE, f"{user}|{message}")
        except Exception as err:
            log.warning("Не вдалося поставити сповіщення в чергу: %s", err)


class HttpTracking:

    def __init__(self, base_url):
        self._base = base_url.rstrip("/")

    def update(self, auth_header, order_id, payload):
        try:
            call("POST", f"{self._base}/orders/{order_id}/status", payload, auth_header, timeout=2)
        except ServiceUnavailable as err:
            log.warning("Tracking недоступний: %s", err)


class NullEvents:
    def publish(self, user, message):
        log.info("Сповіщення для %s: %s", user, message)


class NullTracking:
    def update(self, auth_header, order_id, payload):
        pass
