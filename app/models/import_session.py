
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ImportSession(Base):
    """Server-side record of a pending spreadsheet import.

    Persisting the import plan server-side enables idempotent commits:
    a repeated confirmation request reuses the stored plan instead of
    re-processing client-submitted data, which prevents duplicate batches.
    """

    __tablename__ = "import_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Ownership: import sessions belong to the user who initiated them.
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Client-opaque idempotency key. The same key must never import twice.
    session_key: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )
    # pending | completed | failed | expired

    # The validated import plan produced during the preview/review stage.
    # Stored as JSON so the commit stage can reapply exactly what was approved.
    import_plan: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationship to the owning user.
    owner: Mapped["User"] = relationship("User", back_populates="import_sessions")

    def __repr__(self) -> str:
        return f"<ImportSession(id={self.id}, session_key={self.session_key!r}, user_id={self.user_id})>"
