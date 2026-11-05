STATUS_FLOW = ["created", "cooking", "delivering", "delivered"]
CANCELLABLE_STATUSES = ("created",)


def calculate_total(items):
    return round(sum(item["price"] * item["quantity"] for item in items), 2)


def validate_items(items):
    if not isinstance(items, list) or not items:
        return "items must be a non-empty list"
    for item in items:
        if not isinstance(item, dict) or not item.get("name"):
            return "every item needs a name"
        price = item.get("price")
        quantity = item.get("quantity")
        if not isinstance(price, (int, float)) or price <= 0:
            return "price must be a positive number"
        if not isinstance(quantity, int) or quantity < 1:
            return "quantity must be an integer >= 1"
    return None


def can_cancel(status):
    return status in CANCELLABLE_STATUSES


def next_status(status):
    if status not in STATUS_FLOW:
        return None
    index = STATUS_FLOW.index(status)
    if index + 1 < len(STATUS_FLOW):
        return STATUS_FLOW[index + 1]
    return None
