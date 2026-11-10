
"""Authentication service: password hashing and JWT token management."""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.db.dependencies import get_db
from app.models.user import User
from app.schemas.user import TokenData

# These must be configured via environment variables.
SECRET_KEY: str | None = None
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


def configure_auth(
    secret_key: str,
    algorithm: str = "HS256",
    access_token_expire_minutes: int = 30,
    refresh_token_expire_days: int = 7,
) -> None:
    """Initialize auth configuration from environment variables.

    Call this at application startup. Raises ValueError if the secret
    key is missing or empty.
    """
    global SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS

    if not secret_key or not secret_key.strip():
        raise ValueError("AUTH_SECRET_KEY must be set in the environment.")

    SECRET_KEY = secret_key.strip()
    ALGORITHM = algorithm
    ACCESS_TOKEN_EXPIRE_MINUTES = access_token_expire_minutes
    REFRESH_TOKEN_EXPIRE_DAYS = refresh_token_expire_days


def hash_password(password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    # bcrypt truncates passwords at 72 bytes
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    try:
        pwd_bytes = plain_password.encode("utf-8")[:72]
        return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT refresh token."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str, expected_type: str = "access") -> TokenData | None:
    """Verify a JWT access token and return the token data.

    Returns None if the token is invalid or expired.
    """
    if not SECRET_KEY:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != expected_type:
            return None
        user_id: int | None = payload.get("sub")
        if user_id is None:
            return None
        return TokenData(user_id=int(user_id))
    except JWTError:
        return None


def get_user_by_email(db, email: str) -> User | None:
    """Look up a user by email (case-insensitive)."""
    return db.query(User).filter(User.email == email.lower()).first()


def get_user_by_id(db, user_id: int) -> User | None:
    """Look up a user by id."""
    return db.query(User).filter(User.id == user_id).first()


def authenticate_user(db, email: str, password: str) -> User | None:
    """Authenticate a user by email and password.

    Returns the user on success, None on failure. Always returns None
    (never raises) for invalid credentials to avoid leaking whether
    an account exists.
    """
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
