from app import create_app
from app.logic import calculate_total, can_cancel, next_status, validate_items

ITEMS = [
    {"name": "Борщ", "price": 135.0, "quantity": 2},
    {"name": "Сирники", "price": 120.5, "quantity": 1},
]


def make_client():
    return create_app().test_client()


def test_health():
    assert make_client().get("/health").get_json()["service"] == "order"


def test_calculate_total():
    assert calculate_total(ITEMS) == 391


def test_validate_items_rejects_empty_list():
    assert validate_items([]) is not None


def test_validate_items_rejects_bad_quantity():
    assert validate_items([{"name": "Борщ", "price": 100, "quantity": 0}]) is not None


def test_validate_items_accepts_valid_items():
    assert validate_items(ITEMS) is None


def test_can_cancel_only_before_cooking():
    assert can_cancel("created") is True
    assert can_cancel("cooking") is False
    assert can_cancel("delivered") is False


def test_next_status_follows_flow():
    assert next_status("created") == "cooking"
    assert next_status("delivering") == "delivered"
    assert next_status("delivered") is None


def test_create_order_returns_total_and_status():
    response = make_client().post("/orders", json={"items": ITEMS})
    assert response.status_code == 201
    body = response.get_json()
    assert body["total"] == 390.5
    assert body["status"] == "created"


def test_create_order_rejects_invalid_items():
    assert make_client().post("/orders", json={"items": []}).status_code == 400


def test_get_unknown_order_returns_404():
    assert make_client().get("/orders/999").status_code == 404


def test_cancel_new_order():
    client = make_client()
    order_id = client.post("/orders", json={"items": ITEMS}).get_json()["id"]
    response = client.post(f"/orders/{order_id}/cancel")
    assert response.status_code == 200
    assert response.get_json()["status"] == "cancelled"


def test_cancel_order_that_is_already_cooking():
    app = create_app()
    client = app.test_client()
    order_id = client.post("/orders", json={"items": ITEMS}).get_json()["id"]
    app.extensions["orders"][order_id]["status"] = "cooking"
    assert client.post(f"/orders/{order_id}/cancel").status_code == 409
