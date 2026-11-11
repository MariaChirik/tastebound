import json
import os
import secrets
import time

from flask import Flask, g, jsonify, request

from app.db import connect
from app.integrations import (
    HttpCatalog,
    HttpPayments,
    HttpTracking,
    NullEvents,
    NullTracking,
    RedisEvents,
    ServiceUnavailable,
)
from app.logic import (
    STATUS_MESSAGES,
    TRACKING_STATUS,
    all_settled,
    calculate_total,
    can_advance,
    can_cancel,
    distance_km,
    estimate_delivery_minutes,
    kitchen_load,
    next_status,
    parse_location,
    price_lines,
    road_minutes,
    shares_of,
    validate_lines,
    validate_schedule,
    visible_statuses,
)
from app.security import TokenAuth, bearer_header

MAX_DISTANCE_KM = 30
ID_COLUMN = {
    "sqlite": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "postgres": "SERIAL PRIMARY KEY",
}
COLUMNS = (
    "id, owner, participants, restaurant, items, shares, total, status, address, lat, lng,"
    " restaurant_lat, restaurant_lng, distance_km, eta_minutes, created_at, deliver_at,"
    " scheduled, group_code"
)
JSON_COLUMNS = ("items", "shares")
GROUP_COLUMNS = "code, owner, restaurant, items, status, order_id, created_at"


def schema(dialect):
    return [
        f"""
        CREATE TABLE IF NOT EXISTS orders (
            id {ID_COLUMN[dialect]},
            owner TEXT NOT NULL,
            participants TEXT NOT NULL,
            restaurant TEXT NOT NULL,
            items TEXT NOT NULL,
            shares TEXT NOT NULL,
            total DOUBLE PRECISION NOT NULL,
            status TEXT NOT NULL,
            address TEXT NOT NULL,
            lat DOUBLE PRECISION NOT NULL,
            lng DOUBLE PRECISION NOT NULL,
            restaurant_lat DOUBLE PRECISION NOT NULL,
            restaurant_lng DOUBLE PRECISION NOT NULL,
            distance_km DOUBLE PRECISION NOT NULL,
            eta_minutes INTEGER NOT NULL,
            created_at DOUBLE PRECISION NOT NULL,
            deliver_at DOUBLE PRECISION NOT NULL,
            scheduled INTEGER NOT NULL DEFAULT 0,
            group_code TEXT NOT NULL DEFAULT ''
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS order_groups (
            code TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            restaurant TEXT NOT NULL DEFAULT '',
            items TEXT NOT NULL,
            status TEXT NOT NULL,
            order_id INTEGER,
            created_at DOUBLE PRECISION NOT NULL
        )
        """,
    ]


def row_to_order(row):
    order = dict(zip(COLUMNS.replace(" ", "").split(","), row))
    for key in JSON_COLUMNS:
        order[key] = json.loads(order[key])
    order["participants"] = [user for user in order["participants"].split(",") if user]
    order["scheduled"] = bool(order["scheduled"])
    return order


def row_to_group(row):
    group = dict(zip(GROUP_COLUMNS.split(", "), row))
    group["items"] = json.loads(group["items"])
    group["shares"] = shares_of(group["items"])
    group["total"] = calculate_total(group["items"])
    return group


def from_env(factory, name, fallback=None):
    url = os.environ.get(name)
    return factory(url) if url else fallback


