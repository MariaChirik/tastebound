import json
import logging
import os
import urllib.parse
import urllib.request

import redis
from flask import Flask, g, jsonify, request

from app.ranking import TOP_N, rank
from app.security import TokenAuth

SERVICE = "recommendation"
SUMS_KEY = "dish:score_sum"
COUNTS_KEY = "dish:score_count"

log = logging.getLogger(SERVICE)


def default_store():
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(url, decode_responses=True)


class HttpCatalog:

    def __init__(self, base_url, timeout=2):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def dishes(self, exclude_allergens=""):
        query = urllib.parse.urlencode({"exclude_allergens": exclude_allergens})
        with urllib.request.urlopen(f"{self._base_url}/dishes?{query}", timeout=self._timeout) as r:
            return json.load(r)


def create_app(store=None, catalog=None, auth=None):
    auth = auth or TokenAuth()
    store = store if store is not None else default_store()
    catalog = catalog if catalog is not None else HttpCatalog(
        os.environ.get("CATALOG_URL", "http://localhost:5000")
    )
    app = Flask(__name__)
    app.json.ensure_ascii = False

    @app.errorhandler(redis.RedisError)
    def storage_down(err):
        return jsonify(error="сховище даних тимчасово недоступне"), 503

    @app.get("/health")
    def health():
        store.ping()
        return jsonify(status="ok", service=SERVICE)

    @app.post("/ratings")
    @auth.require("client")
    def rate():
        data = request.get_json(silent=True) or {}
        user, dish, score = g.user["email"], data.get("dish"), data.get("score")
        valid_score = isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 5
        if not dish or not valid_score:
            return jsonify(error="оцінка має бути від 1 до 5"), 400
        key = f"ratings:{user}"
        previous = store.zscore(key, dish)
        store.zadd(key, {dish: score})
        store.hincrbyfloat(SUMS_KEY, dish, score - (previous or 0))
        if previous is None:
            store.hincrby(COUNTS_KEY, dish, 1)
        return jsonify(user=user, dish=dish, score=score), 201

    def own(user):
        return user == g.user["email"]

    @app.get("/ratings/<user>")
    @auth.require()
    def user_ratings(user):
        if not own(user):
            return jsonify(error="недостатньо прав для цієї дії"), 403
        return jsonify(user=user, ratings=dict(store.zrange(f"ratings:{user}", 0, -1,
                                                            withscores=True)))

    @app.get("/recommendations/<user>")
    @auth.require()
    def recommend(user):
        if not own(user):
            return jsonify(error="недостатньо прав для цієї дії"), 403
        excluded = request.args.get("exclude_allergens", "")
        try:
            dishes = catalog.dishes(excluded)
        except Exception as err:
            log.warning("Catalog недоступний: %s", err)
            return jsonify(user=user, dishes=[], available=False)
        ratings = dict(store.zrange(f"ratings:{user}", 0, -1, withscores=True))
        result = rank(dishes, ratings, store.hgetall(SUMS_KEY), store.hgetall(COUNTS_KEY), TOP_N)
        return jsonify(user=user, dishes=result, available=True)

    return app
