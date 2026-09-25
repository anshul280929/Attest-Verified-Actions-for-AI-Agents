"""001 Initial schema for actions, action_events, and outbox tables

Revision ID: 001_initial_schema
Revises: None
Create Date: 2026-09-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. actions table
    op.create_table(
        "actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("resource_key", sa.Text(), nullable=False),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(length=50), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("downstream_ref", sa.Text(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("actions_resource_idx", "actions", ["resource_key", "state"])
    op.create_index("ix_actions_task_id", "actions", ["task_id"])

    # 2. action_events table (append-only audit trail)
    op.create_table(
        "action_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_state", sa.String(length=50), nullable=True),
        sa.Column("to_state", sa.String(length=50), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_action_events_action_id", "action_events", ["action_id"])

    # 3. outbox table
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outbox_action_id", "outbox", ["action_id"])

    # 4. Append-only trigger on action_events for PostgreSQL
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_action_events_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'action_events table is append-only: updates and deletes are prohibited';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER action_events_append_only
        BEFORE UPDATE OR DELETE ON action_events
        FOR EACH ROW EXECUTE FUNCTION prevent_action_events_modification();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS action_events_append_only ON action_events;")
    op.execute("DROP FUNCTION IF EXISTS prevent_action_events_modification();")
    op.drop_table("outbox")
    op.drop_table("action_events")
    op.drop_table("actions")
