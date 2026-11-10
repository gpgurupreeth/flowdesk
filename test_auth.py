
"""Authentication backend tests."""

from app.models.user import User
from app.services.auth import hash_password, verify_password


def test_password_hashing(db, test_user):
    """Passwords are hashed and verifiable."""
    user = db.query(User).filter(User.email == "test@example.com").first()
    assert user is not None
    assert user.hashed_password != "testpassword123"
    assert verify_password("testpassword123", user.hashed_password) is True
    assert verify_password("wrongpassword", user.hashed_password) is False


def test_hash_password_produces_bcrypt_hash():
    """hash_password produces a bcrypt hash."""
    hashed = hash_password("mypassword123")
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    assert verify_password("mypassword123", hashed) is True


def test_register_user(auth_client):
    """A new user can register."""
    response = auth_client.post(
        "/api/auth/register",
        json={
            "full_name": "New User",
            "email": "newuser@example.com",
            "password": "newpass123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["full_name"] == "New User"
    assert "hashed_password" not in data


def test_register_duplicate_email(auth_client, test_user):
    """Duplicate email registration is rejected."""
    response = auth_client.post(
        "/api/auth/register",
        json={
            "full_name": "Duplicate",
            "email": "test@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 409


def test_register_email_normalization(auth_client):
    """Email is normalized to lowercase."""
    response = auth_client.post(
        "/api/auth/register",
        json={
            "full_name": "Upper",
            "email": "UPPER@EXAMPLE.COM",
            "password": "password123",
        },
    )
    assert response.status_code == 201
    assert response.json()["email"] == "upper@example.com"


def test_register_weak_password(auth_client):
    """Password below minimum length is rejected."""
    response = auth_client.post(
        "/api/auth/register",
        json={
            "full_name": "Weak",
            "email": "weak@example.com",
            "password": "short",
        },
    )
    assert response.status_code == 422


def test_login_success(auth_client, test_user):
    """A user can log in with valid credentials."""
    # Use a fresh unauthenticated client
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpassword123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_invalid_credentials(auth_client):
    """Invalid credentials are rejected with a generic message."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401
    assert "detail" in response.json()

    # Also test non-existent email
    response = client.post(
        "/api/auth/login",
        json={"email": "nonexistent@example.com", "password": "password123"},
    )
    assert response.status_code == 401


def test_login_inactive_user(db, test_user):
    """Inactive accounts cannot log in."""
    from fastapi.testclient import TestClient
    from app.main import app

    # Create an inactive user directly in the db session
    inactive_user = User(
        full_name="Inactive User",
        email="inactive@example.com",
        hashed_password=hash_password("password123"),
        is_active=False,
    )
    db.add(inactive_user)
    db.commit()

    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"email": "inactive@example.com", "password": "password123"},
    )
    assert response.status_code == 401


def test_get_current_user(auth_client, test_user):
    """The /api/auth/me endpoint returns the current user."""
    response = auth_client.get("/api/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_user.id
    assert data["email"] == "test@example.com"
    assert data["full_name"] == "Test User"
    assert "hashed_password" not in data


def test_unauthenticated_access_rejected():
    """Unauthenticated requests are rejected with 401."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/auth/me")
    assert response.status_code == 401

    response = client.get("/api/leads")
    assert response.status_code == 401

    response = client.post("/api/leads", json={
        "name": "Test", "email": "test@example.com", "company": "Co"
    })
    assert response.status_code == 401
