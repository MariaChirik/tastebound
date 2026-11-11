import pytest
from itsdangerous import URLSafeTimedSerializer

from app import create_app
from app.logic import (
    distance_km,
    estimate_delivery_minutes,
    kitchen_load,
    next_status,
    shares_of,
    validate_lines,
    validate_schedule,
)
from app.security import TokenAuth

SECRET = "test-secret"
NOW = 1_800_000_000.0
# ~3 км від ресторану «Хата»
HOME = {"address": "вул. Велика Васильківська, 100", "lat": 50.4231, "lng": 30.5195}


def headers(email, role="client", restaurant=""):
    token = URLSafeTimedSerializer(SECRET).dumps(
        {"email": email, "role": role, "restaurant": restaurant}
    )
    return {"Authorization": f"Bearer {token}"}


ANN = headers("ann@example.com")
BOB = headers("bob@example.com")
CHEF = headers("chef@hata.ua", "restaurant_staff", "Хата")
OTHER_CHEF = headers("chef@wok.ua", "restaurant_staff", "Wok Kyiv")
COURIER = headers("courier@example.com", "courier")


class FakeCatalog:
    def __init__(self):
        self.items = {
            1: {"id": 1, "name": "Борщ", "restaurant": "Хата", "price": 135.0, "orderable": True},
            4: {"id": 4, "name": "Сирники", "restaurant": "Хата", "price": 120.0,
                "orderable": True},
            5: {"id": 5, "name": "Паста", "restaurant": "Wok Kyiv", "price": 190.0,
                "orderable": True},
        }
        self.places = {
            "Хата": {"name": "Хата", "lat": 50.4501, "lng": 30.5234, "overloaded": False},
            "Wok Kyiv": {"name": "Wok Kyiv", "lat": 50.4370, "lng": 30.5160, "overloaded": False},
        }

    def dishes(self, ids):
        return [self.items[i] for i in ids if i in self.items]

    def restaurant(self, name):
        return self.places.get(name)


class FakePayments:

    def __init__(self):
        self.calls = []

    def pay(self, auth_header, order_id, amount, method):
        self.calls.append(("pay", order_id, amount, method))
        status = "cash_due" if method == "cash" else "paid"
        return 201, {"status": status, "method": method}

    def check(self, auth_header, order_id):
        return 200, {"status": "paid", "method": "card"}

    def refund(self, auth_header, order_id):
        self.calls.append(("refund", order_id))
        return 200, {"payments": [{"user": "ann@example.com", "status": "refunded"}]}

    def cash_received(self, auth_header, order_id):
        self.calls.append(("cash", order_id))
        return 200, [{"user": "ann@example.com", "status": "paid"}]


class Recorder:
    def __init__(self):
        self.events = []
        self.updates = []

    def publish(self, user, message):
        self.events.append((user, message))

    def update(self, auth_header, order_id, payload):
        self.updates.append((order_id, payload))


@pytest.fixture
def env():
    recorder, catalog, payments = Recorder(), FakeCatalog(), FakePayments()
    app = create_app(events=recorder, tracking=recorder, catalog=catalog, payments=payments,
                     auth=TokenAuth(SECRET), clock=lambda: NOW)
    return app.test_client(), recorder, catalog, payments


def place(client, items=None, who=ANN, **extra):
    body = {"items": items or [{"dish_id": 1, "quantity": 2}], **HOME, **extra}
    return client.post("/orders", json=body, headers=who)


def paid_order(client, method="card"):
    order_id = place(client).get_json()["id"]
    client.post(f"/orders/{order_id}/pay", json={"method": method}, headers=ANN)
    return order_id


def test_lines_are_merged_and_validated():
    lines, error = validate_lines([{"dish_id": 1, "quantity": 1}, {"dish_id": 1, "quantity": 2}])
    assert error is None and lines == [{"dish_id": 1, "quantity": 3}]
    assert validate_lines([])[1]
    assert validate_lines([{"dish_id": "1", "quantity": 1}])[1]
    assert validate_lines([{"dish_id": 1, "quantity": 0}])[1]
    assert validate_lines([{"dish_id": 1, "quantity": True}])[1]


def test_distance_between_two_points():
    assert distance_km(50.4501, 30.5234, 50.4501, 30.5234) == 0
    assert 2.9 < distance_km(50.4501, 30.5234, HOME["lat"], HOME["lng"]) < 3.2


def test_delivery_time_counts_cooking_queue_and_road():
    items = [{"quantity": 2}]
    assert estimate_delivery_minutes(items, 0, 3.0) == 31
    assert estimate_delivery_minutes(items, 2, 3.0) == 39


def test_kitchen_load_counts_only_near_orders_of_same_restaurant():
    orders = [
        {"restaurant": "Хата", "status": "cooking", "deliver_at": NOW + 600},
        {"restaurant": "Хата", "status": "created", "deliver_at": NOW + 10 * 3600},
        {"restaurant": "Хата", "status": "delivering", "deliver_at": NOW + 600},
        {"restaurant": "Wok Kyiv", "status": "cooking", "deliver_at": NOW + 600},
    ]
    assert kitchen_load(orders, "Хата", NOW) == 1


