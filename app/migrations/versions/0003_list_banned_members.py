"""track banned list members

Revision ID: 0003_list_banned_members
Revises: 0002_list_view_messages
Create Date: 2026-07-08 00:00:03.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_list_banned_members"
down_revision: Union[str, None] = "0002_list_view_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "list_banned_members",
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("banned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["shopping_lists.id"],
            name=op.f("fk_list_banned_members_list_id_shopping_lists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_list_banned_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("list_id", "user_id", name=op.f("pk_list_banned_members")),
        sa.UniqueConstraint("list_id", "user_id", name=op.f("uq_list_banned_members_list_id_user_id")),
    )


def downgrade() -> None:
    op.drop_table("list_banned_members")
