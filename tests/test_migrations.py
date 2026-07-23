from __future__ import annotations

import re
from pathlib import Path


REVISION_PATTERN = re.compile(r'^revision:\s*str\s*=\s*"([^"]+)"', re.MULTILINE)


def test_alembic_revision_ids_fit_default_version_table() -> None:
    versions_dir = Path(__file__).resolve().parents[1] / "app" / "migrations" / "versions"

    too_long = []
    for migration_path in versions_dir.glob("*.py"):
        match = REVISION_PATTERN.search(migration_path.read_text(encoding="utf-8"))
        if match and len(match.group(1)) > 32:
            too_long.append((migration_path.name, match.group(1), len(match.group(1))))

    assert too_long == []
