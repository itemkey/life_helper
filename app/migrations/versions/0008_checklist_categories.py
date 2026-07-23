"""allow checklist shopping categories

Revision ID: 0008_checklist_categories
Revises: 0007_expense_cat_split
Create Date: 2026-07-23 00:00:08.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008_checklist_categories"
down_revision: Union[str, None] = "0007_expense_cat_split"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_shopping_categories_accounting_mode", "shopping_categories", type_="check")
    op.create_check_constraint(
        "ck_shopping_categories_accounting_mode",
        "shopping_categories",
        "accounting_mode in ('per_item', 'receipt', 'checklist')",
    )


def downgrade() -> None:
    op.execute("update shopping_categories set accounting_mode = 'per_item' where accounting_mode = 'checklist'")
    op.drop_constraint("ck_shopping_categories_accounting_mode", "shopping_categories", type_="check")
    op.create_check_constraint(
        "ck_shopping_categories_accounting_mode",
        "shopping_categories",
        "accounting_mode in ('per_item', 'receipt')",
    )
