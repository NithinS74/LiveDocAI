import uuid
from sqlalchemy import Column, String, DateTime, JSON, Text, Integer
from sqlalchemy.sql import func
from app.database import Base


class DocHistory(Base):
    """
    Tracks every documentation generation event.
    One row = one "Generate Docs" trigger (manual or webhook).
    """
    __tablename__ = "doc_history"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_email   = Column(String(300), nullable=False, index=True)

    # GitHub info
    owner        = Column(String(200), nullable=False)
    repo         = Column(String(200), nullable=False)
    repo_url     = Column(String(500), nullable=True)

    # What was generated
    doc_target   = Column(String(50), nullable=False)    # readme | documentation_md | custom
    file_path    = Column(String(500), nullable=True)    # actual file path in repo
    pr_url       = Column(String(500), nullable=True)    # link to opened PR
    pr_number    = Column(Integer, nullable=True)
    branch       = Column(String(200), nullable=True)

    # Content
    generated_docs = Column(Text, nullable=True)         # the actual markdown generated
    files_analyzed = Column(JSON, default=list)          # list of files read from repo

    # Drift info
    drift_detected   = Column(String(10), nullable=True)  # YES | NO | UNKNOWN
    drift_summary    = Column(Text, nullable=True)
    commit_sha       = Column(String(50), nullable=True)  # commit that triggered this
    prev_commit_sha  = Column(String(50), nullable=True)

    # Trigger
    trigger      = Column(String(20), default="manual")  # manual | webhook | scheduled

    # Status
    status       = Column(String(20), default="success")  # success | failed
    error_msg    = Column(Text, nullable=True)

    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<DocHistory {self.owner}/{self.repo} @ {self.created_at}>"
