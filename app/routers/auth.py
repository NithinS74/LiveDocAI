"""
Auth Router — JWT + API Key (FIXED VERSION)
────────────────────────────────────────────
POST /api/auth/signup  — create account, return JWT + api_key
POST /api/auth/signin  — verify credentials, return JWT + api_key
GET  /api/auth/me      — return current user from JWT
"""

import hashlib
import secrets
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import jwt

from app.database import get_db
from app.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["Auth"])
logger = logging.getLogger(__name__)
settings = get_settings()

bearer = HTTPBearer(auto_error=False)

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 7


# ── Schemas ────────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    name: str
    org: str = ""
    email: str
    password: str


class SigninRequest(BaseModel):
    email: str
    password: str


# ── Helpers ────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def create_jwt(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRY_DAYS),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired. Please sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")


def generate_api_key() -> str:
    return f"ldai_{secrets.token_hex(32)}"


# ── Dependency ─────────────────────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    payload = decode_jwt(credentials.credentials)

    return {
        "id": payload["sub"],
        "email": payload["email"]
    }


# ── Routes ────────────────────────────────────────────────────────────────

@router.post("/signup")
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):

    # check if user exists
    result = await db.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": body.email.lower().strip()}
    )

    if result.fetchone():
        raise HTTPException(status_code=400, detail="Email already registered.")

    user_id = str(uuid.uuid4())
    api_key = generate_api_key()
    token = create_jwt(user_id, body.email.lower().strip())

    # insert user (NO token column anymore)
    await db.execute(
        text("""
            INSERT INTO users (id, name, org, email, password, api_key)
            VALUES (:id, :name, :org, :email, :password, :api_key)
        """),
        {
            "id": user_id,
            "name": body.name.strip(),
            "org": body.org.strip(),
            "email": body.email.lower().strip(),
            "password": hash_password(body.password),
            "api_key": api_key,
        }
    )

    await db.commit()

    return {
        "token": token,
        "api_key": api_key,
        "name": body.name.strip(),
        "org": body.org.strip(),
        "email": body.email.lower().strip(),
        "user_id": user_id,
    }


@router.post("/signin")
async def signin(body: SigninRequest, db: AsyncSession = Depends(get_db)):

    result = await db.execute(
        text("""
            SELECT id, name, org, email, password, api_key
            FROM users
            WHERE email = :email
        """),
        {"email": body.email.lower().strip()}
    )

    row = result.fetchone()

    if not row or row.password != hash_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_jwt(row.id, row.email)
    api_key = row.api_key or generate_api_key()

    # ONLY update api_key (NOT token)
    await db.execute(
        text("""
            UPDATE users
            SET api_key = COALESCE(api_key, :api_key)
            WHERE id = :id
        """),
        {
            "api_key": api_key,
            "id": row.id
        }
    )

    await db.commit()

    return {
        "token": token,
        "api_key": api_key,
        "name": row.name,
        "org": row.org or "",
        "email": row.email,
        "user_id": row.id,
    }


@router.get("/me")
async def me(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    result = await db.execute(
        text("""
            SELECT id, name, org, email, api_key
            FROM users
            WHERE id = :id
        """),
        {"id": current_user["id"]}
    )

    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="User not found.")

    return {
        "user_id": row.id,
        "name": row.name,
        "org": row.org or "",
        "email": row.email,
        "api_key": row.api_key,
    }