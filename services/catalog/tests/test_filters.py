import pytest

from app.data import SAMPLE_DISHES
from app.filters import ALLERGENS, filter_dishes, parse_list, validate_dish


def names(dishes):
    return {dish["name"] for dish in dishes}


CASES = [[a] for a in ALLERGENS] + [["gluten", "milk"], list(ALLERGENS)]


@pytest.mark.parametrize("excluded", CASES)
def test_no_dish_with_excluded_allergen_is_left(excluded):
    for dish in filter_dishes(SAMPLE_DISHES, excluded):
        assert not set(excluded) & set(dish["allergens"])


@pytest.mark.parametrize("excluded, expected", [
    (["peanuts"], 5),
    (["gluten"], 2),
    (["eggs", "fish"], 4),
    (list(ALLERGENS), 2),
    (["unknown"], 6),
])
def test_number_of_dishes_left(excluded, expected):
    assert len(filter_dishes(SAMPLE_DISHES, excluded)) == expected


def test_dishes_without_allergens_always_stay():
    safe = {d["name"] for d in SAMPLE_DISHES if not d["allergens"]}
    assert safe <= names(filter_dishes(SAMPLE_DISHES, list(ALLERGENS)))


@pytest.mark.parametrize("diet", ["vegan", "vegetarian", "gluten_free"])
def test_diet_and_allergens_together(diet):
    result = filter_dishes(SAMPLE_DISHES, ["gluten"], diet)
    assert all(diet in d["diets"] and "gluten" not in d["allergens"] for d in result)


def test_filter_does_not_change_catalog():
    before = [dict(d) for d in SAMPLE_DISHES]
    filter_dishes(SAMPLE_DISHES, ["milk"], "vegan")
    assert SAMPLE_DISHES == before


@pytest.mark.parametrize("raw, parsed", [
    ("GLUTEN,Milk", ["gluten", "milk"]),
    (" eggs , , fish ", ["eggs", "fish"]),
    ("", []),
])
def test_query_parsing(raw, parsed):
    assert parse_list(raw) == parsed


def test_dish_validation_keeps_only_known_values():
    fields, error = validate_dish({"name": " Суп ", "price": 99.999, "allergens": ["milk", "milk"],
                                   "diets": []})
    assert error is None
    assert fields == {"name": "Суп", "price": 100.0, "composition": "", "allergens": ["milk"],
                      "diets": []}
    assert validate_dish({"price": True, "name": "Суп"})[1]
    assert validate_dish({"diets": ["keto"]}, partial=True)[1]
    assert validate_dish({}, partial=True) == ({}, None)
