"""remember each participant's overview page

Revision ID: 0012_list_view_page
Revises: 0011_collapsed_sections
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_list_view_page"
down_revision: Union[str, None] = "0011_collapsed_sections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("list_view_messages", sa.Column("page", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("list_view_messages", "page")
