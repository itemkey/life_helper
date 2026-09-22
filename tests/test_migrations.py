from __future__ import annotations

import re
import importlib
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


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
