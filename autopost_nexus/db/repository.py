"""Database repository implementing data access patterns."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from autopost_nexus.db.models import PostModel, PostTargetModel, PublishAuditLogModel
from autopost_nexus.schemas.posting import (
    PostingCreateRequest,
    PostStatus,
    TargetStatus,
)


class PostRepository:
    """Repository handling CRUD operations for posts and distribution targets."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, post_id: str) -> PostModel | None:
        """Fetch post by primary key including all targets."""
        stmt = (
            select(PostModel)
            .where(PostModel.id == post_id)
            .options(selectinload(PostModel.targets))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_idempotency_key(self, idempotency_key: str) -> PostModel | None:
        """Fetch post by unique idempotency key."""
        if not idempotency_key:
            return None
        stmt = (
            select(PostModel)
            .where(PostModel.idempotency_key == idempotency_key)
            .options(selectinload(PostModel.targets))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_post(self, req: PostingCreateRequest) -> PostModel:
        """Create a new post and initialize target rows for each platform."""
        initial_status = (
            PostStatus.SCHEDULED.value
            if req.scheduled_at is not None
            else PostStatus.IN_PROGRESS.value
        )

        post = PostModel(
            id=str(uuid.uuid4()),
            title=req.title,
            content=req.content,
            status=initial_status,
            idempotency_key=req.idempotency_key,
            scheduled_at=req.scheduled_at,
        )

        # Create target platforms
        for platform in req.platforms:
            target = PostTargetModel(
                id=str(uuid.uuid4()),
                platform=platform.value,
                status=TargetStatus.PENDING.value,
                retry_count=0,
            )
            post.targets.append(target)

        self.session.add(post)
        await self.session.flush()
        await self.session.refresh(post, attribute_names=["targets"])
        return post

    async def list_posts(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
    ) -> list[PostModel]:
        """Retrieve paginated posts."""
        stmt = (
            select(PostModel)
            .options(selectinload(PostModel.targets))
            .order_by(PostModel.created_at.desc())
        )
        if status:
            stmt = stmt.where(PostModel.status == status)
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_post_status(self, post_id: str, status: PostStatus) -> PostModel | None:
        """Update aggregate status of a post."""
        post = await self.get_by_id(post_id)
        if post:
            post.status = status.value
            await self.session.flush()
        return post

    async def record_audit_log(
        self,
        target_id: str,
        event_type: str,
        http_status_code: int | None = None,
        request_headers_masked: str | None = None,
        response_body_snippet: str | None = None,
        execution_latency_ms: int | None = None,
    ) -> PublishAuditLogModel:
        """Create an immutable audit log entry."""
        log = PublishAuditLogModel(
            id=str(uuid.uuid4()),
            target_id=target_id,
            event_type=event_type,
            http_status_code=http_status_code,
            request_headers_masked=request_headers_masked,
            response_body_snippet=response_body_snippet,
            execution_latency_ms=execution_latency_ms,
        )
        self.session.add(log)
        await self.session.flush()
        return log
