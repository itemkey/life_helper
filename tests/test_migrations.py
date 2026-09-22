from __future__ import annotations

import re
import importlib
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.base import Base
from app.db.models import CollapsedListSection, ListAuditEvent


REVISION_PATTERN = re.compile(r'^revision:\s*str\s*=\s*"([^"]+)"', re.MULTILINE)


def test_alembic_revision_ids_fit_default_version_table() -> None:
    versions_dir = Path(__file__).resolve().parents[1] / "app" / "migrations" / "versions"

    too_long = []
    for migration_path in versions_dir.glob("*.py"):
        match = REVISION_PATTERN.search(migration_path.read_text(encoding="utf-8"))
        if match and len(match.group(1)) > 32:
            too_long.append((migration_path.name, match.group(1), len(match.group(1))))

    assert too_long == []


def test_price_mode_migration_preserves_existing_lists(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migration = importlib.import_module("app.migrations.versions.0009_list_price_mode")
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE shopping_lists (id INTEGER PRIMARY KEY, title TEXT NOT NULL)"))
            connection.execute(sa.text("INSERT INTO shopping_lists (id, title) VALUES (1, 'Семья'), (2, 'Поездка')"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            rows = connection.execute(sa.text("SELECT id, title, prices_enabled FROM shopping_lists ORDER BY id")).all()
            assert rows == [(1, "Семья", 1), (2, "Поездка", 1)]
            connection.execute(sa.text("INSERT INTO shopping_lists (id, title) VALUES (3, 'Новый')"))
            assert connection.scalar(sa.text("SELECT prices_enabled FROM shopping_lists WHERE id = 3")) == 1
    finally:
        engine.dispose()


def test_audit_migration_recovers_existing_records_without_changing_them(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migration = importlib.import_module("app.migrations.versions.0010_list_audit")
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection, tables=[
                table for table in Base.metadata.sorted_tables if table is not ListAuditEvent.__table__
            ])
            connection.execute(sa.text("INSERT INTO users (id, first_name) VALUES (100, 'Анна')"))
            connection.execute(sa.text("INSERT INTO shopping_lists (id, owner_id, title) VALUES (1, 100, 'Дом')"))
            connection.execute(sa.text(
                "INSERT INTO shopping_categories (id, list_id, title, scope) VALUES (10, 1, 'Продукты', 'common')"
            ))
            connection.execute(sa.text(
                "INSERT INTO shopping_items (id, list_id, text, category_id, scope) "
                "VALUES (20, 1, 'Молоко', 10, 'common')"
            ))
            connection.execute(sa.text(
                "INSERT INTO contributions (id, list_id, user_id, amount) VALUES (30, 1, 100, 5000)"
            ))
            connection.execute(sa.text(
                "INSERT INTO expenses (id, list_id, title, amount, payer_id, source) "
                "VALUES (40, 1, 'Молоко', 1000, 100, 'cashbox')"
            ))
            before = connection.execute(sa.text("SELECT id, title FROM shopping_lists")).all()
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            after = connection.execute(sa.text("SELECT id, title FROM shopping_lists")).all()
            events = connection.execute(sa.text(
                "SELECT subject_type, subject_title, origin FROM list_audit_events ORDER BY id"
            )).all()
            assert before == after == [(1, "Дом")]
            assert [(kind, title) for kind, title, _ in events] == [
                ("list", "Дом"), ("section", "Продукты"), ("item", "Молоко"),
                ("contribution", "Взнос участника 100"), ("expense", "Молоко"),
            ]
            assert all(origin == "legacy" for _, _, origin in events)
    finally:
        engine.dispose()


def test_collapsed_sections_migration_preserves_existing_lists_and_items(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migration = importlib.import_module("app.migrations.versions.0011_collapsed_list_sections")
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection, tables=[
                table for table in Base.metadata.sorted_tables if table is not CollapsedListSection.__table__
            ])
            connection.execute(sa.text("INSERT INTO users (id, first_name) VALUES (100, 'Анна')"))
            connection.execute(sa.text("INSERT INTO shopping_lists (id, owner_id, title) VALUES (1, 100, 'Дом')"))
            connection.execute(sa.text(
                "INSERT INTO shopping_categories (id, list_id, title, scope) VALUES (10, 1, 'Продукты', 'common')"
            ))
            connection.execute(sa.text(
                "INSERT INTO shopping_items (id, list_id, text, category_id, scope) "
                "VALUES (20, 1, 'Молоко', 10, 'common')"
            ))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            connection.execute(sa.text(
                "INSERT INTO collapsed_list_sections (list_id, user_id, category_id) VALUES (1, 100, 10)"
            ))
            assert connection.execute(sa.text("SELECT id, title FROM shopping_lists")).all() == [(1, "Дом")]
            assert connection.execute(sa.text("SELECT id, text FROM shopping_items")).all() == [(20, "Молоко")]
            assert connection.execute(sa.text("SELECT list_id, user_id, category_id FROM collapsed_list_sections")).all() == [(1, 100, 10)]
    finally:
        engine.dispose()
