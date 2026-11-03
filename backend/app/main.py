import hashlib
import json
import os
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage

from fastapi import Depends, FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .db import db, init_db
from .security import get_current_user, hash_password, new_session, verify_password
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


# =========================================================
# MODELS
# =========================================================

class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class AuthRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class MeetingCreate(BaseModel):
    project_id: int
    title: str
    transcript: str = ""


class TaskUpdate(BaseModel):
    status: str


class AskRequest(BaseModel):
    question: str
    history: list = []


def require_owned_project(con, project_id: int, user_id: int):
    row = con.execute(
        f"SELECT id FROM projects WHERE id = {PLACEHOLDER} AND owner_id = {PLACEHOLDER}",
        (project_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


def require_owned_meeting(con, meeting_id: int, user_id: int):
    row = con.execute(
        f"""
        SELECT meetings.id
        FROM meetings
        JOIN projects ON projects.id = meetings.project_id
        WHERE meetings.id = {PLACEHOLDER} AND projects.owner_id = {PLACEHOLDER}
        """,
        (meeting_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return row


# =========================================================
# HEALTH
# =========================================================

@app.get("/api/health")
def health():

    return {
        "status": "ok",
        "database": "PostgreSQL" if DATABASE_URL else "SQLite"
    }


@app.post("/api/auth/register")
def register(account: AuthRequest):
    email = account.email.strip().lower()
    if len(email) > 254 or email.count("@") != 1 or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=422, detail="Enter a valid email address.")

    placeholder = PLACEHOLDER
    with db() as con:
        existing = con.execute(
            f"SELECT id FROM users WHERE email = {placeholder}", (email,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="An account with this email already exists.")

        if DATABASE_URL:
            user = con.execute(
                f"INSERT INTO users(email, password_hash) VALUES ({placeholder}, {placeholder}) RETURNING id, email",
                (email, hash_password(account.password)),
            ).fetchone()
            user_id = user["id"]
        else:
            cursor = con.execute(
                f"INSERT INTO users(email, password_hash) VALUES ({placeholder}, {placeholder})",
                (email, hash_password(account.password)),
            )
            user_id = cursor.lastrowid

        # Give every new account a private project so the dashboard is ready to use.
        con.execute(
            f"INSERT INTO projects(owner_id, name, description) VALUES ({placeholder}, {placeholder}, {placeholder})",
            (user_id, "My Project", "Your private meeting workspace"),
        )
        token = new_session(con, user_id)

    return {"access_token": token, "token_type": "bearer", "user": {"id": user_id, "email": email}}


@app.post("/api/auth/login")
def login(account: AuthRequest):
    email = account.email.strip().lower()
    with db() as con:
        row = con.execute(
            f"SELECT id, email, password_hash FROM users WHERE email = {PLACEHOLDER}",
            (email,),
        ).fetchone()
        if not row or not verify_password(account.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Email or password is incorrect.")
        token = new_session(con, row["id"])

    return {"access_token": token, "token_type": "bearer", "user": {"id": row["id"], "email": row["email"]}}


def send_password_reset_email(recipient: str, reset_url: str):
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_from = os.getenv("SMTP_FROM", "").strip() or os.getenv("SMTP_USER", "").strip()
    if not smtp_host or not smtp_from:
        raise RuntimeError("Password reset email is not configured. Set SMTP_HOST and SMTP_FROM.")

    message = EmailMessage()
    message["Subject"] = "Reset your Meeting Memo Expander password"
    message["From"] = smtp_from
    message["To"] = recipient
    message.set_content(
        "We received a request to reset your password.\n\n"
        f"Open this one-time link within 30 minutes: {reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )

    host = smtp_host
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    use_ssl = os.getenv("SMTP_USE_SSL", "false").strip().lower() in {"1", "true", "yes"}
    use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes"}
    context = ssl.create_default_context()

    if use_ssl:
        smtp_connection = smtplib.SMTP_SSL(host, port, timeout=20, context=context)
    else:
        smtp_connection = smtplib.SMTP(host, port, timeout=20)

    with smtp_connection as server:
        if use_tls and not use_ssl:
            server.starttls(context=context)
        if username:
            server.login(username, password)
        server.send_message(message)


@app.post("/api/auth/forgot-password")
def forgot_password(request: ForgotPasswordRequest):
    email = request.email.strip().lower()
    token = None
    try:
        with db() as con:
            row = con.execute(
                f"SELECT id FROM users WHERE email = {PLACEHOLDER}", (email,)
            ).fetchone()
            if row:
                token = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
                con.execute(
                    f"DELETE FROM password_reset_tokens WHERE user_id = {PLACEHOLDER}",
                    (row["id"],),
                )
                con.execute(
                    f"INSERT INTO password_reset_tokens(token_hash, user_id, expires_at) "
                    f"VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})",
                    (token_hash, row["id"], int(time.time()) + 30 * 60),
                )

        if token:
            frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
            send_password_reset_email(email, f"{frontend_url}/?reset_token={token}")
    except Exception as error:
        if token:
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            with db() as con:
                con.execute(
                    f"DELETE FROM password_reset_tokens WHERE token_hash = {PLACEHOLDER}",
                    (token_hash,),
                )
        raise HTTPException(
            status_code=503,
            detail="Could not send the reset email. Check the server email settings and try again.",
        ) from error

    return {"message": "If an account exists for that email, a password reset link has been sent."}


@app.post("/api/auth/reset-password")
def reset_password(request: ResetPasswordRequest):
    token_hash = hashlib.sha256(request.token.encode("utf-8")).hexdigest()
    with db() as con:
        row = con.execute(
            f"SELECT user_id FROM password_reset_tokens "
            f"WHERE token_hash = {PLACEHOLDER} AND expires_at > {PLACEHOLDER}",
            (token_hash, int(time.time())),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")

        consumed = con.execute(
            f"DELETE FROM password_reset_tokens WHERE token_hash = {PLACEHOLDER}",
            (token_hash,),
        )
        if consumed.rowcount != 1:
            raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")

        con.execute(
            f"UPDATE users SET password_hash = {PLACEHOLDER} WHERE id = {PLACEHOLDER}",
            (hash_password(request.password), row["user_id"]),
        )
        con.execute(f"DELETE FROM sessions WHERE user_id = {PLACEHOLDER}", (row["user_id"],))
        con.execute(
            f"DELETE FROM password_reset_tokens WHERE user_id = {PLACEHOLDER}",
            (row["user_id"],),
        )

    return {"message": "Password changed. You can now sign in with your new password."}


@app.get("/api/auth/me")
def who_am_i(user: dict = Depends(get_current_user)):
    return {"id": user["id"], "email": user["email"]}


@app.post("/api/auth/logout")
def logout(user: dict = Depends(get_current_user)):
    with db() as con:
        con.execute(
            f"DELETE FROM sessions WHERE token_hash = {PLACEHOLDER}",
            (user["token_hash"],),
        )
    return {"message": "Signed out."}


# =========================================================
# PROJECTS
# =========================================================

@app.get("/api/projects")
def get_projects(user: dict = Depends(get_current_user)):

    with db() as con:

        rows = con.execute(
            f"""
            SELECT
                id,
                name,
                description,
                created_at
            FROM projects
            WHERE owner_id = {PLACEHOLDER}
            ORDER BY id
            """,
            (user["id"],),
        ).fetchall()

        return [dict(row) for row in rows]


@app.post("/api/projects")
def create_project(project: ProjectCreate, user: dict = Depends(get_current_user)):

    with db() as con:

        if DATABASE_URL:

            row = con.execute(
                f"""
                INSERT INTO projects(
                    owner_id,
                    name,
                    description
                )
                VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
                RETURNING id
                """,
                (
                    user["id"],
                    project.name,
                    project.description
                )
            ).fetchone()

            project_id = row["id"]

        else:

            cursor = con.execute(
                f"""
                INSERT INTO projects(
                    owner_id,
                    name,
                    description
                )
                VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
                """,
                (
                    user["id"],
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
def get_meetings(project_id: int, user: dict = Depends(get_current_user)):

    with db() as con:

        rows = con.execute(
            f"""
            SELECT
                meetings.id,
                meetings.project_id,
                meetings.title,
                meetings.transcript,
                meetings.analysis_json,
                meetings.created_at
            FROM meetings
            JOIN projects ON projects.id = meetings.project_id
            WHERE meetings.project_id = {PLACEHOLDER}
              AND projects.owner_id = {PLACEHOLDER}
            ORDER BY meetings.id DESC
            """,
            (project_id, user["id"])
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
def get_meeting(meeting_id: int, user: dict = Depends(get_current_user)):

    with db() as con:

        row = con.execute(
            f"""
            SELECT
                meetings.id,
                meetings.project_id,
                meetings.title,
                meetings.transcript,
                meetings.analysis_json,
                meetings.created_at
            FROM meetings
            JOIN projects ON projects.id = meetings.project_id
            WHERE meetings.id = {PLACEHOLDER}
              AND projects.owner_id = {PLACEHOLDER}
            """,
            (meeting_id, user["id"])
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
async def create_meeting(meeting: MeetingCreate, user: dict = Depends(get_current_user)):

    with db() as con:
        require_owned_project(con, meeting.project_id, user["id"])

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
def delete_meeting(meeting_id: int, user: dict = Depends(get_current_user)):

    with db() as con:

        meeting = con.execute(
            f"""
            SELECT meetings.id
            FROM meetings
            JOIN projects ON projects.id = meetings.project_id
            WHERE meetings.id = {PLACEHOLDER}
              AND projects.owner_id = {PLACEHOLDER}
            """,
            (meeting_id, user["id"])
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
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
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
            file.filename or "audio.webm",
            file.content_type or "application/octet-stream",
        )

        return {"text": text}

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
def get_tasks(meeting_id: int, user: dict = Depends(get_current_user)):

    with db() as con:

        require_owned_meeting(con, meeting_id, user["id"])

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
    task: TaskUpdate,
    user: dict = Depends(get_current_user),
):

    with db() as con:

        existing = con.execute(
            f"""
            SELECT tasks.id
            FROM tasks
            JOIN meetings ON meetings.id = tasks.meeting_id
            JOIN projects ON projects.id = meetings.project_id
            WHERE tasks.id = {PLACEHOLDER}
              AND projects.owner_id = {PLACEHOLDER}
            """,
            (task_id, user["id"])
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
def get_decisions(meeting_id: int, user: dict = Depends(get_current_user)):

    with db() as con:

        require_owned_meeting(con, meeting_id, user["id"])

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
    project_id: int | None = None,
    user: dict = Depends(get_current_user),
):

    search_text = f"%{q}%"

    with db() as con:

        if project_id is not None:

            rows = con.execute(
                f"""
                SELECT
                meetings.id,
                meetings.project_id,
                meetings.title,
                meetings.transcript,
                meetings.analysis_json,
                meetings.created_at
                FROM meetings
                JOIN projects ON projects.id = meetings.project_id
                WHERE meetings.project_id = {PLACEHOLDER}
                AND projects.owner_id = {PLACEHOLDER}
                AND (
                    meetings.title LIKE {PLACEHOLDER}
                    OR meetings.transcript LIKE {PLACEHOLDER}
                )
                ORDER BY meetings.id DESC
                """,
                (
                    project_id,
                    user["id"],
                    search_text,
                    search_text
                )
            ).fetchall()

        else:

            rows = con.execute(
                f"""
                SELECT
                    meetings.id,
                    meetings.project_id,
                    meetings.title,
                    meetings.transcript,
                    meetings.analysis_json,
                    meetings.created_at
                FROM meetings
                JOIN projects ON projects.id = meetings.project_id
                WHERE projects.owner_id = {PLACEHOLDER}
                AND (
                    meetings.title LIKE {PLACEHOLDER}
                    OR meetings.transcript LIKE {PLACEHOLDER}
                )
                ORDER BY meetings.id DESC
                """,
                (
                    user["id"],
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
    x: AskRequest,
    user: dict = Depends(get_current_user),
):

    with db() as con:

        row = con.execute(
            f"""
            SELECT
                meetings.id,
                title,
                transcript,
                analysis_json
            FROM meetings
            JOIN projects ON projects.id = meetings.project_id
            WHERE meetings.id = {PLACEHOLDER}
              AND projects.owner_id = {PLACEHOLDER}
            """,
            (meeting_id, user["id"])
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
def export_docx(meeting_id: int, user: dict = Depends(get_current_user)):

    with db() as con:

        row = con.execute(
            f"""
            SELECT
                meetings.id,
                title,
                transcript,
                analysis_json
            FROM meetings
            JOIN projects ON projects.id = meetings.project_id
            WHERE meetings.id = {PLACEHOLDER}
              AND projects.owner_id = {PLACEHOLDER}
            """,
            (meeting_id, user["id"])
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
        meeting["title"],
        analysis,
        meeting.get("transcript", ""),
    )

    return StreamingResponse(
        iter([data.getvalue()]),
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
def export_pdf(meeting_id: int, user: dict = Depends(get_current_user)):

    with db() as con:

        row = con.execute(
            f"""
            SELECT
                meetings.id,
                title,
                transcript,
                analysis_json
            FROM meetings
            JOIN projects ON projects.id = meetings.project_id
            WHERE meetings.id = {PLACEHOLDER}
              AND projects.owner_id = {PLACEHOLDER}
            """,
            (meeting_id, user["id"])
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
        meeting["title"],
        analysis,
        meeting.get("transcript", ""),
    )

    return StreamingResponse(
        iter([data.getvalue()]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{meeting["title"]}.pdf"'
            )
        }
    )
