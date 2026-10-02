import os, sqlite3
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DATABASE_PATH", "meeting_memo.db")

SCHEMA = """
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

@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()

def init_db():
    with db() as con:
        con.executescript(SCHEMA)

def seed():
    with db() as con:
        if con.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0:
            con.execute("INSERT INTO projects(name, description) VALUES (?,?)",
                        ("Demo Project", "Example project for Meeting Memo Expander Level 3"))
