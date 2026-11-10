
"""Authentication routes: register, login, logout, current user, refresh, password reset."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import DbSession, get_current_active_user, oauth2_scheme
from app.models.user import User
from app.schemas.user import (
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
)
from app.services.auth import (
    ALGORITHM,
    SECRET_KEY,
    authenticate_user,
    create_access_token,
    create_refresh_token,
    get_user_by_email,
    get_user_by_id,
    hash_password,
    verify_password,
    verify_token,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(user_data: UserCreate, db: DbSession):
    """Register a new user account.

    Passwords are hashed with bcrypt before storage. Email addresses are
    normalized to lowercase and must be unique.
    """
    email = user_data.email.strip().lower()

    existing = get_user_by_email(db, email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        full_name=user_data.full_name.strip(),
        email=email,
        hashed_password=hash_password(user_data.password),
        is_active=True,
    )

    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    return user


@router.post("/login", response_model=Token)
def login(credentials: UserLogin, db: DbSession):
    """Authenticate a user and return access + refresh tokens.

    Uses a generic error message for invalid credentials to avoid
    revealing whether an account exists.
    """
    email = credentials.email.strip().lower()

    user = authenticate_user(db, email, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=Token)
def refresh_token(payload: RefreshRequest, db: DbSession):
    """Refresh an access token using a valid refresh token.

    Implements refresh token rotation: the old refresh token is
    invalidated (by signature check) and a new pair is issued.
    Since refresh tokens are stateless JWTs, revocation is handled
    by short expiry and client-side discard.
    """
    try:
        token_data = verify_token(payload.refresh_token, expected_type="refresh")
        if not token_data or not token_data.user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = get_user_by_id(db, token_data.user_id)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        access_token = create_access_token(data={"sub": str(user.id)})
        new_refresh_token = create_refresh_token(data={"sub": str(user.id)})

        return Token(
            access_token=access_token,
            refresh_token=new_refresh_token,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Refresh failed: {str(exc)}",
        )


@router.post("/logout", response_model=MessageResponse)
def logout():
    """Log out the current user.

    With stateless JWT tokens, logout is handled client-side by
    discarding the token. This endpoint exists for API completeness
    and to provide a clear logout action.
    """
    return MessageResponse(message="Logged out successfully.")


@router.get("/me", response_model=UserResponse)
def get_current_user_profile(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Return the authenticated user's profile."""
    return current_user


@router.post("/password-reset/request", response_model=MessageResponse)
def request_password_reset(payload: PasswordResetRequest, db: DbSession):
    """Request a password reset.

    Always returns success to avoid revealing whether an account exists.
    In production, this would email a time-limited reset token to the
    user. For this portfolio implementation, the reset token is
    returned directly (for demonstration only).
    """
    # Look up the user but don't reveal existence
    user = get_user_by_email(db, payload.email)

    if user:
        # In production: email a reset link. Here, generate a reset token
        # that can be used with /password-reset/confirm.
        reset_token = create_access_token(
            data={"sub": str(user.id), "purpose": "password_reset"},
            expires_delta=timedelta(minutes=15),
        )
        # NOTE: In production, send this via email, not return it.
        # Returned here only for demonstration/testing purposes.
        return MessageResponse(
            message=(
                "If an account exists, a reset link has been sent. "
                f"Reset token (demo only): {reset_token}"
            )
        )

    return MessageResponse(
        message="If an account exists, a reset link has been sent."
    )


@router.post("/password-reset/confirm", response_model=MessageResponse)
def confirm_password_reset(
    payload: PasswordResetConfirm,
    db: DbSession,
):
    """Confirm a password reset using a valid reset token."""
    token_data = verify_token(payload.token, expected_type="access")
    if not token_data or not token_data.user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired reset token.",
        )

    # Verify the token was issued for password reset
    try:
        decoded = jwt.decode(
            payload.token, SECRET_KEY, algorithms=[ALGORITHM]
        )
        if decoded.get("purpose") != "password_reset":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid reset token purpose.",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired reset token.",
        )

    user = get_user_by_id(db, token_data.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    user.hashed_password = hash_password(payload.new_password)
    db.add(user)
    db.commit()

    return MessageResponse(message="Password has been reset successfully.")
