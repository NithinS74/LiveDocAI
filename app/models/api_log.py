import uuid
from sqlalchemy import Column, String, Integer, Float, DateTime, JSON, Text, Index
from sqlalchemy.sql import func
from app.database import Base


class APILog(Base):
    __tablename__ = "api_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # User isolation
    user_id = Column(String(36), nullable=True, index=True)

    # Request
    method              = Column(String(10),  nullable=False)
    path                = Column(String(500), nullable=False)
    query_params        = Column(JSON,  default={})
    request_headers     = Column(JSON,  default={})
    request_body        = Column(Text,  nullable=True)

    # Response
    status_code         = Column(Integer, nullable=False)
    response_headers    = Column(JSON,  default={})
    response_body       = Column(Text,  nullable=True)

    # Performance
    latency_ms          = Column(Float,   nullable=True)
    request_size_bytes  = Column(Integer, default=0)
    response_size_bytes = Column(Integer, default=0)

    # Context
    client_ip           = Column(String(50),  nullable=True)
    user_agent          = Column(String(500), nullable=True)

    created_at          = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_api_logs_path",       "path"),
        Index("idx_api_logs_method",     "method"),
        Index("idx_api_logs_status",     "status_code"),
        Index("idx_api_logs_created_at", "created_at"),
        Index("idx_api_logs_user_id",    "user_id"),
    )

    def __repr__(self):
        return f"<APILog {self.method} {self.path} → {self.status_code}>"
