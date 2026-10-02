import json

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .db import db, init_db, seed
from .llm import analyze, answer_question
from .stt import transcribe
from .exporter import docx_bytes, pdf_bytes


app = FastAPI(title="Meeting Memo Expander Level 3")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://meeting-memo-expander.vercel.app",
],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# PostgreSQL uses %s
# SQLite uses ?
PLACEHOLDER = "%s" if DATABASE_URL else "?"


@app.on_event("startup")
def startup():
    init_db()
    seed()


# ---------------------------------------------------------
# Request Models
# ---------------------------------------------------------

class ProjectIn(BaseModel):
    name: str
    description: str = ""


class MeetingIn(BaseModel):
    project_id: int
    title: str
    transcript: str


class QuestionIn(BaseModel):
    question: str
    history: list[dict] = []


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------
# Projects
# ---------------------------------------------------------

@app.get("/api/projects")
def projects():
    with db() as con:
        return [
            dict(x)
            for x in con.execute(
                "SELECT * FROM projects ORDER BY id DESC"
            )
        ]


@app.post("/api/projects")
def create_project(x: ProjectIn):
    with db() as con:

        if DATABASE_URL:
            cur = con.execute(
                """
                INSERT INTO projects(
                    name,
                    description
                )
                VALUES (%s, %s)
                RETURNING id
                """,
                (x.name, x.description)
            )
            project_id = cur.fetchone()["id"]

        else:
            cur = con.execute(
                """
                INSERT INTO projects(
                    name,
                    description
                )
                VALUES (?, ?)
                """,
                (x.name, x.description)
            )
            project_id = cur.lastrowid

        return {
            "id": project_id,
            "name": x.name
        }


# ---------------------------------------------------------
# Meetings
# ---------------------------------------------------------

@app.get("/api/meetings")
def meetings(project_id: int | None = None):
    with db() as con:

        if project_id:
            rows = con.execute(
                f"""
                SELECT *
                FROM meetings
                WHERE project_id={PLACEHOLDER}
                ORDER BY id DESC
                """,
                (project_id,)
            )
        else:
            rows = con.execute(
                "SELECT * FROM meetings ORDER BY id DESC"
            )

        return [dict(x) for x in rows]


@app.delete("/api/meetings/{mid}")
def delete_meeting(mid: int):
    """Delete one meeting and all tasks/decisions belonging to it."""

    with db() as con:

        row = con.execute(
            f"""
            SELECT id
            FROM meetings
            WHERE id={PLACEHOLDER}
            """,
            (mid,)
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Meeting not found"
            )

        con.execute(
            f"DELETE FROM tasks WHERE meeting_id={PLACEHOLDER}",
            (mid,)
        )

        con.execute(
            f"DELETE FROM decisions WHERE meeting_id={PLACEHOLDER}",
            (mid,)
        )

        con.execute(
            f"DELETE FROM meetings WHERE id={PLACEHOLDER}",
            (mid,)
        )

    return {
        "ok": True,
        "deleted_meeting_id": mid
    }


@app.get("/api/meetings/{mid}")
def meeting(mid: int):
    with db() as con:

        row = con.execute(
            f"""
            SELECT *
            FROM meetings
            WHERE id={PLACEHOLDER}
            """,
            (mid,)
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Meeting not found"
            )

        return dict(row)


@app.post("/api/meetings")
async def create_meeting(x: MeetingIn):

    try:
        analysis = await analyze(x.transcript)

    except RuntimeError as e:
        raise HTTPException(
            status_code=429,
            detail=str(e)
        )

    with db() as con:

        # -------------------------------------------------
        # Save Meeting
        # -------------------------------------------------

        if DATABASE_URL:

            cur = con.execute(
                """
                INSERT INTO meetings(
                    project_id,
                    title,
                    transcript,
                    analysis_json
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (
                    x.project_id,
                    x.title,
                    x.transcript,
                    json.dumps(analysis)
                )
            )

            mid = cur.fetchone()["id"]

        else:

            cur = con.execute(
                """
                INSERT INTO meetings(
                    project_id,
                    title,
                    transcript,
                    analysis_json
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    x.project_id,
                    x.title,
                    x.transcript,
                    json.dumps(analysis)
                )
            )

            mid = cur.lastrowid

        # -------------------------------------------------
        # Save Action Items
        # -------------------------------------------------

        for a in analysis.get("action_items", []):

            if isinstance(a, dict):
                title = a.get("title", "")
                owner = a.get("owner", "")
                deadline = a.get("deadline", "")
            else:
                title = str(a)
                owner = ""
                deadline = ""

            con.execute(
                f"""
                INSERT INTO tasks(
                    meeting_id,
                    title,
                    owner,
                    deadline
                )
                VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
                """,
                (
                    mid,
                    title,
                    owner,
                    deadline
                )
            )

        # -------------------------------------------------
        # Save Decisions
        # -------------------------------------------------

        for d in analysis.get("decisions", []):

            if isinstance(d, dict):
                decision = d.get("decision", "")
                context = d.get("context", "")
            else:
                decision = str(d)
                context = ""

            con.execute(
                f"""
                INSERT INTO decisions(
                    meeting_id,
                    decision,
                    context
                )
                VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
                """,
                (
                    mid,
                    decision,
                    context
                )
            )

    return {
        "id": mid,
        "analysis": analysis
    }


