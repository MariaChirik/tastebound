import functools
import logging
import os

from flask import Flask, g, jsonify, request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import connect

PUBLIC_ROLES = ("client", "restaurant_staff", "courier")
ALL_ROLES = PUBLIC_ROLES + ("admin",)
ROLES_NEEDING_APPROVAL = ("restaurant_staff", "courier")
MIN_PASSWORD_LENGTH = 8
TOKEN_MAX_AGE_SECONDS = 24 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    restaurant TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
)
"""
USER_STATUSES = ("active", "pending", "blocked")

log = logging.getLogger("auth")


def validate_registration(email, password, role, restaurant=""):
    if not email or "@" not in email:
        return "invalid email"
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return "password must be at least 8 characters"
    if role not in PUBLIC_ROLES:
        return "role must be one of: client, restaurant_staff, courier"
    if role == "restaurant_staff" and not restaurant:
        return "restaurant staff must choose a restaurant"
    return None


def create_app(db=None, secret=None, admin_email=None, admin_password=None):
    app = Flask(__name__)
    app.json.ensure_ascii = False
    secret = secret or os.environ.get("AUTH_SECRET_KEY") or "local-development-only"
    signer = URLSafeTimedSerializer(secret)
    db = db if db is not None else connect(os.environ.get("DATABASE_URL"))
    db.query(SCHEMA)

    def find_user(email):
        rows = db.query(
            "SELECT email, password_hash, role, restaurant, status FROM users WHERE email = ?",
            (email,),
        )
        if not rows:
            return None
        keys = ("email", "password_hash", "role", "restaurant", "status")
        return dict(zip(keys, rows[0]))

    admin_email = (admin_email or os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    admin_password = admin_password or os.environ.get("ADMIN_PASSWORD") or ""
    if admin_email and len(admin_password) >= MIN_PASSWORD_LENGTH and not find_user(admin_email):
        db.query(
            "INSERT INTO users (email, password_hash, role, restaurant, status)"
            " VALUES (?, ?, 'admin', '', 'active')",
            (admin_email, generate_password_hash(admin_password)),
        )
        log.info("admin account %s created", admin_email)

    def require_admin(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            try:
                user = signer.loads(header.removeprefix("Bearer "), max_age=TOKEN_MAX_AGE_SECONDS)
            except BadSignature:
                return jsonify(error="authentication required"), 401
            if user.get("role") != "admin":
                return jsonify(error="forbidden for this role"), 403
            g.user = user
            return view(*args, **kwargs)

        return wrapper

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="auth")

    @app.post("/register")
    def register():
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        password = data.get("password")
        role = data.get("role")
        restaurant = (data.get("restaurant") or "").strip() if role == "restaurant_staff" else ""

        error = validate_registration(email, password, role, restaurant)
        if error:
            return jsonify(error=error), 400
        if find_user(email):
            return jsonify(error="user already exists"), 409

        status = "pending" if role in ROLES_NEEDING_APPROVAL else "active"
        db.query(
            "INSERT INTO users (email, password_hash, role, restaurant, status)"
            " VALUES (?, ?, ?, ?, ?)",
            (email, generate_password_hash(password), role, restaurant, status),
        )
        return jsonify(email=email, role=role, restaurant=restaurant, status=status), 201

    @app.post("/login")
    def login():
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        user = find_user(email)

        if not user or not check_password_hash(user["password_hash"], data.get("password") or ""):
            return jsonify(error="invalid credentials"), 401
        if user["status"] == "pending":
            return jsonify(error="account is waiting for administrator approval"), 403
        if user["status"] == "blocked":
            return jsonify(error="account is blocked"), 403

        claims = {"email": email, "role": user["role"], "restaurant": user["restaurant"]}
        return jsonify(token=signer.dumps(claims), role=user["role"],
                       restaurant=user["restaurant"])

    @app.get("/users")
    @require_admin
    def list_users():
        rows = db.query("SELECT email, role, restaurant, status FROM users ORDER BY email")
        keys = ("email", "role", "restaurant", "status")
        return jsonify([dict(zip(keys, row)) for row in rows])

    @app.post("/users/<email>/status")
    @require_admin
    def set_user_status(email):
        status = (request.get_json(silent=True) or {}).get("status")
        if status not in USER_STATUSES:
            return jsonify(error=f"status must be one of {USER_STATUSES}"), 400
        user = find_user(email.strip().lower())
        if not user:
            return jsonify(error="user not found"), 404
        if user["role"] == "admin":
            return jsonify(error="administrator status cannot be changed"), 409
        db.query("UPDATE users SET status = ? WHERE email = ?", (status, user["email"]))
        return jsonify(email=user["email"], role=user["role"], restaurant=user["restaurant"],
                       status=status)

    app.extensions["db"] = db
    app.extensions["signer"] = signer
    return app
