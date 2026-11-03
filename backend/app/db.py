import os
import sqlite3

from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

print(
    "DATABASE MODE:",
    "PostgreSQL" if DATABASE_URL else "SQLite"
)
# =========================================================
# PostgreSQL schema
# =========================================================

POSTGRES_SCHEMA = """

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meetings (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    transcript TEXT DEFAULT '',
    analysis_json TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    owner TEXT DEFAULT '',
    deadline TEXT DEFAULT '',
    status TEXT DEFAULT 'Open',
    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER NOT NULL,
    decision TEXT NOT NULL,
    context TEXT DEFAULT '',
    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

"""


# =========================================================
# SQLite schema
# =========================================================

SQLITE_SCHEMA = """

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    transcript TEXT DEFAULT '',
    analysis_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    owner TEXT DEFAULT '',
    deadline TEXT DEFAULT '',
    status TEXT DEFAULT 'Open',
    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL,
    decision TEXT NOT NULL,
    context TEXT DEFAULT '',
    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

"""


# =========================================================
# Database connection
# =========================================================

@contextmanager
def db():

    # -----------------------------------------------------
    # Render / PostgreSQL
    # -----------------------------------------------------

    if DATABASE_URL:

        import psycopg
        from psycopg.rows import dict_row

        con = psycopg.connect(
            DATABASE_URL,
            row_factory=dict_row
        )

        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

        return

    # -----------------------------------------------------
    # Local development / SQLite
    # -----------------------------------------------------

    db_path = os.getenv(
        "DATABASE_PATH",
        "meeting_memo.db"
    )

    con = sqlite3.connect(db_path)

    con.row_factory = sqlite3.Row

    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# =========================================================
# Initialize database
# =========================================================

def init_db():

    if DATABASE_URL:

        import psycopg

        with psycopg.connect(DATABASE_URL) as con:

            with con.cursor() as cur:

                for statement in POSTGRES_SCHEMA.split(";"):

                    statement = statement.strip()

                    if statement:
                        cur.execute(statement)

                # Add ownership to existing databases without removing data.
                cur.execute(
                    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS "
                    "owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE"
                )

            con.commit()

    else:

        with db() as con:

            con.executescript(SQLITE_SCHEMA)

            columns = {
                row["name"]
                for row in con.execute("PRAGMA table_info(projects)").fetchall()
            }
            if "owner_id" not in columns:
                con.execute(
                    "ALTER TABLE projects ADD COLUMN owner_id INTEGER "
                    "REFERENCES users(id) ON DELETE CASCADE"
                )


# =========================================================
# Seed initial project
# =========================================================

def seed():

    with db() as con:

        row = con.execute(
            "SELECT COUNT(*) AS count FROM projects"
        ).fetchone()

        count = (
            row["count"]
            if isinstance(row, dict)
            else row[0]
        )

        if count == 0:

            placeholder = "%s" if DATABASE_URL else "?"

            con.execute(
                f"""
                INSERT INTO projects(
                    name,
                    description
                )
                VALUES ({placeholder}, {placeholder})
                """,
                (
                    "Demo Project",
                    "Example project for Meeting Memo Expander Level 3"
                )
            )
