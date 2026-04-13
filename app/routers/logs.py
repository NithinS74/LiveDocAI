"""
Logs Router — user-isolated
GET /api/logs/          — paginated logs for current user
GET /api/logs/errors    — error logs for current user
GET /api/logs/stats     — aggregate stats for current user
GET /api/logs/{id}      — single log by id
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import LogFilterParams
from app.services.log_service import LogService
from app.deps import get_user_id

router = APIRouter(prefix="/api/logs", tags=["Logs"])
logger = logging.getLogger(__name__)


@router.get("/")
async def get_logs(
    limit:  int = Query(100, le=500),
    offset: int = Query(0),
    method: Optional[str] = None,
    path:   Optional[str] = None,
    db:     AsyncSession  = Depends(get_db),
    user_id: Optional[str] = Depends(get_user_id),
):
    svc     = LogService(db, user_id=user_id)
    filters = LogFilterParams(limit=limit, offset=offset, method=method, path=path)
    logs    = await svc.get_logs(filters)
    return [_serialize(l) for l in logs]


@router.get("/errors")
async def get_error_logs(
    hours:   int          = Query(24),
    path:    Optional[str] = None,
    db:      AsyncSession  = Depends(get_db),
    user_id: Optional[str] = Depends(get_user_id),
):
    svc  = LogService(db, user_id=user_id)
    logs = await svc.get_errors(path=path, hours=hours)
    return [_serialize(l) for l in logs]


@router.get("/stats")
async def get_log_stats(
    hours:   int          = Query(24),
    db:      AsyncSession  = Depends(get_db),
    user_id: Optional[str] = Depends(get_user_id),
):
    svc   = LogService(db, user_id=user_id)
    stats = await svc.get_path_stats(hours=hours)
    return list(stats)


@router.get("/{log_id}")
async def get_log(
    log_id:  str,
    db:      AsyncSession  = Depends(get_db),
    user_id: Optional[str] = Depends(get_user_id),
):
    svc = LogService(db, user_id=user_id)
    log = await svc.get_by_id(log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Log not found.")
    return _serialize(log)


def _serialize(log) -> dict:
    return {
        "id":                  log.id,
        "user_id":             log.user_id,
        "method":              log.method,
        "path":                log.path,
        "status_code":         log.status_code,
        "latency_ms":          log.latency_ms,
        "request_body":        log.request_body,
        "response_body":       log.response_body,
        "response_size_bytes": log.response_size_bytes,
        "client_ip":           log.client_ip,
        "created_at":          log.created_at.isoformat() if log.created_at else None,
    }
