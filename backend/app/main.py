import json
import os

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .db import db, init_db, seed
from .llm import analyze, answer_question
from .stt import transcribe
from .exporter import docx_bytes, pdf_bytes


# =========================================================
# DATABASE CONFIGURATION
# =========================================================

DATABASE_URL = os.getenv("DATABASE_URL")

print(
    "DATABASE MODE:",
    "PostgreSQL" if DATABASE_URL else "SQLite"
)

PLACEHOLDER = "%s" if DATABASE_URL else "?"


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(
    title="Meeting Memo Expander Level 3"
)


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://meeting-memo-expander.vercel.app",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
def startup():

    init_db()
    seed()


# =========================================================
# MODELS
# =========================================================

class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class MeetingCreate(BaseModel):
    project_id: int
    title: str
    transcript: str = ""


class TaskUpdate(BaseModel):
    status: str


class AskRequest(BaseModel):
    question: str
    history: list = []


# =========================================================
# HEALTH
# =========================================================

@app.get("/api/health")
def health():

    return {
        "status": "ok",
        "database": "PostgreSQL" if DATABASE_URL else "SQLite"
    }


# =========================================================
# PROJECTS
# =========================================================

@app.get("/api/projects")
def get_projects():

    with db() as con:

        rows = con.execute(
            """
            SELECT
                id,
                name,
                description,
                created_at
            FROM projects
            ORDER BY id
            """
        ).fetchall()

        return [dict(row) for row in rows]


@app.post("/api/projects")
def create_project(project: ProjectCreate):

    with db() as con:

        if DATABASE_URL:

            row = con.execute(
                f"""
                INSERT INTO projects(
                    name,
                    description
                )
                VALUES ({PLACEHOLDER}, {PLACEHOLDER})
                RETURNING id
                """,
                (
                    project.name,
                    project.description
                )
            ).fetchone()

            project_id = row["id"]

        else:

            cursor = con.execute(
                f"""
                INSERT INTO projects(
                    name,
                    description
                )
                VALUES ({PLACEHOLDER}, {PLACEHOLDER})
                """,
                (
                    project.name,
                    project.description
                )
            )

            project_id = cursor.lastrowid

        return {
            "id": project_id,
            "name": project.name,
            "description": project.description
        }


# =========================================================
# MEETINGS
# =========================================================

@app.get("/api/meetings")
def get_meetings(project_id: int):

    with db() as con:

        rows = con.execute(
            f"""
            SELECT
                id,
                project_id,
                title,
                transcript,
                analysis_json,
                created_at
            FROM meetings
            WHERE project_id = {PLACEHOLDER}
            ORDER BY id DESC
            """,
            (project_id,)
        ).fetchall()

        result = []

        for row in rows:

            item = dict(row)

            try:
                item["analysis"] = json.loads(
                    item.get("analysis_json") or "{}"
                )
            except Exception:
                item["analysis"] = {}

            result.append(item)

        return result


@app.get("/api/meetings/{meeting_id}")
def get_meeting(meeting_id: int):

    with db() as con:

        row = con.execute(
            f"""
            SELECT
                id,
                project_id,
                title,
                transcript,
                analysis_json,
                created_at
            FROM meetings
            WHERE id = {PLACEHOLDER}
            """,
            (meeting_id,)
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Meeting not found"
            )

        item = dict(row)

        try:
            item["analysis"] = json.loads(
                item.get("analysis_json") or "{}"
            )
        except Exception:
            item["analysis"] = {}

        return item


