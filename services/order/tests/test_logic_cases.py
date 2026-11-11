import pytest

from app.logic import (
    MAX_QUANTITY,
    calculate_total,
    distance_km,
    estimate_delivery_minutes,
    kitchen_load,
    parse_location,
    price_lines,
    shares_of,
    validate_lines,
    validate_schedule,
)

NOW = 1_800_000_000.0


def item(price, quantity, user="ann"):
    return {"price": price, "quantity": quantity, "user": user}


@pytest.mark.parametrize("items, total", [
    ([item(135.0, 1)], 135.0),
    ([item(135.0, 2), item(120.0, 1)], 390.0),
    ([item(0.1, 3)], 0.3),
    ([item(99.99, 3)], 299.97),
    ([item(19.95, 7), item(0.05, 1)], 139.7),
])
def test_order_total(items, total):
    assert calculate_total(items) == total


def test_shares_add_up_to_total():
    items = [item(135.0, 2, "ann"), item(120.0, 1, "bob"), item(99.99, 1, "eve")]
    shares = shares_of(items)
    assert round(sum(s["amount"] for s in shares.values()), 2) == calculate_total(items)
    assert all(s["status"] == "unpaid" for s in shares.values())


@pytest.mark.parametrize("portions, active, km, minutes", [
    (1, 0, 0.0, 20),
    (1, 0, 3.0, 29),
    (3, 0, 3.0, 33),
    (1, 2, 3.0, 37),
    (1, 0, 10.0, 50),
    (5, 3, 6.5, 60),
])
def test_delivery_time_table(portions, active, km, minutes):
    assert estimate_delivery_minutes([{"quantity": portions}], active, km) == minutes


def test_more_portions_and_queue_never_make_delivery_faster():
    base = estimate_delivery_minutes([{"quantity": 1}], 0, 2.0)
    assert estimate_delivery_minutes([{"quantity": 4}], 0, 2.0) > base
    assert estimate_delivery_minutes([{"quantity": 1}], 3, 2.0) > base
    assert estimate_delivery_minutes([{"quantity": 1}], 0, 5.0) > base


def test_distance_is_symmetric_and_realistic():
    hata, wok = (50.4501, 30.5234), (50.4370, 30.5160)
    there = distance_km(*hata, *wok)
    assert there == distance_km(*wok, *hata)
    assert 1.4 < there < 1.7


def test_kitchen_load_ignores_finished_and_far_scheduled_orders():
    orders = [
        {"restaurant": "Хата", "status": "created", "deliver_at": NOW + 1800},
        {"restaurant": "Хата", "status": "cooking", "deliver_at": NOW + 2 * 3600},
        {"restaurant": "Хата", "status": "created", "deliver_at": NOW + 2 * 3600 + 1},
        {"restaurant": "Хата", "status": "delivered", "deliver_at": NOW},
        {"restaurant": "Хата", "status": "awaiting_payment", "deliver_at": NOW},
    ]
    assert kitchen_load(orders, "Хата", NOW) == 2
    assert kitchen_load(orders, "Wok Kyiv", NOW) == 0


@pytest.mark.parametrize("quantity, ok", [
    (1, True), (MAX_QUANTITY, True), (MAX_QUANTITY + 1, False),
    (0, False), (-1, False), (1.5, False),
])
def test_quantity_limits(quantity, ok):
    _, error = validate_lines([{"dish_id": 1, "quantity": quantity}])
    assert (error is None) == ok


CATALOG = [
    {"id": 1, "name": "Борщ", "restaurant": "Хата", "price": 135.0, "orderable": True},
    {"id": 2, "name": "Сирники", "restaurant": "Хата", "price": 120.0, "orderable": False},
    {"id": 3, "name": "Рис", "restaurant": "Wok Kyiv", "price": 110.0, "orderable": False,
     "restaurant_overloaded": True},
]


@pytest.mark.parametrize("dish_id, message", [
    (99, "не знайдено"),
    (2, "недоступна"),
    (3, "не приймає"),
])
def test_unavailable_dishes_are_rejected(dish_id, message):
    _, _, error = price_lines([{"dish_id": dish_id, "quantity": 1}], CATALOG, "ann")
    assert message in error


def test_priced_items_carry_catalog_price_and_owner():
    items, restaurant, error = price_lines([{"dish_id": 1, "quantity": 2}], CATALOG, "ann")
    assert error is None and restaurant == "Хата"
    assert items == [{"dish_id": 1, "name": "Борщ", "price": 135.0, "quantity": 2,
                      "restaurant": "Хата", "user": "ann"}]


@pytest.mark.parametrize("data", [
    {"address": "ab", "lat": 50.4, "lng": 30.5},
    {"address": "вул. Хрещатик, 1", "lat": "50.4", "lng": 30.5},
    {"address": "вул. Хрещатик, 1", "lat": 91, "lng": 30.5},
    {"address": "вул. Хрещатик, 1", "lat": True, "lng": 30.5},
])
def test_invalid_locations(data):
    assert parse_location(data)[3]


def test_schedule_boundaries():
    assert validate_schedule(NOW + 30 * 60, NOW, 30) == (NOW + 30 * 60, None)
    assert validate_schedule(NOW + 30 * 60 - 1, NOW, 30)[1]
    assert validate_schedule(NOW + 7 * 24 * 3600, NOW, 30)[1] is None
    assert validate_schedule("tomorrow", NOW, 30)[1]
