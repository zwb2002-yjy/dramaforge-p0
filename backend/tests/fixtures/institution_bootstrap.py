"""Create the disposable Full-gate database; never connect to a local instance."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg

ADMIN = "postgresql://dramaforge:quality-postgres-password@postgres-quality:5432/dramaforge"
DATABASE = "dramaforge_institution"


def main() -> None:
    if os.environ.get("INSTITUTION_QUALITY_FIXTURE") != "1":
        raise RuntimeError("This fixture requires the isolated quality Compose service")
    # Exact, synthetic destination. No DATABASE_URL from the caller is consumed.
    with psycopg.connect(ADMIN, autocommit=True) as connection:
        if connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,),
        ).fetchone():
            raise RuntimeError(
                "Institution fixture database already exists; use a fresh quality run"
            )
        connection.execute("CREATE DATABASE dramaforge_institution")
    backend = Path(__file__).resolve().parents[2]
    database_url = ADMIN.replace("postgresql://", "postgresql+asyncpg://").rsplit("/", 1)[0]
    environment = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": f"{database_url}/{DATABASE}",
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend, env=environment, check=True,
    )
    with psycopg.connect(ADMIN, autocommit=True) as connection:
        connection.execute(
            "ALTER ROLE dramaforge_app LOGIN NOINHERIT NOBYPASSRLS "
            "PASSWORD 'quality-institution-app-password'"
        )
        connection.execute(
            "ALTER ROLE dramaforge_director_checkpoint LOGIN NOINHERIT NOBYPASSRLS "
            "PASSWORD 'quality-institution-checkpoint-password'"
        )
        roles = connection.execute(
            "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
            "WHERE rolname IN ('dramaforge_app', 'dramaforge_director_checkpoint')"
        ).fetchall()
        if len(roles) != 2 or any(superuser or bypass for _, superuser, bypass in roles):
            raise RuntimeError("Fixture application roles must not bypass RLS")
    print("Institution fixture migrated; application/checkpoint roles enforce RLS", flush=True)


if __name__ == "__main__":
    main()
