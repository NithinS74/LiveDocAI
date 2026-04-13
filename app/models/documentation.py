import uuid
from sqlalchemy import Column, String, DateTime, JSON, Text, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class Documentation(Base):
    __tablename__ = "documentation"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    endpoint_id = Column(String, ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False)
    version     = Column(String(20), nullable=False)
    summary     = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    openapi_spec        = Column(JSON, nullable=True)
    request_examples    = Column(JSON, default=[])
    response_examples   = Column(JSON, default=[])
    error_scenarios     = Column(JSON, default=[])
    edge_cases          = Column(JSON, default=[])
    generated_by        = Column(String(50), default="ai")
    model_used          = Column(String(100), nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Documentation endpoint={self.endpoint_id} v{self.version}>"