def test_schedule_must_leave_time_for_delivery():
    assert validate_schedule(None, NOW, 30) == (None, None)
    assert validate_schedule(NOW + 3600, NOW, 30) == (NOW + 3600, None)
    assert validate_schedule(NOW + 600, NOW, 30)[1]
    assert validate_schedule(NOW + 8 * 24 * 3600, NOW, 30)[1]


def test_shares_split_by_participant():
    items = [
        {"user": "a", "price": 100.0, "quantity": 2},
        {"user": "b", "price": 50.0, "quantity": 1},
        {"user": "a", "price": 10.0, "quantity": 1},
    ]
    shares = shares_of(items)
    assert {user: share["amount"] for user, share in shares.items()} == {"a": 210.0, "b": 50.0}


def test_status_flow():
    assert next_status("awaiting_payment") == "created"
    assert next_status("delivering") == "delivered"
    assert next_status("delivered") is None


def test_order_prices_come_from_catalog_not_from_browser(env):
    client, *_ = env
    body = {"items": [{"dish_id": 1, "quantity": 2, "price": 1}], **HOME}
    order = client.post("/orders", json=body, headers=ANN).get_json()
    assert order["total"] == 270.0
    assert order["status"] == "awaiting_payment"
    assert order["restaurant"] == "Хата"
    assert order["shares"] == {"ann@example.com": {"amount": 270.0, "status": "unpaid",
                                                   "method": None}}


def test_eta_uses_real_distance_to_address(env):
    client, *_ = env
    order = place(client).get_json()
    assert 2.9 < order["distance_km"] < 3.2
    assert order["eta_minutes"] == 32
    assert order["deliver_at"] == NOW + 32 * 60


def test_order_needs_address_and_point_on_map(env):
    client, *_ = env
    response = client.post("/orders", json={"items": [{"dish_id": 1, "quantity": 1}]},
                           headers=ANN)
    assert response.status_code == 400
    far = place(client, lat=49.84, lng=24.03)  # Львів
    assert far.status_code == 400


def test_one_order_from_one_restaurant(env):
    client, *_ = env
    response = place(client, [{"dish_id": 1, "quantity": 1}, {"dish_id": 5, "quantity": 1}])
    assert response.status_code == 400


def test_stop_list_and_overload_block_new_orders(env):
    client, _, catalog, _ = env
    catalog.items[1]["orderable"] = False
    assert place(client).status_code == 400
    catalog.items[1].update(orderable=False, restaurant_overloaded=True)
    response = place(client)
    assert response.status_code == 400
    assert "не приймає" in response.get_json()["error"]


def test_scheduled_order_keeps_chosen_time(env):
    client, *_ = env
    order = place(client, scheduled_for=NOW + 4 * 3600).get_json()
    assert order["scheduled"] is True
    assert order["deliver_at"] == NOW + 4 * 3600
    assert place(client, scheduled_for=NOW + 60).status_code == 400


def test_only_clients_place_orders(env):
    client, *_ = env
    assert place(client, who=CHEF).status_code == 403
    assert client.post("/orders", json={}).status_code == 401


def test_restaurant_sees_order_only_after_payment(env):
    client, recorder, _, payments = env
    order_id = place(client).get_json()["id"]
    assert client.get("/orders", headers=CHEF).get_json() == []

    result = client.post(f"/orders/{order_id}/pay", json={"method": "card"}, headers=ANN)
    assert result.status_code == 201
    assert result.get_json()["order"]["status"] == "created"
    assert payments.calls == [("pay", order_id, 270.0, "card")]
    assert [o["id"] for o in client.get("/orders", headers=CHEF).get_json()] == [order_id]
    assert client.get("/orders", headers=OTHER_CHEF).get_json() == []
    assert (order_id, {"status": "accepted"}) in recorder.updates


def test_cash_is_collected_by_courier_on_delivery(env):
    client, _, _, payments = env
    order_id = paid_order(client, method="cash")
    order = client.get(f"/orders/{order_id}", headers=ANN).get_json()
    assert order["status"] == "created"
    assert order["shares"]["ann@example.com"]["status"] == "cash_due"

    client.post(f"/orders/{order_id}/advance", headers=CHEF)
    client.post(f"/orders/{order_id}/advance", headers=CHEF)
    done = client.post(f"/orders/{order_id}/advance", headers=COURIER).get_json()
    assert done["status"] == "delivered"
    assert done["shares"]["ann@example.com"]["status"] == "paid"
    assert ("cash", order_id) in payments.calls


def test_paying_twice_is_rejected(env):
    client, *_ = env
    order_id = paid_order(client)
    again = client.post(f"/orders/{order_id}/pay", json={"method": "card"}, headers=ANN)
    assert again.status_code == 409


