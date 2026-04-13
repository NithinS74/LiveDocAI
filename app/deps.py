"""
Shared FastAPI dependencies — reused across all routers.
"""
from typing import Optional
from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

bearer = HTTPBearer(auto_error=False)


def get_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> Optional[str]:
    """
    Extract user_id from JWT Bearer token.
    Returns None if no token — routes decide whether to require auth.
    """
    if not credentials:
        return None
    try:
        import jwt
        from app.config import get_settings
        settings = get_settings()
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=["HS256"]
        )
        return payload.get("sub")
    except Exception:
        return None
