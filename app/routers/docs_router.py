"""
Documentation Router
GET /api/docs/endpoint/{id}         — versioned docs
GET /api/docs/endpoint/{id}/latest  — latest docs
GET /api/docs/openapi-export        — full OpenAPI export
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import Optional

from app.database import get_db
from app.models.documentation import Documentation
from app.models.endpoint import Endpoint
from app.deps import get_user_id

router = APIRouter(prefix="/api/docs", tags=["Documentation"])


@router.get("/endpoint/{endpoint_id}")
async def get_docs(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_user_id),
):
    result = await db.execute(
        select(Documentation)
        .where(Documentation.endpoint_id == endpoint_id)
        .order_by(desc(Documentation.created_at))
        .limit(10)
    )
    docs = result.scalars().all()
    return [
        {
            "id": d.id,
            "version": d.version,
            "summary": d.summary,
            "description": d.description,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


@router.get("/endpoint/{endpoint_id}/latest")
async def get_latest_doc(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_user_id),
):
    result = await db.execute(
        select(Documentation)
        .where(Documentation.endpoint_id == endpoint_id)
        .order_by(desc(Documentation.created_at))
        .limit(1)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="No documentation found.")
    return {
        "id": doc.id,
        "version": doc.version,
        "summary": doc.summary,
        "description": doc.description,
        "openapi_spec": doc.openapi_spec,
        "edge_cases": doc.edge_cases,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.get("/openapi-export")
async def export_openapi(
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_user_id),
):
    q = select(Endpoint)
    if user_id:
        q = q.where(Endpoint.user_id == user_id)
    result = await db.execute(q)
    endpoints = result.scalars().all()

    paths = {}
    for ep in endpoints:
        method = ep.method.lower()
        path   = ep.path_pattern
        paths.setdefault(path, {})[method] = {
            "summary":     ep.ai_documentation[:100] if ep.ai_documentation else f"{ep.method} {path}",
            "description": ep.ai_documentation or "",
            "responses":   {"200": {"description": "Success"}},
        }

    return {
        "openapi": "3.0.0",
        "info": {"title": "LiveDocAI Export", "version": "1.0.0"},
        "paths": paths,
    }