# ---------------------------------------------------------
# Speech-to-Text
# ---------------------------------------------------------

@app.post("/api/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...)
):
    try:

        return {
            "text": await transcribe(file)
        }

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=str(e)
        )


# ---------------------------------------------------------
# Tasks
# ---------------------------------------------------------

@app.get("/api/tasks")
def tasks():

    with db() as con:

        return [
            dict(x)
            for x in con.execute(
                """
                SELECT
                    t.*,
                    m.title meeting_title
                FROM tasks t
                JOIN meetings m
                    ON m.id = t.meeting_id
                ORDER BY t.id DESC
                """
            )
        ]


@app.patch("/api/tasks/{tid}")
def update_task(
    tid: int,
    status: str
):

    with db() as con:

        con.execute(
            f"""
            UPDATE tasks
            SET status={PLACEHOLDER}
            WHERE id={PLACEHOLDER}
            """,
            (status, tid)
        )

        return {
            "ok": True
        }


# ---------------------------------------------------------
# Decisions
# ---------------------------------------------------------

@app.get("/api/decisions")
def decisions():

    with db() as con:

        return [
            dict(x)
            for x in con.execute(
                """
                SELECT
                    d.*,
                    m.title meeting_title
                FROM decisions d
                JOIN meetings m
                    ON m.id = d.meeting_id
                ORDER BY d.id DESC
                """
            )
        ]


# ---------------------------------------------------------
# Search
# ---------------------------------------------------------

@app.get("/api/search")
def search(q: str):

    with db() as con:

        like = f"%{q}%"

        meetings_result = [
            dict(x)
            for x in con.execute(
                f"""
                SELECT
                    id,
                    title,
                    created_at
                FROM meetings
                WHERE title LIKE {PLACEHOLDER}
                   OR transcript LIKE {PLACEHOLDER}
                ORDER BY id DESC
                """,
                (like, like)
            )
        ]

        tasks_result = [
            dict(x)
            for x in con.execute(
                f"""
                SELECT
                    id,
                    title,
                    owner,
                    status
                FROM tasks
                WHERE title LIKE {PLACEHOLDER}
                   OR owner LIKE {PLACEHOLDER}
                ORDER BY id DESC
                """,
                (like, like)
            )
        ]

        return {
            "meetings": meetings_result,
            "tasks": tasks_result
        }


# ---------------------------------------------------------
# Ask Question About Meeting
# ---------------------------------------------------------

@app.post("/api/meetings/{mid}/ask")
async def ask(
    mid: int,
    x: QuestionIn
):

    with db() as con:

        row = con.execute(
            f"""
            SELECT transcript
            FROM meetings
            WHERE id={PLACEHOLDER}
            """,
            (mid,)
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found"
        )

    try:

        answer = await answer_question(
            x.question,
            row["transcript"],
            x.history
        )

        return {
            "answer": answer
        }

    except RuntimeError as e:

        raise HTTPException(
            status_code=429,
            detail=str(e)
        )


# ---------------------------------------------------------
# Export Meeting
# ---------------------------------------------------------

@app.get("/api/meetings/{mid}/export/{kind}")
def export(
    mid: int,
    kind: str
):

    with db() as con:

        row = con.execute(
            f"""
            SELECT
                title,
                analysis_json
            FROM meetings
            WHERE id={PLACEHOLDER}
            """,
            (mid,)
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found"
        )

    analysis = json.loads(
        row["analysis_json"] or "{}"
    )

    # -----------------------------------------------------
    # DOCX
    # -----------------------------------------------------

    if kind == "docx":

        data = docx_bytes(
            row["title"],
            analysis
        )

        return StreamingResponse(
            data,
            media_type=(
                "application/vnd.openxmlformats-"
                "officedocument.wordprocessingml.document"
            ),
            headers={
                "Content-Disposition":
                    f'attachment; filename="meeting_{mid}.docx"'
            }
        )

    # -----------------------------------------------------
    # PDF
    # -----------------------------------------------------

    if kind == "pdf":

        data = pdf_bytes(
            row["title"],
            analysis
        )

        return StreamingResponse(
            data,
            media_type="application/pdf",
            headers={
                "Content-Disposition":
                    f'attachment; filename="meeting_{mid}.pdf"'
            }
        )

    raise HTTPException(
        status_code=400,
        detail="Use docx or pdf"
    )