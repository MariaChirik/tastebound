from flask import Flask, jsonify, request

from app.data import SAMPLE_DISHES
from app.filters import filter_dishes, parse_list


def create_app():
    app = Flask(__name__)
    app.json.ensure_ascii = False

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="catalog")

    @app.get("/dishes")
    def dishes():
        excluded = parse_list(request.args.get("exclude_allergens"))
        diet = (request.args.get("diet") or "").strip().lower() or None
        return jsonify(filter_dishes(SAMPLE_DISHES, excluded, diet))

    return app
