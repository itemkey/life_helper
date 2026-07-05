"""track visible list messages

Revision ID: 0002_list_view_messages
Revises: 0001_initial
Create Date: 2026-07-05 00:00:01.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_list_view_messages"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "list_view_messages",
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["shopping_lists.id"],
            name=op.f("fk_list_view_messages_list_id_shopping_lists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_list_view_messages_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("list_id", "user_id", name=op.f("pk_list_view_messages")),
    )
    op.create_index(op.f("ix_list_view_messages_chat_id"), "list_view_messages", ["chat_id"], unique=False)
    op.create_index(op.f("ix_list_view_messages_message_id"), "list_view_messages", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_list_view_messages_message_id"), table_name="list_view_messages")
    op.drop_index(op.f("ix_list_view_messages_chat_id"), table_name="list_view_messages")
    op.drop_table("list_view_messages")
