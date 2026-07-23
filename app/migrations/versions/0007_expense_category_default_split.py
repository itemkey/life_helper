"""add default split to expense categories

Revision ID: 0007_expense_cat_split
Revises: 0006_shop_categories_receipts
Create Date: 2026-07-23 00:00:07.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_expense_cat_split"
down_revision: Union[str, None] = "0006_shop_categories_receipts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "expense_categories",
        sa.Column("default_split", sa.String(length=16), server_default="selected", nullable=False),
    )
    op.create_check_constraint(
        "ck_expense_categories_default_split",
        "expense_categories",
        "default_split in ('all', 'selected', 'me')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_expense_categories_default_split", "expense_categories", type_="check")
    op.drop_column("expense_categories", "default_split")
