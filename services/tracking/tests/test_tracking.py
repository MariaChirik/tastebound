from fake_redis import FakeRedis
from itsdangerous import URLSafeTimedSerializer

from app import create_app, interpolate
from app.security import TokenAuth

SECRET = "test-secret"
ROUTE = {
    "status": "on_the_way",
    "origin": {"lat": 50.0, "lng": 30.0},
    "destination": {"lat": 50.1, "lng": 30.2},
    "road_minutes": 10,
}


def headers(role="client"):
    token = URLSafeTimedSerializer(SECRET).dumps({"email": f"{role}@x.ua", "role": role})
    return {"Authorization": f"Bearer {token}"}


CLIENT, COURIER = headers(), headers("courier")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(store=None):
    clock = Clock()
    app = create_app(store=store or FakeRedis(), auth=TokenAuth(SECRET), clock=clock)
    return app.test_client(), clock


def test_health_returns_503_when_redis_is_down():
    client, _ = make(FakeRedis(down=True))
    assert client.get("/health").status_code == 503


def test_status_needs_login_and_valid_value():
    client, _ = make()
    assert client.post("/orders/1/status", json={"status": "cooking"}).status_code == 401
    assert client.post("/orders/1/status", json={"status": "lost"},
                       headers=CLIENT).status_code == 400
    client.post("/orders/1/status", json={"status": "cooking"}, headers=CLIENT)
    assert client.get("/orders/1/status", headers=CLIENT).get_json()["status"] == "cooking"


def test_unknown_order_returns_404():
    client, _ = make()
    assert client.get("/orders/9/status", headers=CLIENT).status_code == 404
    assert client.get("/orders/9/location", headers=CLIENT).status_code == 404


def test_no_courier_before_order_is_on_the_way():
    client, _ = make()
    client.post("/orders/1/status", json={"status": "cooking"}, headers=CLIENT)
    assert client.get("/orders/1/location", headers=CLIENT).get_json()["courier"] is None


def test_route_requires_points_and_time():
    client, _ = make()
    assert client.post("/orders/1/status", json={"status": "on_the_way"},
                       headers=CLIENT).status_code == 400


def test_estimated_position_moves_along_the_route():
    client, clock = make()
    client.post("/orders/1/status", json=ROUTE, headers=CLIENT)
    start = client.get("/orders/1/location", headers=CLIENT).get_json()["courier"]
    assert start == {"lat": 50.0, "lng": 30.0, "source": "estimate"}
    clock.now += 300  # половина дороги
    middle = client.get("/orders/1/location", headers=CLIENT).get_json()["courier"]
    assert middle == {"lat": 50.05, "lng": 30.1, "source": "estimate"}
    clock.now += 3000
    end = client.get("/orders/1/location", headers=CLIENT).get_json()["courier"]
    assert (end["lat"], end["lng"]) == (50.1, 30.2)


def test_fresh_gps_from_courier_is_preferred():
    client, clock = make()
    client.post("/orders/1/status", json=ROUTE, headers=CLIENT)
    assert client.post("/orders/1/location", json={"lat": 50.02, "lng": 30.03},
                       headers=CLIENT).status_code == 403
    client.post("/orders/1/location", json={"lat": 50.02, "lng": 30.03}, headers=COURIER)
    gps = client.get("/orders/1/location", headers=CLIENT).get_json()["courier"]
    assert gps == {"lat": 50.02, "lng": 30.03, "source": "gps"}
    clock.now += 60  # телефон давно не оновлювався
    assert client.get("/orders/1/location",
                      headers=CLIENT).get_json()["courier"]["source"] == "estimate"


def test_location_only_while_on_the_way():
    client, _ = make()
    client.post("/orders/1/status", json={"status": "cooking"}, headers=CLIENT)
    response = client.post("/orders/1/location", json={"lat": 1, "lng": 2}, headers=COURIER)
    assert response.status_code == 409


def test_delivered_order_shows_courier_at_destination():
    client, _ = make()
    client.post("/orders/1/status", json=ROUTE, headers=CLIENT)
    client.post("/orders/1/status", json={"status": "delivered"}, headers=CLIENT)
    courier = client.get("/orders/1/location", headers=CLIENT).get_json()["courier"]
    assert courier == {"lat": 50.1, "lng": 30.2, "source": "delivered"}


def test_interpolate_is_clamped():
    a, b = {"lat": 0, "lng": 0}, {"lat": 10, "lng": 10}
    assert interpolate(a, b, -1) == {"lat": 0, "lng": 0}
    assert interpolate(a, b, 2) == {"lat": 10, "lng": 10}
