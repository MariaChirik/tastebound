import json
import os

from flask import Flask, g, jsonify, request

from app.data import RESTAURANTS, SAMPLE_DISHES
from app.db import connect
from app.filters import filter_dishes, parse_list, validate_dish
from app.security import TokenAuth

ID_COLUMN = {
    "sqlite": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "postgres": "SERIAL PRIMARY KEY",
}
DISH_COLUMNS = "id, name, restaurant, composition, price, allergens, diets, available, hidden"


def schema(dialect):
    return [
        """
        CREATE TABLE IF NOT EXISTS restaurants (
            name TEXT PRIMARY KEY,
            lat DOUBLE PRECISION NOT NULL,
            lng DOUBLE PRECISION NOT NULL,
            overloaded INTEGER NOT NULL DEFAULT 0
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS dishes (
            id {ID_COLUMN[dialect]},
            name TEXT NOT NULL,
            restaurant TEXT NOT NULL,
            composition TEXT NOT NULL DEFAULT '',
            price DOUBLE PRECISION NOT NULL,
            allergens TEXT NOT NULL,
            diets TEXT NOT NULL,
            available INTEGER NOT NULL DEFAULT 1,
            hidden INTEGER NOT NULL DEFAULT 0
        )
        """,
    ]


def create_app(db=None, auth=None):
    app = Flask(__name__)
    app.json.ensure_ascii = False
    auth = auth or TokenAuth()
    db = db if db is not None else connect(os.environ.get("DATABASE_URL"))
    for statement in schema(db.dialect):
        db.query(statement)
    seed(db)

    def restaurants():
        rows = db.query("SELECT name, lat, lng, overloaded FROM restaurants ORDER BY name")
        return {
            name: {"name": name, "lat": lat, "lng": lng, "overloaded": bool(overloaded)}
            for name, lat, lng, overloaded in rows
        }

    def to_dish(row, overloaded):
        dish = dict(zip(DISH_COLUMNS.split(", "), row))
        dish["allergens"] = json.loads(dish["allergens"])
        dish["diets"] = json.loads(dish["diets"])
        dish["available"] = bool(dish["available"])
        dish["hidden"] = bool(dish["hidden"])
        dish["restaurant_overloaded"] = bool(overloaded)
        dish["orderable"] = dish["available"] and not dish["hidden"] and not overloaded
        return dish

    def dishes_where(condition="1 = 1", params=()):
        places = restaurants()
        rows = db.query(f"SELECT {DISH_COLUMNS} FROM dishes WHERE {condition} ORDER BY id", params)
        return [
            to_dish(row, places.get(row[2], {}).get("overloaded", False)) for row in rows
        ]

    def find_dish(dish_id):
        found = dishes_where("id = ?", (dish_id,))
        return found[0] if found else None

    def own_dish(dish_id):
        dish = find_dish(dish_id)
        if dish and dish["restaurant"] == g.user.get("restaurant"):
            return dish
        return None

    @app.get("/health")
    def health():
        db.query("SELECT 1")
        return jsonify(status="ok", service="catalog")

    @app.get("/dishes")
    def dishes():
        ids = parse_list(request.args.get("ids"))
        if ids:
            numbers = [int(value) for value in ids if value.isdigit()]
            if not numbers:
                return jsonify([])
            marks = ", ".join("?" for _ in numbers)
            return jsonify(dishes_where(f"id IN ({marks})", tuple(numbers)))

        excluded = parse_list(request.args.get("exclude_allergens"))
        diet = (request.args.get("diet") or "").strip().lower() or None
        visible = dishes_where("available = 1 AND hidden = 0")
        return jsonify(filter_dishes(visible, excluded, diet))

    @app.get("/restaurants")
    def list_restaurants():
        return jsonify(list(restaurants().values()))

    @app.get("/menu")
    @auth.require("restaurant_staff")
    def menu():
        place = restaurants().get(g.user.get("restaurant"))
        if not place:
            return jsonify(error="ресторан не знайдено"), 404
        dishes = dishes_where("restaurant = ?", (place["name"],))
        return jsonify(restaurant=place, dishes=dishes)

    @app.post("/menu")
    @auth.require("restaurant_staff")
    def add_dish():
        restaurant = g.user.get("restaurant")
        if restaurant not in restaurants():
            return jsonify(error="ресторан не знайдено"), 404
        fields, error = validate_dish(request.get_json(silent=True) or {})
        if error:
            return jsonify(error=error), 400
        rows = db.query(
            "INSERT INTO dishes (name, restaurant, composition, price, allergens, diets,"
            " available, hidden) VALUES (?, ?, ?, ?, ?, ?, 1, 0) RETURNING id",
            (fields["name"], restaurant, fields["composition"], fields["price"],
             json.dumps(fields["allergens"]), json.dumps(fields["diets"])),
        )
        return jsonify(find_dish(rows[0][0])), 201

    @app.patch("/menu/<int:dish_id>")
    @auth.require("restaurant_staff")
    def update_dish(dish_id):
        if not own_dish(dish_id):
            return jsonify(error="страву не знайдено"), 404
        data = request.get_json(silent=True) or {}
        fields, error = validate_dish(data, partial=True)
        if error:
            return jsonify(error=error), 400
        if "available" in data:
            if not isinstance(data["available"], bool):
                return jsonify(error="некоректне значення наявності"), 400
            fields["available"] = int(data["available"])
        for key in ("allergens", "diets"):
            if key in fields:
                fields[key] = json.dumps(fields[key])
        if fields:
            assignments = ", ".join(f"{key} = ?" for key in fields)
            db.query(f"UPDATE dishes SET {assignments} WHERE id = ?",
                     (*fields.values(), dish_id))
        return jsonify(find_dish(dish_id))

    @app.post("/menu/overload")
    @auth.require("restaurant_staff")
    def set_overload():
        value = (request.get_json(silent=True) or {}).get("overloaded")
        if not isinstance(value, bool):
            return jsonify(error="некоректне значення режиму перевантаження"), 400
        restaurant = g.user.get("restaurant")
        if restaurant not in restaurants():
            return jsonify(error="ресторан не знайдено"), 404
        db.query("UPDATE restaurants SET overloaded = ? WHERE name = ?", (int(value), restaurant))
        return jsonify(restaurants()[restaurant])

    @app.get("/admin/dishes")
    @auth.require("admin")
    def all_dishes():
        return jsonify(dishes_where())

    @app.post("/admin/dishes/<int:dish_id>/hidden")
    @auth.require("admin")
    def hide_dish(dish_id):
        value = (request.get_json(silent=True) or {}).get("hidden")
        if not isinstance(value, bool):
            return jsonify(error="некоректне значення"), 400
        if not find_dish(dish_id):
            return jsonify(error="страву не знайдено"), 404
        db.query("UPDATE dishes SET hidden = ? WHERE id = ?", (int(value), dish_id))
        return jsonify(find_dish(dish_id))

    app.extensions["db"] = db
    return app


def seed(db):
    if not db.query("SELECT name FROM restaurants"):
        for place in RESTAURANTS:
            db.query("INSERT INTO restaurants (name, lat, lng, overloaded) VALUES (?, ?, ?, 0)",
                     (place["name"], place["lat"], place["lng"]))
    if not db.query("SELECT id FROM dishes"):
        for dish in SAMPLE_DISHES:
            db.query(
                "INSERT INTO dishes (name, restaurant, composition, price, allergens, diets,"
                " available, hidden) VALUES (?, ?, ?, ?, ?, ?, 1, 0)",
                (dish["name"], dish["restaurant"], dish["composition"], dish["price"],
                 json.dumps(dish["allergens"]), json.dumps(dish["diets"])),
            )
