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
    stored = app.extensions["users"]["anna@example.com"]["password_hash"]
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
