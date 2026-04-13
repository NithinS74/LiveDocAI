"""
Endpoints Router — user-isolated
GET  /api/endpoints/              — list all endpoints for current user
GET  /api/endpoints/drift         — endpoints with drift for current user
GET  /api/endpoints/{id}          — single endpoint
GET  /api/endpoints/{id}/logs     — logs for a specific endpoint
POST /api/endpoints/{id}/analyze  — trigger AI analysis on an endpoint
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.endpoint_service import EndpointService
from app.services.log_service import LogService
from app.deps import get_user_id

router = APIRouter(prefix="/api/endpoints", tags=["Endpoints"])
logger = logging.getLogger(__name__)


@router.get("/")
async def list_endpoints(
    db:      AsyncSession  = Depends(get_db),
    user_id: Optional[str] = Depends(get_user_id),
):
    svc       = EndpointService(db, user_id=user_id)
    endpoints = await svc.list_all()
    return [_serialize(ep) for ep in endpoints]


@router.get("/drift")
async def get_drift_endpoints(
    db:      AsyncSession  = Depends(get_db),
    user_id: Optional[str] = Depends(get_user_id),
):
    svc       = EndpointService(db, user_id=user_id)
    endpoints = await svc.get_with_drift()
    return [_serialize(ep) for ep in endpoints]


@router.get("/{endpoint_id}")
async def get_endpoint(
    endpoint_id: str,
    db:          AsyncSession  = Depends(get_db),
    user_id:     Optional[str] = Depends(get_user_id),
):
    svc = EndpointService(db, user_id=user_id)
    ep  = await svc.get_by_id(endpoint_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found.")
    return _serialize(ep)


@router.get("/{endpoint_id}/logs")
async def get_endpoint_logs(
    endpoint_id: str,
    db:          AsyncSession  = Depends(get_db),
    user_id:     Optional[str] = Depends(get_user_id),
):
    ep_svc = EndpointService(db, user_id=user_id)
    ep     = await ep_svc.get_by_id(endpoint_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found.")

    log_svc = LogService(db, user_id=user_id)
    logs    = await log_svc.get_for_endpoint(ep.path_pattern, ep.method)
    return [
        {
            "id":          l.id,
            "method":      l.method,
            "path":        l.path,
            "status_code": l.status_code,
            "latency_ms":  l.latency_ms,
            "created_at":  l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]


@router.post("/{endpoint_id}/analyze")
async def trigger_analysis(
    endpoint_id: str,
    db:          AsyncSession  = Depends(get_db),
    user_id:     Optional[str] = Depends(get_user_id),
):
    ep_svc = EndpointService(db, user_id=user_id)
    ep     = await ep_svc.get_by_id(endpoint_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found.")

    log_svc = LogService(db, user_id=user_id)
    logs    = await log_svc.get_for_endpoint(ep.path_pattern, ep.method, limit=50)
    if not logs:
        return {"status": "no_logs", "message": "No traffic data to analyze."}

    try:
        from app.services.ai_service import run_analysis
        analysis = await run_analysis(
            method=ep.method,
            path=ep.path_pattern,
            logs=logs,
        )
        await ep_svc.save_ai_docs(
            endpoint_id   = ep.id,
            documentation = analysis["documentation"],
            edge_cases    = analysis["edge_cases"],
            examples      = analysis["examples"],
        )
        await ep_svc.save_drift(
            endpoint_id = ep.id,
            has_drift   = analysis["drift_detected"],
            summary     = analysis["drift_description"],
        )
        await db.commit()
        return {"status": "ok", "drift_detected": analysis["drift_detected"]}
    except Exception as e:
        logger.error(f"[Endpoints] analyze error: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)[:200]}")


def _serialize(ep) -> dict:
    return {
        "id":               ep.id,
        "user_id":          ep.user_id,
        "method":           ep.method,
        "path_pattern":     ep.path_pattern,
        "total_requests":   ep.total_requests,
        "error_count":      ep.error_count,
        "avg_latency_ms":   ep.avg_latency_ms,
        "has_drift":        ep.has_drift,
        "drift_summary":    ep.drift_summary,
        "ai_documentation": ep.ai_documentation,
        "edge_cases":       ep.edge_cases or [],
        "usage_examples":   ep.usage_examples or [],
        "docs_updated_at":  ep.docs_updated_at.isoformat() if ep.docs_updated_at else None,
        "last_seen_at":     ep.last_seen_at.isoformat() if ep.last_seen_at else None,
    }
