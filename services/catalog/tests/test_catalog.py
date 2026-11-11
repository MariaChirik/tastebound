from itsdangerous import URLSafeTimedSerializer

from app import create_app
from app.data import SAMPLE_DISHES
from app.filters import filter_dishes, parse_list
from app.security import TokenAuth


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


SECRET = "test-secret"


def auth_client():
    return create_app(auth=TokenAuth(SECRET)).test_client()


def headers(role, restaurant=""):
    token = URLSafeTimedSerializer(SECRET).dumps(
        {"email": f"{role}@test.ua", "role": role, "restaurant": restaurant}
    )
    return {"Authorization": f"Bearer {token}"}


CHEF = headers("restaurant_staff", "Хата")
ADMIN = headers("admin")


def test_seed_creates_dishes_with_ids_and_restaurants_with_coordinates():
    client = auth_client()
    dishes = client.get("/dishes").get_json()
    assert [dish["id"] for dish in dishes] == [1, 2, 3, 4, 5, 6]
    assert all(dish["orderable"] for dish in dishes)
    places = {place["name"]: place for place in client.get("/restaurants").get_json()}
    assert places["Хата"]["lat"] == 50.4501


def test_staff_adds_dish_with_allergens_to_own_restaurant():
    client = auth_client()
    response = client.post("/menu", json={
        "name": "Вареники з вишнею", "price": 145, "composition": "тісто, вишня, цукор",
        "allergens": ["gluten"], "diets": ["vegetarian"],
    }, headers=CHEF)
    assert response.status_code == 201
    dish = response.get_json()
    assert dish["restaurant"] == "Хата"
    assert dish["allergens"] == ["gluten"]
    assert dish["composition"] == "тісто, вишня, цукор"
    filtered = client.get("/dishes?exclude_allergens=gluten").get_json()
    assert "Вареники з вишнею" not in names(filtered)


def test_invalid_dish_data_is_rejected():
    client = auth_client()
    bad = [
        {"name": "X", "price": 10},
        {"name": "Суп", "price": -5},
        {"name": "Суп", "price": 50, "allergens": ["poison"]},
    ]
    for body in bad:
        assert client.post("/menu", json=body, headers=CHEF).status_code == 400


def test_stop_list_hides_dish_from_clients_but_not_from_order_service():
    client = auth_client()
    response = client.patch("/menu/1", json={"available": False}, headers=CHEF)
    assert response.get_json()["available"] is False
    assert 1 not in [dish["id"] for dish in client.get("/dishes").get_json()]
    [dish] = client.get("/dishes?ids=1").get_json()
    assert dish["orderable"] is False


def test_staff_cannot_change_other_restaurant_dishes():
    client = auth_client()
    assert client.patch("/menu/5", json={"available": False}, headers=CHEF).status_code == 404
    courier = headers("courier")
    assert client.patch("/menu/1", json={"available": False}, headers=courier).status_code == 403
    assert client.get("/menu").status_code == 401


def test_overload_pauses_orders_for_whole_restaurant():
    client = auth_client()
    response = client.post("/menu/overload", json={"overloaded": True}, headers=CHEF)
    assert response.get_json()["overloaded"] is True
    by_id = {dish["id"]: dish for dish in client.get("/dishes").get_json()}
    assert by_id[1]["orderable"] is False and by_id[4]["orderable"] is False
    assert by_id[5]["orderable"] is True
    menu = client.get("/menu", headers=CHEF).get_json()
    assert menu["restaurant"]["overloaded"] is True


def test_admin_hides_dish_for_moderation():
    client = auth_client()
    response = client.post("/admin/dishes/2/hidden", json={"hidden": True}, headers=ADMIN)
    assert response.get_json()["hidden"] is True
    assert 2 not in [dish["id"] for dish in client.get("/dishes").get_json()]
    assert len(client.get("/admin/dishes", headers=ADMIN).get_json()) == 6
    assert client.post("/admin/dishes/2/hidden", json={"hidden": True},
                       headers=CHEF).status_code == 403


def test_staff_updates_composition_and_allergens():
    client = auth_client()
    dish = client.patch("/menu/1", json={"composition": "буряк, квасоля", "allergens": []},
                        headers=CHEF).get_json()
    assert dish["composition"] == "буряк, квасоля" and dish["allergens"] == []
    assert client.patch("/menu/1", json={"composition": "x" * 301},
                        headers=CHEF).status_code == 400
