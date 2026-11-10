
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    # Ownership: every lead belongs to the authenticated user who created it.
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    company: Mapped[str] = mapped_column(String(200), nullable=False)

    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    location: Mapped[str | None] = mapped_column(String(150), nullable=True)

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="New",
    )

    # Optional monetary deal value (stored as numeric to avoid float issues).
    deal_value: Mapped[float | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    follow_up_date: Mapped[Date | None] = mapped_column(Date, nullable=True)

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

    imported_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationship to the owning user.
    owner: Mapped["User"] = relationship("User", back_populates="leads")

    def __repr__(self) -> str:
        return f"<Lead(id={self.id}, name={self.name!r}, user_id={self.user_id})>"