def test_strangers_cannot_pay_or_see_order(env):
    client, *_ = env
    order_id = place(client).get_json()["id"]
    assert client.post(f"/orders/{order_id}/pay", json={}, headers=BOB).status_code == 404
    assert client.get(f"/orders/{order_id}", headers=BOB).status_code == 404
    assert client.get(f"/orders/{order_id}", headers=OTHER_CHEF).status_code == 404


def test_cancel_before_cooking_refunds_automatically(env):
    client, recorder, _, payments = env
    order_id = paid_order(client)
    response = client.post(f"/orders/{order_id}/cancel", headers=ANN)
    assert response.get_json()["status"] == "cancelled"
    assert response.get_json()["shares"]["ann@example.com"]["status"] == "refunded"
    assert ("refund", order_id) in payments.calls
    assert ("ann@example.com", f"Замовлення №{order_id} скасовано") in recorder.events


def test_unpaid_order_is_cancelled_without_refund(env):
    client, _, _, payments = env
    order_id = place(client).get_json()["id"]
    assert client.post(f"/orders/{order_id}/cancel", headers=ANN).status_code == 200
    assert payments.calls == []


def test_cannot_cancel_after_cooking_started(env):
    client, *_ = env
    order_id = paid_order(client)
    client.post(f"/orders/{order_id}/advance", headers=CHEF)
    assert client.post(f"/orders/{order_id}/cancel", headers=ANN).status_code == 409


def test_full_lifecycle_with_route_for_tracking(env):
    client, recorder, *_ = env
    order_id = paid_order(client)
    assert client.post(f"/orders/{order_id}/advance", headers=COURIER).status_code == 409
    assert client.post(f"/orders/{order_id}/advance", headers=OTHER_CHEF).status_code == 404
    assert client.post(f"/orders/{order_id}/advance",
                       headers=CHEF).get_json()["status"] == "cooking"
    assert client.post(f"/orders/{order_id}/advance",
                       headers=CHEF).get_json()["status"] == "delivering"
    courier_orders = client.get("/orders", headers=COURIER).get_json()
    assert [order["id"] for order in courier_orders] == [order_id]
    route = recorder.updates[-1][1]
    assert route["status"] == "on_the_way"
    assert route["origin"] == {"lat": 50.4501, "lng": 30.5234}
    assert route["destination"] == {"lat": HOME["lat"], "lng": HOME["lng"]}
    assert client.post(f"/orders/{order_id}/advance",
                       headers=COURIER).get_json()["status"] == "delivered"


def test_group_order_each_pays_own_share(env):
    client, *_ = env
    code = client.post("/groups", headers=ANN).get_json()["code"]
    client.put(f"/groups/{code}/items", json={"items": [{"dish_id": 1, "quantity": 1}]},
               headers=ANN)
    group = client.put(f"/groups/{code}/items", json={"items": [{"dish_id": 4, "quantity": 2}]},
                       headers=BOB).get_json()
    assert group["restaurant"] == "Хата"
    assert {u: s["amount"] for u, s in group["shares"].items()} == {
        "ann@example.com": 135.0, "bob@example.com": 240.0,
    }

    assert client.post(f"/groups/{code}/checkout", json=HOME, headers=BOB).status_code == 403
    order = client.post(f"/groups/{code}/checkout", json=HOME, headers=ANN).get_json()
    assert order["total"] == 375.0
    assert order["participants"] == ["ann@example.com", "bob@example.com"]

    client.post(f"/orders/{order['id']}/pay", json={"method": "card"}, headers=ANN)
    assert client.get(f"/orders/{order['id']}", headers=BOB).get_json()["status"] == \
        "awaiting_payment"
    result = client.post(f"/orders/{order['id']}/pay", json={"method": "cash"},
                         headers=BOB).get_json()
    assert result["order"]["status"] == "created"
    assert [o["id"] for o in client.get("/orders", headers=BOB).get_json()] == [order["id"]]


def test_group_keeps_one_restaurant_and_closes_after_checkout(env):
    client, *_ = env
    code = client.post("/groups", headers=ANN).get_json()["code"]
    client.put(f"/groups/{code}/items", json={"items": [{"dish_id": 1, "quantity": 1}]},
               headers=ANN)
    wrong = client.put(f"/groups/{code}/items", json={"items": [{"dish_id": 5, "quantity": 1}]},
                       headers=BOB)
    assert wrong.status_code == 400
    client.post(f"/groups/{code}/checkout", json=HOME, headers=ANN)
    late = client.put(f"/groups/{code}/items", json={"items": [{"dish_id": 1, "quantity": 1}]},
                      headers=BOB)
    assert late.status_code == 409


def test_empty_group_cannot_be_ordered(env):
    client, *_ = env
    code = client.post("/groups", headers=ANN).get_json()["code"]
    assert client.post(f"/groups/{code}/checkout", json=HOME, headers=ANN).status_code == 400
    assert client.get("/groups/unknown", headers=ANN).status_code == 404
