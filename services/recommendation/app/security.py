import functools
import os

from flask import g, jsonify, request
from itsdangerous import BadSignature, URLSafeTimedSerializer

TOKEN_MAX_AGE_SECONDS = 24 * 3600


class TokenAuth:
    def __init__(self, secret=None):
        secret = secret or os.environ.get("AUTH_SECRET_KEY") or "local-development-only"
        self.signer = URLSafeTimedSerializer(secret)

    def current_user(self):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        try:
            return self.signer.loads(header[len("Bearer "):], max_age=TOKEN_MAX_AGE_SECONDS)
        except BadSignature:
            return None

    def require(self, *roles):

        def decorator(view):
            @functools.wraps(view)
            def wrapper(*args, **kwargs):
                user = self.current_user()
                if user is None:
                    return jsonify(error="потрібно увійти в акаунт"), 401
                if roles and user.get("role") not in roles:
                    return jsonify(error="недостатньо прав для цієї дії"), 403
                g.user = user
                return view(*args, **kwargs)

            return wrapper

        return decorator


def bearer_header():
    return request.headers.get("Authorization", "")
