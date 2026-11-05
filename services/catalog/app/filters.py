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
