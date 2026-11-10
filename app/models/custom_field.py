
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CustomFieldDefinition(Base):
    __tablename__ = "custom_field_definitions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    # Ownership: custom-field definitions belong to the user who created them.
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    field_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="text",
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

    # Relationship to the owning user.
    owner: Mapped["User"] = relationship("User", back_populates="custom_fields")

    def __repr__(self) -> str:
        return f"<CustomFieldDefinition(id={self.id}, name={self.name!r}, user_id={self.user_id})>"
