import json
import logging
import os
import time

import redis
from flask import Flask, g, jsonify, request

from app.mailer import LogMailer
from app.security import TokenAuth

SERVICE = "notification"
QUEUE = "notifications:queue"
HISTORY_SIZE = 20

log = logging.getLogger(SERVICE)


def default_store():
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(url, decode_responses=True)


def history_key(user):
    return f"notifications:user:{user}"


def deliver(store, item, clock=time.time, mailer=None):
    user, message = item.split("|", 1)
    mailer = mailer or LogMailer()
    email_sent = False
    if "@" in user:
        try:
            mailer.send(user, message)
            email_sent = True
        except Exception as err:
            log.warning("email to %s failed: %s", user, err)
    entry = {"message": message, "at": clock()}
    store.lpush(history_key(user), json.dumps(entry, ensure_ascii=False))
    store.ltrim(history_key(user), 0, HISTORY_SIZE - 1)
    return {"user": user, "message": message, "email": email_sent}


def create_app(store=None, clock=time.time, auth=None, mailer=None):
    store = store if store is not None else default_store()
    auth = auth or TokenAuth()
    app = Flask(__name__)
    app.json.ensure_ascii = False

    @app.errorhandler(redis.RedisError)
    def storage_down(err):
        return jsonify(error="storage unavailable"), 503

    @app.get("/health")
    def health():
        store.ping()
        return jsonify(status="ok", service=SERVICE)

    @app.post("/notifications")
    @auth.require("admin")
    def enqueue():
        data = request.get_json(silent=True) or {}
        user, message = data.get("user"), data.get("message")
        if not user or not message:
            return jsonify(error="user and message are required"), 400
        store.rpush(QUEUE, f"{user}|{message}")
        return jsonify(queued=True, user=user), 202

    @app.post("/notifications/process")
    @auth.require("admin")
    def process():
        sent = []
        while (item := store.lpop(QUEUE)) is not None:
            sent.append(deliver(store, item, clock, mailer))
        return jsonify(sent=len(sent), items=sent)

    @app.get("/notifications/pending")
    @auth.require("admin")
    def pending():
        return jsonify(pending=store.llen(QUEUE))

    @app.get("/users/<user>")
    @auth.require()
    def history(user):
        if user != g.user["email"]:
            return jsonify(error="you can read only your own notifications"), 403
        items = [json.loads(raw) for raw in store.lrange(history_key(user), 0, HISTORY_SIZE - 1)]
        return jsonify(user=user, items=items)

    return app