def create_app(db=None, events=None, tracking=None, catalog=None, payments=None,
               auth=None, clock=time.time):
    app = Flask(__name__)
    app.json.ensure_ascii = False
    auth = auth or TokenAuth()
    db = db if db is not None else connect(os.environ.get("DATABASE_URL"))
    events = events or from_env(RedisEvents, "REDIS_URL", NullEvents())
    tracking = tracking or from_env(HttpTracking, "TRACKING_URL", NullTracking())
    catalog = catalog or HttpCatalog(os.environ.get("CATALOG_URL", "http://catalog:5000"))
    payments = payments or HttpPayments(os.environ.get("PAYMENT_URL", "http://payment:5000"))
    for statement in schema(db.dialect):
        db.query(statement)

    @app.errorhandler(ServiceUnavailable)
    def dependency_down(err):
        return jsonify(error="a required service is unavailable, try again later"), 503

    def find_order(order_id):
        rows = db.query(f"SELECT {COLUMNS} FROM orders WHERE id = ?", (order_id,))
        return row_to_order(rows[0]) if rows else None

    def select_orders(condition, params=(), order_by="id"):
        rows = db.query(f"SELECT {COLUMNS} FROM orders WHERE {condition} ORDER BY {order_by}",
                        params)
        return [row_to_order(row) for row in rows]

    def save_shares(order):
        db.query("UPDATE orders SET shares = ? WHERE id = ?",
                 (json.dumps(order["shares"], ensure_ascii=False), order["id"]))

    def find_group(code):
        rows = db.query(f"SELECT {GROUP_COLUMNS} FROM order_groups WHERE code = ?", (code,))
        return row_to_group(rows[0]) if rows else None

    def notify_all(order, message):
        for user in order["participants"]:
            events.publish(user, message)

    def set_status(order, status):
        db.query("UPDATE orders SET status = ? WHERE id = ?", (status, order["id"]))
        order["status"] = status
        notify_all(order, f"Замовлення №{order['id']} {STATUS_MESSAGES[status]}")
        if status in TRACKING_STATUS:
            payload = {"status": TRACKING_STATUS[status]}
            if status == "delivering":
                payload.update(
                    origin={"lat": order["restaurant_lat"], "lng": order["restaurant_lng"]},
                    destination={"lat": order["lat"], "lng": order["lng"]},
                    road_minutes=round(road_minutes(order["distance_km"]), 1),
                )
            tracking.update(bearer_header(), order["id"], payload)
        return order

    def can_view(order, user):
        role = user["role"]
        if role == "restaurant_staff":
            return order["restaurant"] == user.get("restaurant")
        return role in ("courier", "admin") or user["email"] in order["participants"]

    def priced(lines_data, user):
        lines, error = validate_lines(lines_data)
        if error:
            return None, None, error
        dishes = catalog.dishes([line["dish_id"] for line in lines])
        return price_lines(lines, dishes, user)

    def place_order(owner, items, restaurant, data, group_code=""):
        address, lat, lng, error = parse_location(data)
        if error:
            return None, error
        place = catalog.restaurant(restaurant)
        if place is None:
            return None, "restaurant not found"
        if place["overloaded"]:
            return None, f"ресторан «{restaurant}» тимчасово не приймає нових замовлень"
        distance = distance_km(place["lat"], place["lng"], lat, lng)
        if distance > MAX_DISTANCE_KM:
            return None, f"delivery is possible within {MAX_DISTANCE_KM} km of the restaurant"

        now = clock()
        active = select_orders("restaurant = ? AND status IN ('created', 'cooking')",
                               (restaurant,))
        eta = estimate_delivery_minutes(items, kitchen_load(active, restaurant, now), distance)
        scheduled_for, error = validate_schedule(data.get("scheduled_for"), now, eta)
        if error:
            return None, error

        shares = shares_of(items)
        participants = "," + ",".join(shares) + ","
        rows = db.query(
            f"INSERT INTO orders ({COLUMNS.replace('id, ', '', 1)}) VALUES"
            " (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (
                owner, participants, restaurant,
                json.dumps(items, ensure_ascii=False), json.dumps(shares, ensure_ascii=False),
                calculate_total(items), "awaiting_payment", address, lat, lng,
                place["lat"], place["lng"], distance, eta, now,
                scheduled_for or now + eta * 60, int(scheduled_for is not None), group_code,
            ),
        )
        order = find_order(rows[0][0])
        when = "на обраний час" if order["scheduled"] else f"орієнтовно за {eta} хв"
        for user, share in order["shares"].items():
            events.publish(user, f"Замовлення №{order['id']} створено, доставка {when}. "
                                 f"Ваша частка - {share['amount']:.2f} грн")
        return order, None

    @app.get("/health")
    def health():
        db.query("SELECT 1")
        return jsonify(status="ok", service="order")

    @app.post("/orders")
    @auth.require("client")
    def create_order():
        data = request.get_json(silent=True) or {}
        items, restaurant, error = priced(data.get("items"), g.user["email"])
        if error:
            return jsonify(error=error), 400
        order, error = place_order(g.user["email"], items, restaurant, data)
        if error:
            return jsonify(error=error), 400
        return jsonify(order), 201

    @app.post("/groups")
    @auth.require("client")
    def create_group():
        code = secrets.token_urlsafe(6)
        db.query(
            "INSERT INTO order_groups (code, owner, restaurant, items, status, created_at)"
            " VALUES (?, ?, '', '[]', 'open', ?)",
            (code, g.user["email"], clock()),
        )
        return jsonify(find_group(code)), 201

    @app.get("/groups/<code>")
    @auth.require("client")
    def get_group(code):
        group = find_group(code)
        if not group:
            return jsonify(error="group not found"), 404
        return jsonify(group)

    @app.put("/groups/<code>/items")
    @auth.require("client")
    def set_group_items(code):
        group = find_group(code)
        if not group:
            return jsonify(error="group not found"), 404
        if group["status"] != "open":
            return jsonify(error="this group order is already placed"), 409
        user = g.user["email"]
        others = [item for item in group["items"] if item["user"] != user]
        lines = (request.get_json(silent=True) or {}).get("items")
        mine, restaurant = [], group["restaurant"]
        if lines:
            mine, restaurant, error = priced(lines, user)
            if error:
                return jsonify(error=error), 400
            if others and group["restaurant"] and restaurant != group["restaurant"]:
                return jsonify(error=f"the group orders from «{group['restaurant']}»"), 400
        elif not others:
            restaurant = ""
        db.query("UPDATE order_groups SET items = ?, restaurant = ? WHERE code = ?",
                 (json.dumps(others + mine, ensure_ascii=False), restaurant, code))
        return jsonify(find_group(code))

    @app.post("/groups/<code>/checkout")
    @auth.require("client")
    def checkout_group(code):
        group = find_group(code)
        if not group:
            return jsonify(error="group not found"), 404
        if group["owner"] != g.user["email"]:
            return jsonify(error="only the group creator can place the order"), 403
        if group["status"] != "open":
            return jsonify(error="this group order is already placed"), 409
        if not group["items"]:
            return jsonify(error="the group cart is empty"), 400
        lines = [{"dish_id": item["dish_id"], "quantity": item["quantity"]}
                 for item in group["items"]]
        dishes = catalog.dishes(sorted({line["dish_id"] for line in lines}))
        items = []
        for item in group["items"]:
            fresh, _, error = price_lines(
                [{"dish_id": item["dish_id"], "quantity": item["quantity"]}], dishes, item["user"]
            )
            if error:
                return jsonify(error=error), 400
            items.extend(fresh)
        order, error = place_order(group["owner"], items, group["restaurant"],
                                   request.get_json(silent=True) or {}, code)
        if error:
            return jsonify(error=error), 400
        db.query("UPDATE order_groups SET status = 'ordered', order_id = ? WHERE code = ?",
                 (order["id"], code))
        return jsonify(order), 201

    @app.get("/orders")
    @auth.require()
    def list_orders():
        user = g.user
        role = user["role"]
        if role == "restaurant_staff":
            statuses = visible_statuses(role)
            marks = ", ".join("?" for _ in statuses)
            return jsonify(select_orders(f"restaurant = ? AND status IN ({marks})",
                                         (user.get("restaurant"), *statuses), "deliver_at"))
        if role == "courier":
            return jsonify(select_orders("status = 'delivering'", (), "deliver_at"))
        if role == "admin":
            return jsonify(select_orders("1 = 1", (), "id DESC")[:50])
        return jsonify(select_orders("participants LIKE ?", (f"%,{user['email']},%",),
                                     "id DESC"))

    @app.get("/orders/<int:order_id>")
    @auth.require()
    def get_order(order_id):
        order = find_order(order_id)
        if not order or not can_view(order, g.user):
            return jsonify(error="order not found"), 404
        return jsonify(order)

    def apply_payment(order, user, payment):
        share = order["shares"][user]
        share["status"] = payment["status"]
        share["method"] = payment.get("method")
        save_shares(order)
        if order["status"] == "awaiting_payment" and all_settled(order["shares"]):
            set_status(order, "created")
        return order

    def my_share(order_id):
        order = find_order(order_id)
        if not order or g.user["email"] not in order["shares"]:
            return None, (jsonify(error="order not found"), 404)
        return order, None

    @app.post("/orders/<int:order_id>/pay")
    @auth.require("client")
    def pay_share(order_id):
        order, failure = my_share(order_id)
        if failure:
            return failure
        if order["status"] != "awaiting_payment":
            return jsonify(error="this order does not wait for payment"), 409
        user = g.user["email"]
        method = (request.get_json(silent=True) or {}).get("method", "card")
        code, payment = payments.pay(bearer_header(), order_id, order["shares"][user]["amount"],
                                     method)
        if code not in (200, 201):
            return jsonify(error=(payment or {}).get("error", "payment failed")), code
        apply_payment(order, user, payment)
        return jsonify(order=order, checkout=payment.get("checkout")), 201

    @app.post("/orders/<int:order_id>/pay/check")
    @auth.require("client")
    def check_share(order_id):
        order, failure = my_share(order_id)
        if failure:
            return failure
        code, payment = payments.check(bearer_header(), order_id)
        if code != 200:
            return jsonify(error=(payment or {}).get("error", "payment check failed")), code
        if order["status"] == "awaiting_payment":
            apply_payment(order, g.user["email"], payment)
        return jsonify(order=order)

    @app.post("/orders/<int:order_id>/cancel")
    @auth.require("client")
    def cancel_order(order_id):
        order = find_order(order_id)
        if not order or g.user["email"] not in order["participants"]:
            return jsonify(error="order not found"), 404
        if order["owner"] != g.user["email"]:
            return jsonify(error="only the person who placed the order can cancel it"), 403
        if not can_cancel(order["status"]):
            return jsonify(error="order can no longer be cancelled"), 409
        if any(share["status"] != "unpaid" for share in order["shares"].values()):
            code, result = payments.refund(bearer_header(), order_id)
            if code != 200:
                return jsonify(error="refund failed, the order was not cancelled"), 502
            for payment in result["payments"]:
                if payment["user"] in order["shares"]:
                    order["shares"][payment["user"]]["status"] = payment["status"]
            save_shares(order)
        return jsonify(set_status(order, "cancelled"))

    @app.post("/orders/<int:order_id>/advance")
    @auth.require("restaurant_staff", "courier")
    def advance_order(order_id):
        order = find_order(order_id)
        if not order or not can_view(order, g.user):
            return jsonify(error="order not found"), 404
        if not can_advance(g.user["role"], order["status"]):
            return jsonify(error="this role cannot change the order now"), 409
        status = next_status(order["status"])
        if status == "delivered" and any(s["status"] == "cash_due"
                                         for s in order["shares"].values()):
            code, collected = payments.cash_received(bearer_header(), order_id)
            if code == 200:
                for payment in collected:
                    order["shares"][payment["user"]]["status"] = payment["status"]
                save_shares(order)
        return jsonify(set_status(order, status))

    app.extensions["db"] = db
    return app
