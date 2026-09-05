"""Schema migration manager for Trader Machine V1.
Tracks migration versions, dates, and execution state in PostgreSQL.
"""
from pathlib import Path
from sqlalchemy import text
from database.connection import get_engine

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

def init_migration_table() -> None:
    """Ensure the schema_migrations audit table exists."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(64) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))

def get_applied_migrations() -> set[str]:
    """Retrieve all previously applied migration version keys."""
    init_migration_table()
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version FROM schema_migrations;"))
        return {row[0] for row in result.fetchall()}

def run_migrations() -> list[str]:
    """Scan and apply any pending SQL migrations in sequential order."""
    init_migration_table()
    applied = get_applied_migrations()
    applied_now = []

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    engine = get_engine()

    for sql_file in sql_files:
        version = sql_file.stem.split("_")[0]
        name = sql_file.name

        if version not in applied:
            with open(sql_file, "r", encoding="utf-8") as f:
                sql_content = f.read()

            with engine.begin() as conn:
                conn.execute(text(sql_content))
                conn.execute(
                    text("INSERT INTO schema_migrations (version, name) VALUES (:version, :name);"),
                    {"version": version, "name": name}
                )
            applied_now.append(name)

    return applied_now

if __name__ == "__main__":
    applied = run_migrations()
    if applied:
        print(f"Applied migrations: {', '.join(applied)}")
    else:
        print("Schema is up to date. No pending migrations.")
