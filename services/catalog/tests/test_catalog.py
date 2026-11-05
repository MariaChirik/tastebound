from app import create_app
from app.data import SAMPLE_DISHES
from app.filters import filter_dishes, parse_list


def names(dishes):
    return {dish["name"] for dish in dishes}


def test_health():
    response = create_app().test_client().get("/health")
    assert response.status_code == 200
    assert response.get_json()["service"] == "catalog"


def test_no_filters_returns_all_dishes():
    assert len(filter_dishes(SAMPLE_DISHES)) == len(SAMPLE_DISHES)


def test_excluded_allergen_removes_dishes():
    result = filter_dishes(SAMPLE_DISHES, exclude_allergens=["gluten"])
    assert all("gluten" not in dish["allergens"] for dish in result)
    assert "Борщ з пампушками" not in names(result)


def test_several_allergens_are_all_excluded():
    result = filter_dishes(SAMPLE_DISHES, exclude_allergens=["peanuts", "milk"])
    assert "Паста з арахісовим соусом" not in names(result)
    assert "Сирники зі сметаною" not in names(result)


def test_diet_filter_keeps_only_matching_dishes():
    result = filter_dishes(SAMPLE_DISHES, diet="vegan")
    assert result
    assert all("vegan" in dish["diets"] for dish in result)


def test_allergen_and_diet_combined():
    result = filter_dishes(SAMPLE_DISHES, exclude_allergens=["gluten"], diet="vegan")
    assert names(result) == {"Боул з кіноа та овочами", "Рис з овочами"}


def test_parse_list():
    assert parse_list("Gluten, nuts ,") == ["gluten", "nuts"]
    assert parse_list(None) == []


def test_dishes_endpoint_applies_filters():
    client = create_app().test_client()
    response = client.get("/dishes?exclude_allergens=gluten,eggs&diet=vegetarian")
    dishes = response.get_json()
    assert response.status_code == 200
    assert dishes
    assert all("gluten" not in d["allergens"] and "eggs" not in d["allergens"] for d in dishes)
