from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Any, Dict, List
from datetime import datetime


# ─────────────────────────────────────────────────────────────
#  API Log Schemas
# ─────────────────────────────────────────────────────────────

class APILogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    method: str
    path: str
    query_params: Dict[str, Any]
    request_body: Optional[str]
    status_code: int
    response_body: Optional[str]
    latency_ms: Optional[float]
    request_size_bytes: int
    response_size_bytes: int
    client_ip: Optional[str]
    user_agent: Optional[str]
    created_at: datetime


class LogFilterParams(BaseModel):
    method: Optional[str] = None
    path: Optional[str] = None
    status_code: Optional[int] = None
    min_latency_ms: Optional[float] = None
    max_latency_ms: Optional[float] = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


# ─────────────────────────────────────────────────────────────
#  Endpoint Schemas
# ─────────────────────────────────────────────────────────────

class EndpointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    method: str
    path_pattern: str
    total_requests: int
    error_count: int
    avg_latency_ms: float
    p95_latency_ms: float
    has_drift: bool
    drift_summary: Optional[str]
    ai_documentation: Optional[str]
    edge_cases: List[Any]
    usage_examples: List[Any]
    first_seen_at: datetime
    last_seen_at: datetime
    docs_updated_at: Optional[datetime]


# ─────────────────────────────────────────────────────────────
#  Documentation Schemas
# ─────────────────────────────────────────────────────────────

class DocumentationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    endpoint_id: str
    version: str
    summary: Optional[str]
    description: Optional[str]
    openapi_spec: Optional[Dict[str, Any]]
    request_examples: List[Any]
    response_examples: List[Any]
    error_scenarios: List[Any]
    edge_cases: List[Any]
    generated_by: str
    model_used: Optional[str]
    created_at: datetime


# ─────────────────────────────────────────────────────────────
#  Dashboard / Analytics Schemas
# ─────────────────────────────────────────────────────────────

class EndpointStatItem(BaseModel):
    path_pattern: str
    method: str
    total_requests: int
    error_rate: float
    avg_latency_ms: float


class DashboardStats(BaseModel):
    total_requests_24h: int
    total_endpoints: int
    endpoints_with_drift: int
    avg_error_rate: float
    top_endpoints: List[EndpointStatItem]


# ─────────────────────────────────────────────────────────────
#  AI Analysis Schemas
# ─────────────────────────────────────────────────────────────

class AnalysisResult(BaseModel):
    endpoint_id: str
    documentation: str
    edge_cases: List[str]
    drift_detected: bool
    drift_description: Optional[str]
    examples: List[Dict[str, Any]]
