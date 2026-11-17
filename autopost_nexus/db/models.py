"""SQLAlchemy 2.0 database models for AutoPost Nexus."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy entities."""


def generate_uuid() -> str:
    """Generate RFC 4122 UUID4 string."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(UTC)


class PostModel(Base):
    """Represents a multi-platform post entity."""

    __tablename__ = "posts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(255), nullable=True)
    content = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="draft", index=True)
    idempotency_key = Column(String(64), unique=True, nullable=True, index=True)
    scheduled_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    # Relationships
    targets = relationship(
        "PostTargetModel",
        back_populates="post",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class PostTargetModel(Base):
    """Represents a specific platform distribution target for a post."""

    __tablename__ = "post_targets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    post_id = Column(
        String(36), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform = Column(String(32), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    external_post_id = Column(String(255), nullable=True)
    external_url = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (UniqueConstraint("post_id", "platform", name="uq_post_platform"),)

    # Relationships
    post = relationship("PostModel", back_populates="targets")
    audit_logs = relationship(
        "PublishAuditLogModel",
        back_populates="target",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class PublishAuditLogModel(Base):
    """Records audit trail events for every dispatch attempt."""

    __tablename__ = "publish_audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    target_id = Column(
        String(36), ForeignKey("post_targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type = Column(String(32), nullable=False)
    http_status_code = Column(Integer, nullable=True)
    request_headers_masked = Column(Text, nullable=True)
    response_body_snippet = Column(Text, nullable=True)
    execution_latency_ms = Column(Integer, nullable=True)
    timestamp = Column(DateTime, nullable=False, default=utc_now)

    # Relationships
    target = relationship("PostTargetModel", back_populates="audit_logs")
