from __future__ import annotations

from pathlib import Path

from .config import get_settings
from .migrations import MigrationRunner


def main() -> None:
    settings = get_settings()
    migrations_dir = (Path(__file__).resolve().parent.parent / "migrations").resolve()
    MigrationRunner(settings.database_url, migrations_dir).run()
    print("Migrations completed successfully.")


if __name__ == "__main__":
    main()
