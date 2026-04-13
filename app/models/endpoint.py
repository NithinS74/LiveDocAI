import uuid
from sqlalchemy import Column, String, Integer, Float, DateTime, JSON, Boolean, Text, Index
from sqlalchemy.sql import func
from app.database import Base


class Endpoint(Base):
    __tablename__ = "endpoints"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # User isolation
    user_id = Column(String(36), nullable=True, index=True)

    # Identity
    method        = Column(String(10),  nullable=False)
    path_pattern  = Column(String(500), nullable=False)
    path_regex    = Column(String(500), nullable=True)
    openapi_spec  = Column(JSON, nullable=True)

    # Aggregated stats
    total_requests  = Column(Integer, default=0)
    error_count     = Column(Integer, default=0)
    avg_latency_ms  = Column(Float,   default=0.0)
    p95_latency_ms  = Column(Float,   default=0.0)
    p99_latency_ms  = Column(Float,   default=0.0)

    # Drift detection
    has_drift               = Column(Boolean, default=False)
    drift_summary           = Column(Text,    nullable=True)
    last_drift_detected_at  = Column(DateTime(timezone=True), nullable=True)

    # AI analysis
    ai_documentation = Column(Text, nullable=True)
    edge_cases       = Column(JSON, default=[])
    usage_examples   = Column(JSON, default=[])

    # Timestamps
    first_seen_at   = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    docs_updated_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_endpoints_user_id", "user_id"),
    )

    def __repr__(self):
        return f"<Endpoint {self.method} {self.path_pattern}>"
