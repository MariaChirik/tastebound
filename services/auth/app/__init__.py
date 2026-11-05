import os

from flask import Flask, jsonify, request
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

PUBLIC_ROLES = ("client", "restaurant_staff", "courier")
ALL_ROLES = PUBLIC_ROLES + ("admin",)
MIN_PASSWORD_LENGTH = 8


def validate_registration(email, password, role):
    if not email or "@" not in email:
        return "invalid email"
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return "password must be at least 8 characters"
    if role not in PUBLIC_ROLES:
        return "role must be one of: client, restaurant_staff, courier"
    return None


def create_app():
    app = Flask(__name__)
    secret = os.environ.get("AUTH_SECRET_KEY") or "local-development-only"
    signer = URLSafeTimedSerializer(secret)
    users = {}

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="auth")

    @app.post("/register")
    def register():
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        password = data.get("password")
        role = data.get("role")

        error = validate_registration(email, password, role)
        if error:
            return jsonify(error=error), 400
        if email in users:
            return jsonify(error="user already exists"), 409

        users[email] = {
            "password_hash": generate_password_hash(password),
            "role": role,
        }
        return jsonify(email=email, role=role), 201

    @app.post("/login")
    def login():
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        user = users.get(email)

        if not user or not check_password_hash(user["password_hash"], data.get("password") or ""):
            return jsonify(error="invalid credentials"), 401

        token = signer.dumps({"email": email, "role": user["role"]})
        return jsonify(token=token, role=user["role"])

    app.extensions["users"] = users
    return app
