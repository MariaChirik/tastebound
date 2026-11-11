ALLERGENS = ("gluten", "eggs", "fish", "milk", "peanuts")
DIETS = ("vegan", "vegetarian", "gluten_free")
MAX_PRICE = 10000


def parse_list(value):
    if not value:
        return []
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def filter_dishes(dishes, exclude_allergens=None, diet=None):
    excluded = set(exclude_allergens or [])
    result = []
    for dish in dishes:
        if excluded & set(dish["allergens"]):
            continue
        if diet and diet not in dish["diets"]:
            continue
        result.append(dish)
    return result


def validate_dish(data, partial=False):
    fields = {}
    if "name" in data or not partial:
        name = (data.get("name") or "").strip()
        if not 2 <= len(name) <= 80:
            return None, "назва має містити від 2 до 80 символів"
        fields["name"] = name
    if "price" in data or not partial:
        price = data.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)) \
                or not 0 < price <= MAX_PRICE:
            return None, f"ціна має бути від 0 до {MAX_PRICE} грн"
        fields["price"] = round(float(price), 2)
    if "composition" in data or not partial:
        composition = (data.get("composition") or "").strip()
        if len(composition) > 300:
            return None, "склад може містити до 300 символів"
        fields["composition"] = composition
    for key, allowed in (("allergens", ALLERGENS), ("diets", DIETS)):
        if key in data or not partial:
            values = data.get(key) or []
            if not isinstance(values, list) or not set(values) <= set(allowed):
                return None, "некоректний список алергенів або дієт"
            fields[key] = sorted(set(values))
    return fields, None
