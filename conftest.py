
"""Test configuration and fixtures for FlowDesk backend tests.

Uses a dedicated test database (flowdesk_test) so the development
database is never touched.
"""

import os

# Point SQLAlchemy at the test database before the app modules import
# and create their engine.
os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:2580@localhost:5432/flowdesk_test"
os.environ["AUTH_SECRET_KEY"] = "test-secret-key-do-not-use-in-production"
os.environ["AUTH_ALGORITHM"] = "HS256"
os.environ["AUTH_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import engine, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth import hash_password  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def create_test_schema():
    """Create all tables in the test database once per session."""
    # Drop all tables first to ensure clean schema with user ownership columns.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    # Drop all tables after the session to leave a clean state.
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    """Provide a transactional SQLAlchemy session for a test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def test_user(db):
    """Create a committed test user and return it.

    Uses a separate session that commits, so the user is visible
    to API requests made through the TestClient (which uses its own
    get_db() dependency).
    """
    session = SessionLocal()
    # Clean up any leftover user from a previous test
    session.query(User).filter(User.email == "test@example.com").delete()
    session.commit()
    user = User(
        full_name="Test User",
        email="test@example.com",
        hashed_password=hash_password("testpassword123"),
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    session.close()
    return user


@pytest.fixture
def auth_client(test_user):
    """Provide an authenticated TestClient with a valid JWT token."""
    from app.services.auth import create_access_token

    token = create_access_token(
        data={"sub": str(test_user.id)},
        expires_delta=None,
    )

    client = TestClient(app)
    client.headers.update(
        {"Authorization": f"Bearer {token}"}
    )
    return client
