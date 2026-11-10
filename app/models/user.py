
from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    """Application user account.

    Owns leads, custom-field definitions, import sessions, and other
    CRM records. Data isolation is enforced by scoping every query to
    the authenticated user's id.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    full_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships to owned resources.
    leads: Mapped[list["Lead"]] = relationship(
        "Lead", back_populates="owner", cascade="all, delete-orphan"
    )
    custom_fields: Mapped[list["CustomFieldDefinition"]] = relationship(
        "CustomFieldDefinition",
        back_populates="owner",
        cascade="all, delete-orphan",
    )
    import_sessions: Mapped[list["ImportSession"]] = relationship(
        "ImportSession",
        back_populates="owner",
        cascade="all, delete-orphan",
    )

    @property
    def workspace_id(self) -> str:
        return f"ws_user_{self.id}"

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email!r})>"
