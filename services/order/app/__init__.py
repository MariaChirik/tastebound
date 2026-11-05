from flask import Flask, jsonify, request

from app.logic import calculate_total, can_cancel, validate_items


def create_app():
    app = Flask(__name__)
    orders = {}

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="order")

    @app.post("/orders")
    def create_order():
        data = request.get_json(silent=True) or {}
        items = data.get("items")
        error = validate_items(items)
        if error:
            return jsonify(error=error), 400

        order_id = len(orders) + 1
        orders[order_id] = {
            "id": order_id,
            "items": items,
            "total": calculate_total(items),
            "status": "created",
        }
        return jsonify(orders[order_id]), 201

    @app.get("/orders/<int:order_id>")
    def get_order(order_id):
        order = orders.get(order_id)
        if not order:
            return jsonify(error="order not found"), 404
        return jsonify(order)

    @app.post("/orders/<int:order_id>/cancel")
    def cancel_order(order_id):
        order = orders.get(order_id)
        if not order:
            return jsonify(error="order not found"), 404
        if not can_cancel(order["status"]):
            return jsonify(error="order can no longer be cancelled"), 409
        order["status"] = "cancelled"
        return jsonify(order)

    app.extensions["orders"] = orders
    return app
