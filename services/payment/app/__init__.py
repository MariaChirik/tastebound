import logging
import os
import uuid

import redis
from flask import Flask, g, jsonify, request

from app import liqpay as lp
from app.security import TokenAuth

SERVICE = "payment"
NOTIFICATION_QUEUE = "notifications:queue"
METHODS = ("card", "cash")

log = logging.getLogger(SERVICE)


def default_store():
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(url, decode_responses=True)


def default_gateway():
    public_key = os.environ.get("LIQPAY_PUBLIC_KEY")
    private_key = os.environ.get("LIQPAY_PRIVATE_KEY")
    if not public_key or not private_key:
        return None
    return lp.LiqPay(public_key, private_key,
                     result_url=os.environ.get("LIQPAY_RESULT_URL", ""),
                     server_url=os.environ.get("LIQPAY_SERVER_URL", ""))


def payment_key(order_id, user):
    return f"payment:{order_id}:{user}"


def reference(order_id, user):
    return f"tastebound-{order_id}-{user}"


def create_app(store=None, gateway="env", auth=None):
    store = store if store is not None else default_store()
    gateway = default_gateway() if gateway == "env" else gateway
    auth = auth or TokenAuth()
    app = Flask(__name__)
    app.json.ensure_ascii = False

    @app.errorhandler(redis.RedisError)
    def storage_down(err):
        return jsonify(error="сховище даних тимчасово недоступне"), 503

    @app.get("/health")
    def health():
        store.ping()
        return jsonify(status="ok", service=SERVICE, liqpay=gateway is not None)

    def notify(user, message):
        if user:
            store.rpush(NOTIFICATION_QUEUE, f"{user}|{message}")

    def load(order_id, user):
        payment = store.hgetall(payment_key(order_id, user))
        if payment:
            payment["amount"] = float(payment["amount"])
        return payment

    def save(payment, **changes):
        payment.update(changes)
        store.hset(payment_key(payment["order_id"], payment["user"]), mapping=payment)
        return payment

    def mark_paid(payment):
        save(payment, status="paid")
        notify(payment["user"],
               f"Оплату замовлення №{payment['order_id']} на {payment['amount']:.2f} грн отримано")
        return payment

    @app.post("/pay")
    @auth.require("client")
    def pay():
        data = request.get_json(silent=True) or {}
        order_id, amount = str(data.get("order_id") or ""), data.get("amount")
        method = data.get("method", "card")
        if not order_id or isinstance(amount, bool) or not isinstance(amount, (int, float)) \
                or amount <= 0:
            return jsonify(error="потрібні номер замовлення і сума більше нуля"), 400
        if method not in METHODS:
            return jsonify(error="оберіть оплату карткою або готівкою"), 400
        user = g.user["email"]
        existing = load(order_id, user)
        if existing and existing["status"] in ("paid", "cash_due"):
            return jsonify(error="цю частку вже оплачено"), 409

        payment = {
            "id": str(uuid.uuid4()), "order_id": order_id, "user": user,
            "amount": round(float(amount), 2), "method": method,
            "mode": "liqpay" if gateway and method == "card" else "test",
        }
        store.sadd(f"payments:{order_id}", user)
        if method == "cash":
            save(payment, status="cash_due")
            notify(user, f"Замовлення №{order_id}: оплата {amount:.2f} грн готівкою кур'єру")
            return jsonify(payment), 201
        if gateway is None:
            return jsonify(mark_paid(payment)), 201

        save(payment, status="pending")
        checkout = gateway.checkout(reference(order_id, user), payment["amount"],
                                    f"Tastebound, замовлення №{order_id}")
        return jsonify({**payment, "checkout": checkout}), 201

    @app.post("/payments/<order_id>/check")
    @auth.require("client")
    def check(order_id):
        payment = load(order_id, g.user["email"])
        if not payment:
            return jsonify(error="платіж не знайдено"), 404
        if payment["status"] == "pending" and gateway is not None:
            try:
                status = gateway.status(reference(order_id, payment["user"]))
            except Exception as err:
                log.warning("LiqPay недоступний: %s", err)
                return jsonify(error="платіжний сервіс тимчасово недоступний"), 502
            if status in lp.PAID_STATUSES:
                mark_paid(payment)
            elif status in lp.FAILED_STATUSES:
                save(payment, status="failed")
        return jsonify(payment)

    @app.post("/liqpay/callback")
    def callback():
        if gateway is None:
            return jsonify(error="LiqPay не налаштовано"), 404
        result = lp.decode(request.form.get("data"), request.form.get("signature"),
                           gateway.private_key)
        if result is None:
            return jsonify(error="некоректний підпис"), 400
        prefix, _, rest = str(result.get("order_id", "")).partition("-")
        order_id, _, user = rest.partition("-")
        payment = load(order_id, user) if prefix == "tastebound" else None
        if payment and payment["status"] == "pending":
            if result.get("status") in lp.PAID_STATUSES:
                mark_paid(payment)
            elif result.get("status") in lp.FAILED_STATUSES:
                save(payment, status="failed")
        return jsonify(received=True)

    @app.get("/payments/<order_id>")
    @auth.require()
    def get_payments(order_id):
        users = sorted(store.smembers(f"payments:{order_id}"))
        if not users:
            return jsonify(error="платіж не знайдено"), 404
        return jsonify([load(order_id, user) for user in users])

    @app.post("/payments/<order_id>/cash")
    @auth.require("courier")
    def cash_received(order_id):
        collected = []
        for user in sorted(store.smembers(f"payments:{order_id}")):
            payment = load(order_id, user)
            if payment["status"] == "cash_due":
                collected.append(mark_paid(payment))
        return jsonify(collected)

    @app.post("/refund/<order_id>")
    @auth.require("client", "admin")
    def refund(order_id):
        users = sorted(store.smembers(f"payments:{order_id}"))
        if not users:
            return jsonify(error="платіж не знайдено"), 404
        result = []
        for user in users:
            payment = load(order_id, user)
            if payment["status"] == "paid":
                if payment["mode"] == "liqpay" and gateway is not None:
                    try:
                        gateway.refund(reference(order_id, user), payment["amount"])
                    except Exception as err:
                        log.warning("LiqPay refund failed: %s", err)
                save(payment, status="refunded")
                notify(user, f"Кошти за замовлення №{order_id} повернено")
            elif payment["status"] in ("pending", "cash_due"):
                save(payment, status="cancelled")
            result.append(payment)
        return jsonify(order_id=order_id, payments=result)

    return app
