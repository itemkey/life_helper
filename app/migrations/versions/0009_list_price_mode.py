"""add optional price tracking to shopping lists

Revision ID: 0009_list_price_mode
Revises: 0008_checklist_categories
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_list_price_mode"
down_revision: Union[str, None] = "0008_checklist_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shopping_lists",
        sa.Column("prices_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("shopping_lists", "prices_enabled")