@app.post("/api/meetings")
async def create_meeting(meeting: MeetingCreate):

    transcript = meeting.transcript or ""

    # -----------------------------------------------------
    # AI ANALYSIS
    # -----------------------------------------------------

    try:

        result = await analyze(transcript)

    except Exception as e:

        print(
            "AI ANALYSIS ERROR:",
            str(e)
        )

        # -------------------------------------------------
        # IMPORTANT:
        # If Gemini quota is exhausted, the meeting is
        # still saved instead of failing completely.
        # -------------------------------------------------

        result = {
            "summary": "AI analysis is temporarily unavailable.",
            "decisions": [],
            "action_items": [],
            "risks": [],
            "follow_up_questions": []
        }

    analysis_json = json.dumps(
        result,
        ensure_ascii=False
    )

    # =====================================================
    # SAVE MEETING
    # =====================================================

    with db() as con:

        if DATABASE_URL:

            row = con.execute(
                f"""
                INSERT INTO meetings(
                    project_id,
                    title,
                    transcript,
                    analysis_json
                )
                VALUES (
                    {PLACEHOLDER},
                    {PLACEHOLDER},
                    {PLACEHOLDER},
                    {PLACEHOLDER}
                )
                RETURNING id
                """,
                (
                    meeting.project_id,
                    meeting.title,
                    transcript,
                    analysis_json
                )
            ).fetchone()

            meeting_id = row["id"]

        else:

            cursor = con.execute(
                f"""
                INSERT INTO meetings(
                    project_id,
                    title,
                    transcript,
                    analysis_json
                )
                VALUES (
                    {PLACEHOLDER},
                    {PLACEHOLDER},
                    {PLACEHOLDER},
                    {PLACEHOLDER}
                )
                """,
                (
                    meeting.project_id,
                    meeting.title,
                    transcript,
                    analysis_json
                )
            )

            meeting_id = cursor.lastrowid

        # =================================================
        # SAVE ACTION ITEMS
        # =================================================

        action_items = result.get(
            "action_items",
            []
        )

        for item in action_items:

            if isinstance(item, dict):

                title = (
                    item.get("title")
                    or item.get("task")
                    or item.get("action")
                    or ""
                )

                owner = (
                    item.get("owner")
                    or ""
                )

                deadline = (
                    item.get("deadline")
                    or ""
                )

            else:

                title = str(item)
                owner = ""
                deadline = ""

            if title:

                con.execute(
                    f"""
                    INSERT INTO tasks(
                        meeting_id,
                        title,
                        owner,
                        deadline,
                        status
                    )
                    VALUES (
                        {PLACEHOLDER},
                        {PLACEHOLDER},
                        {PLACEHOLDER},
                        {PLACEHOLDER},
                        {PLACEHOLDER}
                    )
                    """,
                    (
                        meeting_id,
                        title,
                        owner,
                        deadline,
                        "Open"
                    )
                )

        # =================================================
        # SAVE DECISIONS
        # =================================================

        decisions = result.get(
            "decisions",
            []
        )

        for decision in decisions:

            if isinstance(decision, dict):

                decision_text = (
                    decision.get("decision")
                    or decision.get("title")
                    or decision.get("text")
                    or ""
                )

                context = (
                    decision.get("context")
                    or ""
                )

            else:

                decision_text = str(decision)
                context = ""

            if decision_text:

                con.execute(
                    f"""
                    INSERT INTO decisions(
                        meeting_id,
                        decision,
                        context
                    )
                    VALUES (
                        {PLACEHOLDER},
                        {PLACEHOLDER},
                        {PLACEHOLDER}
                    )
                    """,
                    (
                        meeting_id,
                        decision_text,
                        context
                    )
                )

    # =====================================================
    # RESPONSE
    # =====================================================

    return {
        "id": meeting_id,
        "project_id": meeting.project_id,
        "title": meeting.title,
        "transcript": transcript,
        "analysis": result
    }


# =========================================================
# DELETE MEETING
# =========================================================

@app.delete("/api/meetings/{meeting_id}")
def delete_meeting(meeting_id: int):

    with db() as con:

        meeting = con.execute(
            f"""
            SELECT id
            FROM meetings
            WHERE id = {PLACEHOLDER}
            """,
            (meeting_id,)
        ).fetchone()

        if not meeting:

            raise HTTPException(
                status_code=404,
                detail="Meeting not found"
            )

        con.execute(
            f"""
            DELETE FROM tasks
            WHERE meeting_id = {PLACEHOLDER}
            """,
            (meeting_id,)
        )

        con.execute(
            f"""
            DELETE FROM decisions
            WHERE meeting_id = {PLACEHOLDER}
            """,
            (meeting_id,)
        )

        con.execute(
            f"""
            DELETE FROM meetings
            WHERE id = {PLACEHOLDER}
            """,
            (meeting_id,)
        )

        return {
            "message": "Meeting deleted successfully"
        }


# =========================================================
# TRANSCRIPTION
# =========================================================

