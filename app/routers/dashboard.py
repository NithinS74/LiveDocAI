"""
Dashboard Router — user-isolated stats
GET /api/dashboard/stats
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, desc

from app.database import get_db
from app.models.api_log import APILog
from app.models.endpoint import Endpoint

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])
logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


def _get_user_id(credentials: Optional[HTTPAuthorizationCredentials]) -> Optional[str]:
    """Extract user_id from JWT without hard failing — dashboard can work without auth."""
    if not credentials:
        return None
    try:
        import jwt
        from app.config import get_settings
        settings = get_settings()
        payload = jwt.decode(credentials.credentials, settings.secret_key, algorithms=["HS256"])
        return payload.get("sub")
    except Exception:
        return None


@router.get("/stats")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
):
    user_id = _get_user_id(credentials)

    try:
        # ── Total endpoints ────────────────────────────────────────────────
        ep_q = select(func.count()).select_from(Endpoint)
        if user_id:
            ep_q = ep_q.where(Endpoint.user_id == user_id)
        total_endpoints = (await db.execute(ep_q)).scalar() or 0

        # ── Endpoints with drift ───────────────────────────────────────────
        drift_q = select(func.count()).select_from(Endpoint).where(Endpoint.has_drift.is_(True))
        if user_id:
            drift_q = drift_q.where(Endpoint.user_id == user_id)
        endpoints_with_drift = (await db.execute(drift_q)).scalar() or 0

        # ── Requests last 24h ─────────────────────────────────────────────
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(hours=24)
        req_q = select(func.count()).select_from(APILog).where(APILog.created_at >= cutoff)
        if user_id:
            req_q = req_q.where(APILog.user_id == user_id)
        total_requests_24h = (await db.execute(req_q)).scalar() or 0

        # ── Avg error rate ─────────────────────────────────────────────────
        err_q = select(
            func.count().label("total"),
            func.sum(case((APILog.status_code >= 400, 1), else_=0)).label("errors")
        ).select_from(APILog).where(APILog.created_at >= cutoff)
        if user_id:
            err_q = err_q.where(APILog.user_id == user_id)
        err_row = (await db.execute(err_q)).fetchone()
        total   = err_row.total or 0
        errors  = err_row.errors or 0
        avg_error_rate = (errors / total) if total > 0 else 0.0

        # ── Top endpoints ──────────────────────────────────────────────────
        top_q = (
            select(
                Endpoint.method,
                Endpoint.path_pattern,
                Endpoint.total_requests,
                Endpoint.avg_latency_ms,
                Endpoint.error_count,
                case(
                    (Endpoint.total_requests > 0,
                     Endpoint.error_count * 1.0 / Endpoint.total_requests),
                    else_=0.0
                ).label("error_rate"),
            )
            .order_by(desc(Endpoint.total_requests))
            .limit(10)
        )
        if user_id:
            top_q = top_q.where(Endpoint.user_id == user_id)
        top_rows = (await db.execute(top_q)).fetchall()

        top_endpoints = [
            {
                "method":        r.method,
                "path_pattern":  r.path_pattern,
                "total_requests": r.total_requests,
                "avg_latency_ms": round(r.avg_latency_ms or 0, 2),
                "error_count":   r.error_count,
                "error_rate":    round(float(r.error_rate or 0), 4),
            }
            for r in top_rows
        ]

        return {
            "total_endpoints":      total_endpoints,
            "endpoints_with_drift": endpoints_with_drift,
            "total_requests_24h":   total_requests_24h,
            "avg_error_rate":       round(avg_error_rate, 4),
            "top_endpoints":        top_endpoints,
        }

    except Exception as e:
        logger.error(f"[Dashboard] stats error: {e}")
        return {
            "total_endpoints":      0,
            "endpoints_with_drift": 0,
            "total_requests_24h":   0,
            "avg_error_rate":       0.0,
            "top_endpoints":        [],
        }
