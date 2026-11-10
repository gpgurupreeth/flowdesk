
from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LeadCustomFieldValue(Base):
    __tablename__ = "lead_custom_field_values"

    __table_args__ = (
        UniqueConstraint(
            "lead_id",
            "custom_field_id",
            name="uq_lead_custom_field_value",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    custom_field_id: Mapped[int] = mapped_column(
        ForeignKey(
            "custom_field_definitions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
