MIN_SCORE = 4
TOP_N = 5
SAME_RESTAURANT_POINTS = 2


def average(sums, counts, dish):
    count = int(counts.get(dish, 0) or 0)
    return float(sums.get(dish, 0)) / count if count else None


def rank(catalog, ratings, sums, counts, limit=TOP_N):
    by_name = {dish["name"]: dish for dish in catalog}
    liked = [by_name[name] for name, score in ratings.items()
             if score >= MIN_SCORE and name in by_name]
    liked_restaurants = {dish["restaurant"] for dish in liked}
    liked_diets = {diet for dish in liked for diet in dish["diets"]}

    scored = []
    for dish in catalog:
        if dish["name"] in ratings:
            continue
        points, reasons = 0.0, []
        if dish["restaurant"] in liked_restaurants:
            points += SAME_RESTAURANT_POINTS
            reasons.append(f"з ресторану «{dish['restaurant']}», який вам сподобався")
        shared = liked_diets & set(dish["diets"])
        if shared:
            points += len(shared)
            reasons.append("схожа на ваші улюблені страви")
        avg = average(sums, counts, dish["name"])
        if avg is not None:
            points += avg / 5
            if avg >= MIN_SCORE:
                reasons.append(f"середня оцінка {avg:.1f}")
        if points > 0:
            scored.append((points, dish, reasons))

    scored.sort(key=lambda entry: (-entry[0], entry[1]["name"]))
    return [{**dish, "reason": "; ".join(reasons) or "популярна страва"}
            for _, dish, reasons in scored[:limit]]
