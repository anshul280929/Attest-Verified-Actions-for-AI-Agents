"""SQLAlchemy declarative models for actions, audit events, and outbox."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Dialect-adaptive types: native JSONB and UUID on Postgres, standard JSON and UUID on SQLite
JSONB_TYPE = JSON().with_variant(PG_JSONB(), "postgresql")
UUID_TYPE = Uuid(as_uuid=True).with_variant(PG_UUID(as_uuid=True), "postgresql")


class Base(DeclarativeBase):
    pass


class Action(Base):
    """An action recorded by Attest before tool execution."""

    __tablename__ = "actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    task_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    tool: Mapped[str] = mapped_column(Text, nullable=False)
    resource_key: Mapped[str] = mapped_column(Text, nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB_TYPE, nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    downstream_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    events: Mapped[list["ActionEvent"]] = relationship(
        "ActionEvent",
        back_populates="action",
        cascade="all, delete-orphan",
        order_by="ActionEvent.id",
    )
    outbox_entries: Mapped[list["Outbox"]] = relationship(
        "Outbox", back_populates="action", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("actions_resource_idx", "resource_key", "state"),)


class ActionEvent(Base):
    """Append-only audit trail event recording state transitions."""

    __tablename__ = "action_events"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, ForeignKey("actions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB_TYPE, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    action: Mapped["Action"] = relationship("Action", back_populates="events")


class Outbox(Base):
    """Transactional outbox queue for asynchronous reconciliation and compensation."""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, ForeignKey("actions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)  # 'reconcile' | 'compensate'
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    action: Mapped["Action"] = relationship("Action", back_populates="outbox_entries")
