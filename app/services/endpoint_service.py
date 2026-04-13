import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case
from typing import List, Optional
from datetime import datetime

from app.models.endpoint import Endpoint
from app.models.api_log import APILog

_UUID_RE = re.compile(r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_INT_RE  = re.compile(r"/\d+")


def normalize_path(path: str) -> str:
    path = _UUID_RE.sub("/{uuid}", path)
    path = _INT_RE.sub("/{id}", path)
    return path


class EndpointService:
    def __init__(self, db: AsyncSession, user_id: Optional[str] = None):
        self.db      = db
        self.user_id = user_id

    def _base_query(self):
        q = select(Endpoint)
        if self.user_id:
            q = q.where(Endpoint.user_id == self.user_id)
        return q

    async def get_or_create(self, method: str, path: str, user_id: Optional[str] = None) -> Endpoint:
        pattern  = normalize_path(path)
        uid      = user_id or self.user_id
        q = (
            select(Endpoint)
            .where(Endpoint.method == method.upper())
            .where(Endpoint.path_pattern == pattern)
        )
        if uid:
            q = q.where(Endpoint.user_id == uid)
        result = await self.db.execute(q)
        ep = result.scalar_one_or_none()
        if not ep:
            ep = Endpoint(
                method       = method.upper(),
                path_pattern = pattern,
                user_id      = uid,
                first_seen_at = datetime.utcnow(),
                last_seen_at  = datetime.utcnow(),
            )
            self.db.add(ep)
            await self.db.flush()
        return ep

    async def list_all(self) -> List[Endpoint]:
        result = await self.db.execute(
            self._base_query().order_by(Endpoint.total_requests.desc())
        )
        return result.scalars().all()

    async def get_by_id(self, endpoint_id: str) -> Optional[Endpoint]:
        result = await self.db.execute(
            select(Endpoint).where(Endpoint.id == endpoint_id)
        )
        return result.scalar_one_or_none()

    async def get_by_path(self, method: str, pattern: str) -> Optional[Endpoint]:
        q = (
            select(Endpoint)
            .where(Endpoint.method == method.upper())
            .where(Endpoint.path_pattern == pattern)
        )
        if self.user_id:
            q = q.where(Endpoint.user_id == self.user_id)
        result = await self.db.execute(q)
        return result.scalar_one_or_none()

    async def get_with_drift(self) -> List[Endpoint]:
        result = await self.db.execute(
            self._base_query().where(Endpoint.has_drift.is_(True))
        )
        return result.scalars().all()

    async def count(self) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(self._base_query().subquery())
        )
        return result.scalar() or 0

    async def update_stats(self, endpoint_id: str):
        ep = await self.get_by_id(endpoint_id)
        if not ep:
            return
        prefix = ep.path_pattern.split("{")[0].rstrip("/") or "/"
        q = (
            select(
                func.count().label("total"),
                func.avg(APILog.latency_ms).label("avg_lat"),
                func.sum(case((APILog.status_code >= 400, 1), else_=0)).label("errors"),
            )
            .where(APILog.path.like(f"{prefix}%"))
            .where(APILog.method == ep.method)
        )
        if ep.user_id:
            q = q.where(APILog.user_id == ep.user_id)
        stats = await self.db.execute(q)
        row = stats.mappings().first()
        if row and row["total"]:
            ep.total_requests = row["total"]
            ep.error_count    = row["errors"] or 0
            ep.avg_latency_ms = round(row["avg_lat"] or 0, 2)
            ep.last_seen_at   = datetime.utcnow()
            await self.db.flush()

    async def save_drift(self, endpoint_id: str, has_drift: bool, summary: Optional[str] = None):
        ep = await self.get_by_id(endpoint_id)
        if ep:
            ep.has_drift     = has_drift
            ep.drift_summary = summary
            if has_drift:
                ep.last_drift_detected_at = datetime.utcnow()
            await self.db.flush()

    async def save_ai_docs(self, endpoint_id: str, documentation: str, edge_cases: list, examples: list):
        ep = await self.get_by_id(endpoint_id)
        if ep:
            ep.ai_documentation = documentation
            ep.edge_cases       = edge_cases
            ep.usage_examples   = examples
            ep.docs_updated_at  = datetime.utcnow()
            await self.db.flush()
