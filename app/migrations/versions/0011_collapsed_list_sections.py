"""store each person's collapsed list sections

Revision ID: 0011_collapsed_sections
Revises: 0010_list_audit
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_collapsed_sections"
down_revision: Union[str, None] = "0010_list_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "collapsed_list_sections",
        sa.Column("list_id", sa.Integer(), sa.ForeignKey("shopping_lists.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("shopping_categories.id", ondelete="CASCADE"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("collapsed_list_sections")
