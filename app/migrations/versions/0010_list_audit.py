"""add an append-only audit journal and recover available legacy records

Revision ID: 0010_list_audit
Revises: 0009_list_price_mode
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_list_audit"
down_revision: Union[str, None] = "0009_list_price_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill(bind: sa.Connection, table: sa.Table, query: str, build) -> None:
    batch: list[dict] = []
    for row in bind.execute(sa.text(query)).mappings():
        batch.append(build(row))
        if len(batch) == 500:
            bind.execute(sa.insert(table), batch)
            batch.clear()
    if batch:
        bind.execute(sa.insert(table), batch)


def _event(*, list_id: int, actor_id: int | None, at, kind: str, subject_id: int | None,
           title: str, action: str, section_id: int | None = None,
           section_title: str | None = None, details: str | None = None) -> dict:
    return {
        "list_id": list_id,
        "actor_id": actor_id,
        "occurred_at": datetime.fromisoformat(at) if isinstance(at, str) else at,
        "subject_type": kind,
        "subject_id": subject_id,
        "subject_title": title,
        "section_id": section_id,
        "previous_section_id": None,
        "section_title": section_title,
        "action": action,
        "details": details,
        "origin": "legacy",
    }


def upgrade() -> None:
    op.create_table(
        "list_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("list_id", sa.Integer(), sa.ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("subject_title", sa.String(255), nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=True),
        sa.Column("previous_section_id", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.String(80), nullable=True),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(16), nullable=False, server_default="live"),
    )
    op.create_index("ix_list_audit_events_list_time", "list_audit_events", ["list_id", "occurred_at", "id"])
    op.create_index("ix_list_audit_events_hierarchy", "list_audit_events",
                    ["list_id", "subject_type", "section_id", "subject_id"])
    op.create_index("ix_list_audit_events_previous_section", "list_audit_events",
                    ["list_id", "subject_type", "previous_section_id"])
    bind = op.get_bind()
    table = sa.Table("list_audit_events", sa.MetaData(), autoload_with=bind)

    _backfill(bind, table,
        "SELECT id, owner_id, title, created_at FROM shopping_lists",
        lambda row: _event(list_id=row.id, actor_id=row.owner_id, at=row.created_at,
                           kind="list", subject_id=row.id, title=row.title,
                           action="Создан список"))
    _backfill(bind, table,
        "SELECT id, list_id, title, created_by_id, created_at FROM shopping_categories",
        lambda row: _event(list_id=row.list_id, actor_id=row.created_by_id, at=row.created_at,
                           kind="section", subject_id=row.id, title=row.title,
                           action="Создан раздел"))
    _backfill(bind, table,
        "SELECT i.id, i.list_id, i.text, i.author_id, i.created_at, i.is_done, "
        "i.category_id, c.title AS section_title FROM shopping_items i "
        "LEFT JOIN shopping_categories c ON c.id = i.category_id",
        lambda row: _event(list_id=row.list_id, actor_id=row.author_id, at=row.created_at,
                           kind="item", subject_id=row.id, title=row.text,
                           section_id=row.category_id, section_title=row.section_title,
                           action="Добавлен пункт",
                           details="Текущий статус при включении журнала: " +
                           ("отмечен" if row.is_done else "не отмечен")))
    _backfill(bind, table,
        "SELECT id, list_id, title, created_by_id, created_at FROM expense_categories",
        lambda row: _event(list_id=row.list_id, actor_id=row.created_by_id, at=row.created_at,
                           kind="expense_category", subject_id=row.id, title=row.title,
                           action="Создана категория трат"))
    _backfill(bind, table,
        "SELECT c.id, c.list_id, c.user_id, c.created_by_id, c.amount, c.created_at, "
        "l.currency FROM contributions c JOIN shopping_lists l ON l.id = c.list_id",
        lambda row: _event(list_id=row.list_id, actor_id=row.created_by_id, at=row.created_at,
                           kind="contribution", subject_id=row.id, title=f"Взнос участника {row.user_id}",
                           action="Добавлен взнос", details=f"{row.amount / 100:.2f} {row.currency}"))
    _backfill(bind, table,
        "SELECT e.id, e.list_id, e.title, e.created_by_id, e.amount, e.created_at, "
        "l.currency FROM expenses e JOIN shopping_lists l ON l.id = e.list_id",
        lambda row: _event(list_id=row.list_id, actor_id=row.created_by_id, at=row.created_at,
                           kind="expense", subject_id=row.id, title=row.title,
                           action="Записана трата", details=f"{row.amount / 100:.2f} {row.currency}"))
    _backfill(bind, table,
        "SELECT list_id, user_id, joined_at FROM list_members",
        lambda row: _event(list_id=row.list_id, actor_id=row.user_id, at=row.joined_at,
                           kind="member", subject_id=None, title=f"Участник {row.user_id}",
                           action="Присоединился к списку"))
    _backfill(bind, table,
        "SELECT list_id, user_id, banned_at FROM list_banned_members",
        lambda row: _event(list_id=row.list_id, actor_id=None, at=row.banned_at,
                           kind="member", subject_id=None, title=f"Участник {row.user_id}",
                           action="Заблокирован"))


def downgrade() -> None:
    raise RuntimeError("Журнал аудита нельзя удалить автоматическим откатом миграции.")
