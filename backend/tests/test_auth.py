from collections import defaultdict
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import auth
import main
import security
from database import Base, engine
from main import app


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.counters: defaultdict[str, int] = defaultdict(int)
        self.expirations: dict[str, int] = {}

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        return None

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def getex(self, key: str, ex: int) -> str | None:
        value = self.values.get(key)
        if value is not None:
            self.expirations[key] = ex
        return value

    def getdel(self, key: str) -> str | None:
        self.expirations.pop(key, None)
        return self.values.pop(key, None)

    def delete(self, key: str) -> int:
        self.expirations.pop(key, None)
        return int(self.values.pop(key, None) is not None)

    def incr(self, key: str) -> int:
        self.counters[key] += 1
        return self.counters[key]

    def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    fake_redis = MemoryRedis()
    monkeypatch.setattr(security, "redis_client", fake_redis)
    monkeypatch.setattr(auth, "redis_client", fake_redis)
    monkeypatch.setattr(main, "redis_client", fake_redis)
    app.state.fake_redis = fake_redis
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


def sign_in_admin(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={
            "email": "admin@example.com",
            "password": "local-admin-password-change-me",
        },
    )
    assert response.status_code == 200
    assert "httponly" in response.headers["set-cookie"].lower()


def test_admin_can_create_user_and_role_is_enforced(client: TestClient) -> None:
    sign_in_admin(client)
    created = client.post(
        "/users",
        json={
            "email": "member@example.com",
            "full_name": "Workspace Member",
            "password": "a-long-member-password",
            "role": "user",
        },
    )
    assert created.status_code == 201
    assert created.json()["role"] == "user"
    assert "password_hash" not in created.json()

    client.cookies.clear()
    login = client.post(
        "/auth/login",
        json={"email": "member@example.com", "password": "a-long-member-password"},
    )
    assert login.status_code == 200
    assert client.get("/users").status_code == 403
    assert client.get("/auth/me").json()["email"] == "member@example.com"


def test_last_admin_cannot_disable_themselves(client: TestClient) -> None:
    sign_in_admin(client)
    me = client.get("/auth/me").json()

    response = client.patch(f"/users/{me['id']}", json={"is_active": False})

    assert response.status_code == 400
    assert "own active administrator" in response.json()["detail"]


def test_invalid_credentials_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "incorrect-password"},
    )

    assert response.status_code == 401


def test_authenticated_request_refreshes_idle_session_expiry(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(security.settings, "session_ttl_seconds", 300)
    sign_in_admin(client)
    token = client.cookies.get(security.settings.session_cookie_name)
    assert token is not None
    key = security.session_key(token)
    fake_redis = client.app.state.fake_redis
    assert fake_redis.expirations[key] == 300

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert fake_redis.expirations[key] == 300
    assert "max-age=300" in response.headers["set-cookie"].lower()
