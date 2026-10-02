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

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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

            con.commit()

    else:

        with db() as con:

            con.executescript(SQLITE_SCHEMA)


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