from __future__ import annotations

import logging
import time
from pathlib import Path

import psycopg

logger = logging.getLogger(__name__)


class MigrationRunner:
    def __init__(self, database_url: str, migrations_dir: Path) -> None:
        self._database_url = database_url
        self._migrations_dir = migrations_dir

    def run(self, max_retries: int = 10, retry_delay: float = 2.0) -> None:
        migration_files = sorted(self._migrations_dir.glob("*.sql"))

        conn = None
        for attempt in range(1, max_retries + 1):
            try:
                conn = psycopg.connect(self._database_url)
                break
            except psycopg.OperationalError as e:
                if attempt == max_retries:
                    logger.error("Failed to connect to database after %d attempts: %s", max_retries, e)
                    raise
                logger.warning("Database connection attempt %d/%d failed: %s. Retrying in %.1fs...",
                               attempt, max_retries, e, retry_delay)
                time.sleep(retry_delay)

        with conn:
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
