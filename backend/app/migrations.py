from __future__ import annotations

from pathlib import Path

import psycopg


class MigrationRunner:
    def __init__(self, database_url: str, migrations_dir: Path) -> None:
        self._database_url = database_url
        self._migrations_dir = migrations_dir

    def run(self) -> None:
        migration_files = sorted(self._migrations_dir.glob("*.sql"))

        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        filename TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )

                for migration_file in migration_files:
                    cur.execute(
                        "SELECT 1 FROM schema_migrations WHERE filename = %s",
                        (migration_file.name,),
                    )
                    if cur.fetchone():
                        continue

                    sql = migration_file.read_text(encoding="utf-8")
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (filename) VALUES (%s)",
                        (migration_file.name,),
                    )
            conn.commit()
