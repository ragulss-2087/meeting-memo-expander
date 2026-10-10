"""Password hashing and database-backed bearer sessions."""

import base64
import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import DATABASE_URL, db


SESSION_DAYS = 14
PASSWORD_ITERATIONS = 310_000
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def new_session(con, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    placeholder = "%s" if DATABASE_URL else "?"
    con.execute(
        f"INSERT INTO sessions(token_hash, user_id, expires_at) "
        f"VALUES ({placeholder}, {placeholder}, {placeholder})",
        (token_hash, user_id, int(time.time()) + SESSION_DAYS * 24 * 60 * 60),
    )
    return token


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Please sign in to continue.")

    token_hash = hashlib.sha256(credentials.credentials.encode("utf-8")).hexdigest()
    placeholder = "%s" if DATABASE_URL else "?"

    with db() as con:
        row = con.execute(
            f"""
            SELECT users.id, users.email, sessions.token_hash
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = {placeholder}
              AND sessions.expires_at > {placeholder}
            """,
            (token_hash, int(time.time())),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Your session expired. Please sign in again.")

    return dict(row)