@app.post("/api/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...)
):

    audio_bytes = await file.read()

    if not audio_bytes:

        raise HTTPException(
            status_code=400,
            detail="Empty audio file"
        )

    try:

        text = await transcribe(
            audio_bytes,
            file.filename or "audio.webm"
        )

        return {
            "transcript": text
        }

    except Exception as e:

        print(
            "TRANSCRIPTION ERROR:",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# =========================================================
# TASKS
# =========================================================

@app.get("/api/meetings/{meeting_id}/tasks")
def get_tasks(meeting_id: int):

    with db() as con:

        rows = con.execute(
            f"""
            SELECT
                id,
                meeting_id,
                title,
                owner,
                deadline,
                status
            FROM tasks
            WHERE meeting_id = {PLACEHOLDER}
            ORDER BY id
            """,
            (meeting_id,)
        ).fetchall()

        return [dict(row) for row in rows]


@app.patch("/api/tasks/{task_id}")
def update_task(
    task_id: int,
    task: TaskUpdate
):

    with db() as con:

        existing = con.execute(
            f"""
            SELECT id
            FROM tasks
            WHERE id = {PLACEHOLDER}
            """,
            (task_id,)
        ).fetchone()

        if not existing:

            raise HTTPException(
                status_code=404,
                detail="Task not found"
            )

        con.execute(
            f"""
            UPDATE tasks
            SET status = {PLACEHOLDER}
            WHERE id = {PLACEHOLDER}
            """,
            (
                task.status,
                task_id
            )
        )

        return {
            "message": "Task updated successfully",
            "id": task_id,
            "status": task.status
        }


# =========================================================
# DECISIONS
# =========================================================

@app.get("/api/meetings/{meeting_id}/decisions")
def get_decisions(meeting_id: int):

    with db() as con:

        rows = con.execute(
            f"""
            SELECT
                id,
                meeting_id,
                decision,
                context
            FROM decisions
            WHERE meeting_id = {PLACEHOLDER}
            ORDER BY id
            """,
            (meeting_id,)
        ).fetchall()

        return [dict(row) for row in rows]


# =========================================================
# SEARCH
# =========================================================

@app.get("/api/search")
def search(
    q: str,
    project_id: int | None = None
):

    search_text = f"%{q}%"

    with db() as con:

        if project_id is not None:

            rows = con.execute(
                f"""
                SELECT
                    id,
                    project_id,
                    title,
                    transcript,
                    analysis_json,
                    created_at
                FROM meetings
                WHERE project_id = {PLACEHOLDER}
                AND (
                    title LIKE {PLACEHOLDER}
                    OR transcript LIKE {PLACEHOLDER}
                )
                ORDER BY id DESC
                """,
                (
                    project_id,
                    search_text,
                    search_text
                )
            ).fetchall()

        else:

            rows = con.execute(
                f"""
                SELECT
                    id,
                    project_id,
                    title,
                    transcript,
                    analysis_json,
                    created_at
                FROM meetings
                WHERE (
                    title LIKE {PLACEHOLDER}
                    OR transcript LIKE {PLACEHOLDER}
                )
                ORDER BY id DESC
                """,
                (
                    search_text,
                    search_text
                )
            ).fetchall()

        result = []

        for row in rows:

            item = dict(row)

            try:
                item["analysis"] = json.loads(
                    item.get("analysis_json") or "{}"
                )
            except Exception:
                item["analysis"] = {}

            result.append(item)

        return result


# =========================================================
# MEETING AI Q&A
# =========================================================

@app.post("/api/meetings/{meeting_id}/ask")
async def ask_meeting_question(
    meeting_id: int,
    x: AskRequest
):

    with db() as con:

        row = con.execute(
            f"""
            SELECT
                id,
                title,
                transcript,
                analysis_json
            FROM meetings
            WHERE id = {PLACEHOLDER}
            """,
            (meeting_id,)
        ).fetchone()

        if not row:

            raise HTTPException(
                status_code=404,
                detail="Meeting not found"
            )

        transcript = row["transcript"]

        analysis_json = row["analysis_json"] or "{}"

        context = (
            "Meeting title: "
            + row["title"]
            + "\n\n"
            + "Transcript:\n"
            + transcript
            + "\n\n"
            + "Analysis:\n"
            + analysis_json
        )

    try:

        answer = await answer_question(
            x.question,
            context,
            x.history
        )

        return answer

    except Exception as e:

        print(
            "AI QUESTION ERROR:",
            str(e)
        )

        raise HTTPException(
            status_code=429,
            detail="Gemini quota reached. Please try again after the quota resets."
        )


# =========================================================
# DOCX EXPORT
# =========================================================

@app.get("/api/meetings/{meeting_id}/export/docx")
def export_docx(meeting_id: int):

    with db() as con:

        row = con.execute(
            f"""
            SELECT
                id,
                title,
                transcript,
                analysis_json
            FROM meetings
            WHERE id = {PLACEHOLDER}
            """,
            (meeting_id,)
        ).fetchone()

        if not row:

            raise HTTPException(
                status_code=404,
                detail="Meeting not found"
            )

        meeting = dict(row)

    try:

        analysis = json.loads(
            meeting.get("analysis_json") or "{}"
        )

    except Exception:

        analysis = {}

    data = docx_bytes(
        meeting,
        analysis
    )

    return StreamingResponse(
        iter([data]),
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{meeting["title"]}.docx"'
            )
        }
    )


# =========================================================
# PDF EXPORT
# =========================================================

@app.get("/api/meetings/{meeting_id}/export/pdf")
def export_pdf(meeting_id: int):

    with db() as con:

        row = con.execute(
            f"""
            SELECT
                id,
                title,
                transcript,
                analysis_json
            FROM meetings
            WHERE id = {PLACEHOLDER}
            """,
            (meeting_id,)
        ).fetchone()

        if not row:

            raise HTTPException(
                status_code=404,
                detail="Meeting not found"
            )

        meeting = dict(row)

    try:

        analysis = json.loads(
            meeting.get("analysis_json") or "{}"
        )

    except Exception:

        analysis = {}

    data = pdf_bytes(
        meeting,
        analysis
    )

    return StreamingResponse(
        iter([data]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{meeting["title"]}.pdf"'
            )
        }
    )