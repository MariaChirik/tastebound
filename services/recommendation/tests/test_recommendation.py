from itsdangerous import URLSafeTimedSerializer

from app import create_app
from app.ranking import rank
from app.security import TokenAuth

CATALOG = [
    {"id": 1, "name": "Борщ", "restaurant": "Хата", "price": 135.0,
     "allergens": ["gluten"], "diets": []},
    {"id": 4, "name": "Сирники", "restaurant": "Хата", "price": 120.0,
     "allergens": ["milk"], "diets": ["vegetarian"]},
    {"id": 3, "name": "Боул", "restaurant": "Green Bowl", "price": 175.0,
     "allergens": [], "diets": ["vegan", "vegetarian"]},
    {"id": 6, "name": "Рис з овочами", "restaurant": "Wok Kyiv", "price": 110.0,
     "allergens": [], "diets": ["vegan", "vegetarian"]},
]


class FakeStore:
    def __init__(self):
        self.sets = {}
        self.hashes = {}

    def ping(self):
        return True

    def zadd(self, key, mapping):
        self.sets.setdefault(key, {}).update(mapping)

    def zscore(self, key, member):
        return self.sets.get(key, {}).get(member)

    def zrange(self, key, start, end, withscores=False):
        return sorted(self.sets.get(key, {}).items(), key=lambda item: item[1])

    def hincrbyfloat(self, key, field, amount):
        bucket = self.hashes.setdefault(key, {})
        bucket[field] = float(bucket.get(field, 0)) + amount

    def hincrby(self, key, field, amount):
        bucket = self.hashes.setdefault(key, {})
        bucket[field] = int(bucket.get(field, 0)) + amount

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))


class FakeCatalog:
    def __init__(self, down=False):
        self.down = down
        self.queries = []

    def dishes(self, exclude_allergens=""):
        if self.down:
            raise OSError("catalog is down")
        self.queries.append(exclude_allergens)
        excluded = set(filter(None, exclude_allergens.split(",")))
        return [dish for dish in CATALOG if not excluded & set(dish["allergens"])]


SECRET = "test-secret"


def H(user, role="client"):
    token = URLSafeTimedSerializer(SECRET).dumps({"email": user, "role": role})
    return {"Authorization": f"Bearer {token}"}


def make_client(catalog=None, store=None):
    return create_app(store=store or FakeStore(), catalog=catalog or FakeCatalog(),
                      auth=TokenAuth(SECRET)).test_client()


def rate(client, user, dish, score):
    return client.post("/ratings", json={"dish": dish, "score": score}, headers=H(user))


def names(response):
    return [dish["name"] for dish in response.get_json()["dishes"]]


def test_health():
    assert make_client().get("/health").get_json()["service"] == "recommendation"


def test_rating_out_of_range_or_fractional_is_rejected():
    client = make_client()
    assert rate(client, "ann", "Борщ", 9).status_code == 400
    assert rate(client, "ann", "Борщ", 3.5).status_code == 400


def test_recommends_new_dishes_similar_to_liked_ones():
    client = make_client()
    rate(client, "ann", "Боул", 5)
    dishes = client.get("/recommendations/ann", headers=H("ann")).get_json()["dishes"]
    assert dishes[0]["name"] == "Рис з овочами"
    assert "Боул" not in [dish["name"] for dish in dishes]
    assert dishes[0]["reason"]


def test_same_restaurant_is_recommended():
    client = make_client()
    rate(client, "ann", "Борщ", 5)
    assert names(client.get("/recommendations/ann", headers=H("ann")))[0] == "Сирники"


def test_low_scores_do_not_attract_similar_dishes():
    client = make_client()
    rate(client, "ann", "Борщ", 2)
    assert names(client.get("/recommendations/ann", headers=H("ann"))) == []


def test_new_user_gets_dishes_rated_well_by_others():
    client = make_client()
    rate(client, "bob", "Сирники", 5)
    rate(client, "kate", "Сирники", 4)
    assert names(client.get("/recommendations/newcomer", headers=H("newcomer"))) == ["Сирники"]


def test_allergens_are_passed_to_catalog_and_respected():
    catalog = FakeCatalog()
    client = make_client(catalog)
    rate(client, "ann", "Борщ", 5)
    response = client.get("/recommendations/ann?exclude_allergens=milk", headers=H("ann"))
    assert "Сирники" not in names(response)
    assert catalog.queries[-1] == "milk"


def test_catalog_failure_returns_empty_list_instead_of_error():
    response = make_client(FakeCatalog(down=True)).get("/recommendations/ann", headers=H("ann"))
    assert response.status_code == 200
    assert response.get_json() == {"user": "ann", "dishes": [], "available": False}


def test_rerating_updates_average_without_counting_twice():
    store = FakeStore()
    client = make_client(store=store)
    rate(client, "ann", "Борщ", 2)
    rate(client, "ann", "Борщ", 4)
    assert store.hashes["dish:score_sum"]["Борщ"] == 4
    assert store.hashes["dish:score_count"]["Борщ"] == 1


def test_rank_limits_result_size():
    ratings = {"Боул": 5}
    assert len(rank(CATALOG, ratings, {}, {}, limit=1)) == 1


def test_user_cannot_read_or_rate_for_someone_else():
    client = make_client()
    assert client.get("/recommendations/ann", headers=H("bob")).status_code == 403
    assert client.get("/ratings/ann", headers=H("bob")).status_code == 403
    assert client.post("/ratings", json={"dish": "Борщ", "score": 5}).status_code == 401
    courier = H("ann", "courier")
    assert client.post("/ratings", json={"dish": "Борщ", "score": 5},
                       headers=courier).status_code == 403
