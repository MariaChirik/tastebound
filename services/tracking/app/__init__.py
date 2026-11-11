import os
import time

import redis
from flask import Flask, jsonify, request

from app.security import TokenAuth

SERVICE = "tracking"
ORDER_STATUSES = ("accepted", "cooking", "on_the_way", "delivered")
ORDER_TTL_SECONDS = 24 * 3600
GPS_FRESH_SECONDS = 30


def default_store():
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(url, decode_responses=True)


def is_point(value):
    return (isinstance(value, dict)
            and all(isinstance(value.get(k), (int, float)) and not isinstance(value.get(k), bool)
                    for k in ("lat", "lng")))


def interpolate(origin, destination, progress):
    progress = max(0.0, min(1.0, progress))
    return {
        "lat": round(origin["lat"] + (destination["lat"] - origin["lat"]) * progress, 6),
        "lng": round(origin["lng"] + (destination["lng"] - origin["lng"]) * progress, 6),
    }


def create_app(store=None, auth=None, clock=time.time):
    store = store if store is not None else default_store()
    auth = auth or TokenAuth()
    app = Flask(__name__)

    @app.errorhandler(redis.RedisError)
    def storage_down(err):
        return jsonify(error="storage unavailable"), 503

    @app.get("/health")
    def health():
        store.ping()
        return jsonify(status="ok", service=SERVICE)

    def key(order_id):
        return f"order:{order_id}"

    @app.post("/orders/<order_id>/status")
    @auth.require()
    def set_status(order_id):
        data = request.get_json(silent=True) or {}
        status = data.get("status")
        if status not in ORDER_STATUSES:
            return jsonify(error=f"status must be one of {ORDER_STATUSES}"), 400
        fields = {"status": status}
        if status == "on_the_way":
            origin, destination = data.get("origin"), data.get("destination")
            minutes = data.get("road_minutes")
            if not is_point(origin) or not is_point(destination) \
                    or not isinstance(minutes, (int, float)) or minutes <= 0:
                return jsonify(error="origin, destination and road_minutes are required"), 400
            fields.update(origin_lat=origin["lat"], origin_lng=origin["lng"],
                          dest_lat=destination["lat"], dest_lng=destination["lng"],
                          road_minutes=minutes, started_at=clock())
        store.hset(key(order_id), mapping=fields)
        store.expire(key(order_id), ORDER_TTL_SECONDS)
        return jsonify(order_id=order_id, status=status)

    @app.get("/orders/<order_id>/status")
    @auth.require()
    def get_status(order_id):
        status = store.hget(key(order_id), "status")
        if status is None:
            return jsonify(error="order not found"), 404
        return jsonify(order_id=order_id, status=status)

    @app.post("/orders/<order_id>/location")
    @auth.require("courier")
    def set_location(order_id):
        data = request.get_json(silent=True) or {}
        if not is_point(data):
            return jsonify(error="numeric lat and lng are required"), 400
        if store.hget(key(order_id), "status") != "on_the_way":
            return jsonify(error="order is not on the way"), 409
        store.hset(key(order_id), mapping={"gps_lat": data["lat"], "gps_lng": data["lng"],
                                           "gps_at": clock()})
        return jsonify(order_id=order_id, lat=data["lat"], lng=data["lng"])

    @app.get("/orders/<order_id>/location")
    @auth.require()
    def get_location(order_id):
        info = store.hgetall(key(order_id))
        if not info:
            return jsonify(error="order not found"), 404
        result = {"order_id": order_id, "status": info["status"], "courier": None}
        if "origin_lat" not in info:
            return jsonify(result)
        origin = {"lat": float(info["origin_lat"]), "lng": float(info["origin_lng"])}
        destination = {"lat": float(info["dest_lat"]), "lng": float(info["dest_lng"])}
        result.update(origin=origin, destination=destination)
        if info["status"] == "delivered":
            result["courier"] = {**destination, "source": "delivered"}
        elif "gps_at" in info and clock() - float(info["gps_at"]) <= GPS_FRESH_SECONDS:
            result["courier"] = {"lat": float(info["gps_lat"]), "lng": float(info["gps_lng"]),
                                 "source": "gps"}
        else:
            elapsed = clock() - float(info["started_at"])
            progress = elapsed / (float(info["road_minutes"]) * 60)
            result["courier"] = {**interpolate(origin, destination, progress),
                                 "source": "estimate"}
        return jsonify(result)

    return app
