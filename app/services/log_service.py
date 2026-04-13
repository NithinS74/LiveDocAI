from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, case
from typing import List, Optional
from datetime import datetime, timedelta

from app.models.api_log import APILog
from app.schemas import LogFilterParams


class LogService:
    def __init__(self, db: AsyncSession, user_id: Optional[str] = None):
        self.db      = db
        self.user_id = user_id  # filter all queries to this user

    def _base_query(self):
        q = select(APILog)
        if self.user_id:
            q = q.where(APILog.user_id == self.user_id)
        return q

    async def get_logs(self, filters: LogFilterParams) -> List[APILog]:
        q = self._base_query()
        if filters.method:
            q = q.where(APILog.method == filters.method.upper())
        if filters.path:
            q = q.where(APILog.path.contains(filters.path))
        if filters.status_code:
            q = q.where(APILog.status_code == filters.status_code)
        if filters.min_latency_ms is not None:
            q = q.where(APILog.latency_ms >= filters.min_latency_ms)
        if filters.max_latency_ms is not None:
            q = q.where(APILog.latency_ms <= filters.max_latency_ms)
        q = q.order_by(desc(APILog.created_at)).offset(filters.offset).limit(filters.limit)
        result = await self.db.execute(q)
        return result.scalars().all()

    async def get_by_id(self, log_id: str) -> Optional[APILog]:
        q = self._base_query().where(APILog.id == log_id)
        result = await self.db.execute(q)
        return result.scalar_one_or_none()

    async def get_for_endpoint(self, path_prefix: str, method: str, limit: int = 100) -> List[APILog]:
        prefix = path_prefix.split("{")[0].rstrip("/") or "/"
        q = (
            self._base_query()
            .where(APILog.path.like(f"{prefix}%"))
            .where(APILog.method == method.upper())
            .order_by(desc(APILog.created_at))
            .limit(limit)
        )
        result = await self.db.execute(q)
        return result.scalars().all()

    async def get_errors(self, path: Optional[str] = None, hours: int = 24) -> List[APILog]:
        since = datetime.utcnow() - timedelta(hours=hours)
        q = (
            self._base_query()
            .where(APILog.status_code >= 400)
            .where(APILog.created_at >= since)
        )
        if path:
            q = q.where(APILog.path.contains(path))
        result = await self.db.execute(q.order_by(desc(APILog.created_at)).limit(200))
        return result.scalars().all()

    async def get_path_stats(self, hours: int = 24):
        since = datetime.utcnow() - timedelta(hours=hours)
        q = (
            select(
                APILog.method,
                APILog.path,
                func.count().label("total"),
                func.avg(APILog.latency_ms).label("avg_latency"),
                func.sum(case((APILog.status_code >= 400, 1), else_=0)).label("error_count"),
            )
            .where(APILog.created_at >= since)
            .group_by(APILog.method, APILog.path)
            .order_by(desc("total"))
        )
        if self.user_id:
            q = q.where(APILog.user_id == self.user_id)
        result = await self.db.execute(q)
        return result.mappings().all()

    async def count_last_24h(self) -> int:
        since = datetime.utcnow() - timedelta(hours=24)
        q = self._base_query().where(APILog.created_at >= since)
        result = await self.db.execute(select(func.count()).select_from(q.subquery()))
        return result.scalar() or 0
