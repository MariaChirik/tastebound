from app import create_app, validate_registration


def make_client():
    return create_app().test_client()


def register(client, email="anna@example.com", password="strongpass1", role="client"):
    return client.post("/register", json={"email": email, "password": password, "role": role})


def test_health():
    response = make_client().get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "service": "auth"}


def test_register_success():
    response = register(make_client())
    assert response.status_code == 201
    assert response.get_json()["role"] == "client"


def test_register_duplicate_email():
    client = make_client()
    register(client)
    assert register(client).status_code == 409


def test_register_rejects_short_password():
    assert register(make_client(), password="123").status_code == 400


def test_register_rejects_unknown_role():
    assert register(make_client(), role="hacker").status_code == 400


def test_admin_cannot_self_register():
    assert register(make_client(), role="admin").status_code == 400


def test_password_is_stored_as_hash():
    app = create_app()
    client = app.test_client()
    register(client, password="strongpass1")
    rows = app.extensions["db"].query(
        "SELECT password_hash FROM users WHERE email = ?", ("anna@example.com",)
    )
    stored = rows[0][0]
    assert stored != "strongpass1"
    assert "strongpass1" not in stored


def test_login_success_returns_token():
    client = make_client()
    register(client)
    response = client.post(
        "/login", json={"email": "anna@example.com", "password": "strongpass1"}
    )
    assert response.status_code == 200
    assert response.get_json()["token"]


def test_login_wrong_password():
    client = make_client()
    register(client)
    response = client.post("/login", json={"email": "anna@example.com", "password": "wrong"})
    assert response.status_code == 401


def test_validate_registration_valid_data():
    assert validate_registration("a@b.com", "longenough", "courier") is None


def test_users_survive_app_restart_with_same_database():
    from app.db import SqliteDb

    db = SqliteDb()
    register(create_app(db=db).test_client())
    restarted = create_app(db=db).test_client()
    response = restarted.post(
        "/login", json={"email": "anna@example.com", "password": "strongpass1"}
    )
    assert response.status_code == 200


ADMIN = {"email": "admin@tastebound.local", "password": "adminpass1"}


def admin_app():
    return create_app(admin_email=ADMIN["email"], admin_password=ADMIN["password"])


def login(client, email, password):
    return client.post("/login", json={"email": email, "password": password})


def admin_headers(client):
    token = login(client, ADMIN["email"], ADMIN["password"]).get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_restaurant_staff_must_choose_restaurant():
    assert register(make_client(), role="restaurant_staff").status_code == 400


def test_staff_waits_for_approval_and_token_carries_restaurant():
    client = admin_app().test_client()
    response = client.post("/register", json={
        "email": "chef@hata.ua", "password": "strongpass1",
        "role": "restaurant_staff", "restaurant": "Хата",
    })
    assert response.get_json()["status"] == "pending"
    assert login(client, "chef@hata.ua", "strongpass1").status_code == 403

    approved = client.post("/users/chef@hata.ua/status", json={"status": "active"},
                           headers=admin_headers(client))
    assert approved.status_code == 200

    result = login(client, "chef@hata.ua", "strongpass1").get_json()
    assert result["restaurant"] == "Хата"
    claims = client.application.extensions["signer"].loads(result["token"])
    assert claims == {"email": "chef@hata.ua", "role": "restaurant_staff", "restaurant": "Хата"}


def test_admin_comes_from_settings_and_can_block_users():
    client = admin_app().test_client()
    register(client)
    headers = admin_headers(client)
    users = client.get("/users", headers=headers).get_json()
    assert [user["email"] for user in users] == ["admin@tastebound.local", "anna@example.com"]

    client.post("/users/anna@example.com/status", json={"status": "blocked"}, headers=headers)
    assert login(client, "anna@example.com", "strongpass1").status_code == 403


def test_only_admin_can_manage_users():
    client = admin_app().test_client()
    register(client)
    token = login(client, "anna@example.com", "strongpass1").get_json()["token"]
    response = client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert client.get("/users").status_code == 401


def test_admin_cannot_be_blocked():
    client = admin_app().test_client()
    response = client.post(f"/users/{ADMIN['email']}/status", json={"status": "blocked"},
                           headers=admin_headers(client))
    assert response.status_code == 409
