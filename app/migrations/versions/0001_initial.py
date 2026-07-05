"""initial shopping lists schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-05 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_table(
        "shopping_lists",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("is_public", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("public_token", sa.String(length=64), nullable=True),
        sa.Column("public_token_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_shopping_lists_owner_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shopping_lists")),
        sa.UniqueConstraint("public_token", name=op.f("uq_shopping_lists_public_token")),
        sa.UniqueConstraint("public_token_hash", name=op.f("uq_shopping_lists_public_token_hash")),
    )
    op.create_index(op.f("ix_shopping_lists_owner_id"), "shopping_lists", ["owner_id"], unique=False)
    op.create_table(
        "list_members",
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["list_id"], ["shopping_lists.id"], name=op.f("fk_list_members_list_id_shopping_lists"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_list_members_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("list_id", "user_id", name=op.f("pk_list_members")),
        sa.UniqueConstraint("list_id", "user_id", name="uq_list_members_list_id_user_id"),
    )
    op.create_table(
        "shopping_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=255), nullable=False),
        sa.Column("is_done", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], name=op.f("fk_shopping_items_author_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["list_id"], ["shopping_lists.id"], name=op.f("fk_shopping_items_list_id_shopping_lists"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shopping_items")),
    )
    op.create_index(op.f("ix_shopping_items_author_id"), "shopping_items", ["author_id"], unique=False)
    op.create_index(op.f("ix_shopping_items_list_id"), "shopping_items", ["list_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_shopping_items_list_id"), table_name="shopping_items")
    op.drop_index(op.f("ix_shopping_items_author_id"), table_name="shopping_items")
    op.drop_table("shopping_items")
    op.drop_table("list_members")
    op.drop_index(op.f("ix_shopping_lists_owner_id"), table_name="shopping_lists")
    op.drop_table("shopping_lists")
    op.drop_table("users")
