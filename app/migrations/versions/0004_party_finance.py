"""add party item scopes and finance tracking

Revision ID: 0004_party_finance
Revises: 0003_list_banned_members
Create Date: 2026-07-23 00:00:04.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_party_finance"
down_revision: Union[str, None] = "0003_list_banned_members"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shopping_lists",
        sa.Column("currency", sa.String(length=3), server_default="BYN", nullable=False),
    )
    op.add_column("shopping_lists", sa.Column("cashbox_holder_id", sa.BigInteger(), nullable=True))
    op.execute("update shopping_lists set cashbox_holder_id = owner_id where cashbox_holder_id is null")
    op.create_index(op.f("ix_shopping_lists_cashbox_holder_id"), "shopping_lists", ["cashbox_holder_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_shopping_lists_cashbox_holder_id_users"),
        "shopping_lists",
        "users",
        ["cashbox_holder_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "shopping_items",
        sa.Column("scope", sa.String(length=16), server_default="common", nullable=False),
    )
    op.add_column("shopping_items", sa.Column("personal_owner_id", sa.BigInteger(), nullable=True))
    op.create_index(op.f("ix_shopping_items_personal_owner_id"), "shopping_items", ["personal_owner_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_shopping_items_personal_owner_id_users"),
        "shopping_items",
        "users",
        ["personal_owner_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint("ck_shopping_items_scope", "shopping_items", "scope in ('common', 'personal')")
    op.create_check_constraint(
        "ck_shopping_items_scope_owner",
        "shopping_items",
        "(scope = 'common' and personal_owner_id is null) or "
        "(scope = 'personal' and personal_owner_id is not null)",
    )

    op.create_table(
        "contributions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_contributions_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["shopping_lists.id"],
            name=op.f("fk_contributions_list_id_shopping_lists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_contributions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contributions")),
    )
    op.create_index(op.f("ix_contributions_created_by_id"), "contributions", ["created_by_id"], unique=False)
    op.create_index(op.f("ix_contributions_list_id"), "contributions", ["list_id"], unique=False)
    op.create_index(op.f("ix_contributions_user_id"), "contributions", ["user_id"], unique=False)

    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("payer_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source in ('cashbox', 'personal')", name="ck_expenses_source"),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_expenses_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["shopping_items.id"],
            name=op.f("fk_expenses_item_id_shopping_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["shopping_lists.id"],
            name=op.f("fk_expenses_list_id_shopping_lists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payer_id"],
            ["users.id"],
            name=op.f("fk_expenses_payer_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expenses")),
    )
    op.create_index(op.f("ix_expenses_created_by_id"), "expenses", ["created_by_id"], unique=False)
    op.create_index(op.f("ix_expenses_item_id"), "expenses", ["item_id"], unique=False)
    op.create_index(op.f("ix_expenses_list_id"), "expenses", ["list_id"], unique=False)
    op.create_index(op.f("ix_expenses_payer_id"), "expenses", ["payer_id"], unique=False)

    op.create_table(
        "expense_shares",
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["expense_id"],
            ["expenses.id"],
            name=op.f("fk_expense_shares_expense_id_expenses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_expense_shares_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("expense_id", "user_id", name=op.f("pk_expense_shares")),
    )


def downgrade() -> None:
    op.drop_table("expense_shares")
    op.drop_index(op.f("ix_expenses_payer_id"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_list_id"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_item_id"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_created_by_id"), table_name="expenses")
    op.drop_table("expenses")
    op.drop_index(op.f("ix_contributions_user_id"), table_name="contributions")
    op.drop_index(op.f("ix_contributions_list_id"), table_name="contributions")
    op.drop_index(op.f("ix_contributions_created_by_id"), table_name="contributions")
    op.drop_table("contributions")
    op.drop_constraint("ck_shopping_items_scope_owner", "shopping_items", type_="check")
    op.drop_constraint("ck_shopping_items_scope", "shopping_items", type_="check")
    op.drop_constraint(op.f("fk_shopping_items_personal_owner_id_users"), "shopping_items", type_="foreignkey")
    op.drop_index(op.f("ix_shopping_items_personal_owner_id"), table_name="shopping_items")
    op.drop_column("shopping_items", "personal_owner_id")
    op.drop_column("shopping_items", "scope")
    op.drop_constraint(op.f("fk_shopping_lists_cashbox_holder_id_users"), "shopping_lists", type_="foreignkey")
    op.drop_index(op.f("ix_shopping_lists_cashbox_holder_id"), table_name="shopping_lists")
    op.drop_column("shopping_lists", "cashbox_holder_id")
    op.drop_column("shopping_lists", "currency")
