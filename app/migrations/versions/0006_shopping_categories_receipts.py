"""add shopping categories and receipt expense links

Revision ID: 0006_shopping_categories_receipts
Revises: 0005_expense_categories
Create Date: 2026-07-23 00:00:06.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_shopping_categories_receipts"
down_revision: Union[str, None] = "0005_expense_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shopping_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("scope", sa.String(length=16), server_default="common", nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=True),
        sa.Column("accounting_mode", sa.String(length=16), server_default="per_item", nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope in ('common', 'personal')", name="ck_shopping_categories_scope"),
        sa.CheckConstraint(
            "accounting_mode in ('per_item', 'receipt')",
            name="ck_shopping_categories_accounting_mode",
        ),
        sa.CheckConstraint(
            "(scope = 'common' and owner_id is null) or "
            "(scope = 'personal' and owner_id is not null)",
            name="ck_shopping_categories_scope_owner",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_shopping_categories_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["shopping_lists.id"],
            name=op.f("fk_shopping_categories_list_id_shopping_lists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_shopping_categories_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shopping_categories")),
    )
    op.create_index(op.f("ix_shopping_categories_created_by_id"), "shopping_categories", ["created_by_id"], unique=False)
    op.create_index(op.f("ix_shopping_categories_list_id"), "shopping_categories", ["list_id"], unique=False)
    op.create_index(op.f("ix_shopping_categories_owner_id"), "shopping_categories", ["owner_id"], unique=False)

    op.add_column("shopping_items", sa.Column("category_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_shopping_items_category_id"), "shopping_items", ["category_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_shopping_items_category_id_shopping_categories"),
        "shopping_items",
        "shopping_categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "expense_items",
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["expense_id"],
            ["expenses.id"],
            name=op.f("fk_expense_items_expense_id_expenses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["shopping_items.id"],
            name=op.f("fk_expense_items_item_id_shopping_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("expense_id", "item_id", name=op.f("pk_expense_items")),
    )

    op.execute(
        """
        insert into shopping_categories
            (list_id, title, scope, owner_id, accounting_mode, position, created_by_id)
        select id, 'Общее', 'common', null, 'per_item', 1, owner_id
        from shopping_lists
        """
    )
    op.execute(
        """
        insert into shopping_categories
            (list_id, title, scope, owner_id, accounting_mode, position, created_by_id)
        select id, 'Личное', 'personal', owner_id, 'per_item', 2, owner_id
        from shopping_lists
        """
    )
    op.execute(
        """
        insert into shopping_categories
            (list_id, title, scope, owner_id, accounting_mode, position, created_by_id)
        select
            list_id,
            'Личное',
            'personal',
            user_id,
            'per_item',
            row_number() over (partition by list_id order by joined_at asc, user_id asc) + 2,
            user_id
        from list_members
        """
    )
    op.execute(
        """
        update shopping_items
        set category_id = (
            select sc.id
            from shopping_categories sc
            where sc.list_id = shopping_items.list_id and sc.scope = 'common'
            order by sc.position asc, sc.id asc
            limit 1
        )
        where scope = 'common'
        """
    )
    op.execute(
        """
        update shopping_items
        set category_id = (
            select sc.id
            from shopping_categories sc
            where
                sc.list_id = shopping_items.list_id
                and sc.scope = 'personal'
                and sc.owner_id = shopping_items.personal_owner_id
            order by sc.position asc, sc.id asc
            limit 1
        )
        where scope = 'personal'
        """
    )
    op.execute(
        """
        insert into expense_items (expense_id, item_id)
        select id, item_id
        from expenses
        where item_id is not null
        """
    )


def downgrade() -> None:
    op.drop_table("expense_items")
    op.drop_constraint(op.f("fk_shopping_items_category_id_shopping_categories"), "shopping_items", type_="foreignkey")
    op.drop_index(op.f("ix_shopping_items_category_id"), table_name="shopping_items")
    op.drop_column("shopping_items", "category_id")
    op.drop_index(op.f("ix_shopping_categories_owner_id"), table_name="shopping_categories")
    op.drop_index(op.f("ix_shopping_categories_list_id"), table_name="shopping_categories")
    op.drop_index(op.f("ix_shopping_categories_created_by_id"), table_name="shopping_categories")
    op.drop_table("shopping_categories")
