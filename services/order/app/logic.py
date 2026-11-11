import math

STATUS_FLOW = ["awaiting_payment", "created", "cooking", "delivering", "delivered"]
CANCELLABLE_STATUSES = ("awaiting_payment", "created")
ACTIVE_STATUSES = ("created", "cooking")

TRANSITIONS_BY_ROLE = {
    "restaurant_staff": ("created", "cooking"),
    "courier": ("delivering",),
}

BASE_COOK_MINUTES = 15
EXTRA_PORTION_MINUTES = 2
MINUTES_PER_ACTIVE_ORDER = 4
PICKUP_MINUTES = 5
COURIER_SPEED_KMH = 20
MAX_DISTANCE_KM = 30
MAX_QUANTITY = 20
MAX_SCHEDULE_AHEAD_SECONDS = 7 * 24 * 3600
KITCHEN_HORIZON_SECONDS = 2 * 3600

SETTLED_SHARES = ("paid", "cash_due")

STATUS_MESSAGES = {
    "created": "оплачено і передано в ресторан",
    "cooking": "готується",
    "delivering": "передано кур'єру",
    "delivered": "доставлено",
    "cancelled": "скасовано",
}

TRACKING_STATUS = {
    "created": "accepted",
    "cooking": "cooking",
    "delivering": "on_the_way",
    "delivered": "delivered",
}


def validate_lines(lines):
    if not isinstance(lines, list) or not lines:
        return None, "items must be a non-empty list"
    merged = {}
    for line in lines:
        if not isinstance(line, dict):
            return None, "every item needs dish_id and quantity"
        dish_id, quantity = line.get("dish_id"), line.get("quantity")
        if isinstance(dish_id, bool) or not isinstance(dish_id, int):
            return None, "dish_id must be an integer"
        if isinstance(quantity, bool) or not isinstance(quantity, int) \
                or not 1 <= quantity <= MAX_QUANTITY:
            return None, f"quantity must be an integer from 1 to {MAX_QUANTITY}"
        merged[dish_id] = merged.get(dish_id, 0) + quantity
    return [{"dish_id": key, "quantity": value} for key, value in merged.items()], None


def price_lines(lines, dishes, user):
    by_id = {dish["id"]: dish for dish in dishes}
    items, restaurants = [], set()
    for line in lines:
        dish = by_id.get(line["dish_id"])
        if dish is None:
            return None, None, f"dish {line['dish_id']} not found"
        if dish.get("restaurant_overloaded"):
            message = f"ресторан «{dish['restaurant']}» тимчасово не приймає нових замовлень"
            return None, None, message
        if not dish["orderable"]:
            return None, None, f"«{dish['name']}» зараз недоступна для замовлення"
        restaurants.add(dish["restaurant"])
        items.append({
            "dish_id": dish["id"], "name": dish["name"], "price": dish["price"],
            "quantity": line["quantity"], "restaurant": dish["restaurant"], "user": user,
        })
    if len(restaurants) > 1:
        return None, None, "one order can contain dishes from one restaurant only"
    return items, restaurants.pop(), None


def calculate_total(items):
    return round(sum(item["price"] * item["quantity"] for item in items), 2)


def shares_of(items):
    totals = {}
    for item in items:
        totals[item["user"]] = totals.get(item["user"], 0) + item["price"] * item["quantity"]
    return {user: {"amount": round(amount, 2), "status": "unpaid", "method": None}
            for user, amount in sorted(totals.items())}


def all_settled(shares):
    return all(share["status"] in SETTLED_SHARES for share in shares.values())


def parse_location(data):
    address = (data.get("address") or "").strip()
    lat, lng = data.get("lat"), data.get("lng")
    if not 3 <= len(address) <= 200:
        return None, None, None, "address must be 3-200 characters"
    for value in (lat, lng):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, None, None, "lat and lng must be numbers"
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None, None, None, "lat or lng out of range"
    return address, float(lat), float(lng), None


def distance_km(lat1, lng1, lat2, lng2):
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * radius * math.asin(math.sqrt(a)), 2)


def road_minutes(distance):
    return PICKUP_MINUTES + distance / COURIER_SPEED_KMH * 60


def estimate_delivery_minutes(items, active_orders, distance):
    portions = sum(item["quantity"] for item in items)
    cooking = BASE_COOK_MINUTES + EXTRA_PORTION_MINUTES * max(0, portions - 1)
    queue = MINUTES_PER_ACTIVE_ORDER * active_orders
    return math.ceil(cooking + queue + road_minutes(distance))


def kitchen_load(orders, restaurant, now):
    return sum(
        1 for order in orders
        if order["restaurant"] == restaurant and order["status"] in ACTIVE_STATUSES
        and order["deliver_at"] - now <= KITCHEN_HORIZON_SECONDS
    )


def validate_schedule(value, now, eta_minutes):
    if value is None:
        return None, None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "scheduled_for must be a unix time in seconds"
    if value < now + eta_minutes * 60:
        return None, f"the earliest possible delivery is in {eta_minutes} minutes"
    if value > now + MAX_SCHEDULE_AHEAD_SECONDS:
        return None, "orders can be scheduled at most 7 days ahead"
    return float(value), None


def can_cancel(status):
    return status in CANCELLABLE_STATUSES


def next_status(status):
    if status not in STATUS_FLOW:
        return None
    index = STATUS_FLOW.index(status)
    return STATUS_FLOW[index + 1] if index + 1 < len(STATUS_FLOW) else None


def can_advance(role, status):
    return status in TRANSITIONS_BY_ROLE.get(role, ()) and next_status(status) is not None


def visible_statuses(role):
    return TRANSITIONS_BY_ROLE.get(role, ())
