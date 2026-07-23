"""add flexible expense categories

Revision ID: 0005_expense_categories
Revises: 0004_party_finance
Create Date: 2026-07-23 00:00:05.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_expense_categories"
down_revision: Union[str, None] = "0004_party_finance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "expense_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_expense_categories_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["shopping_lists.id"],
            name=op.f("fk_expense_categories_list_id_shopping_lists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expense_categories")),
        sa.UniqueConstraint("list_id", "title", name="uq_expense_categories_list_id_title"),
    )
    op.create_index(op.f("ix_expense_categories_created_by_id"), "expense_categories", ["created_by_id"], unique=False)
    op.create_index(op.f("ix_expense_categories_list_id"), "expense_categories", ["list_id"], unique=False)
    op.add_column("expenses", sa.Column("category_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_expenses_category_id"), "expenses", ["category_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_expenses_category_id_expense_categories"),
        "expenses",
        "expense_categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_expenses_category_id_expense_categories"), "expenses", type_="foreignkey")
    op.drop_index(op.f("ix_expenses_category_id"), table_name="expenses")
    op.drop_column("expenses", "category_id")
    op.drop_index(op.f("ix_expense_categories_list_id"), table_name="expense_categories")
    op.drop_index(op.f("ix_expense_categories_created_by_id"), table_name="expense_categories")
    op.drop_table("expense_categories")
