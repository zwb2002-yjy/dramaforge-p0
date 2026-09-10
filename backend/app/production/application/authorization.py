"""Persisted single-action grants; all entry points require trusted user identity."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import ProjectCreativeProfile, User
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.contracts.production_commands import ExecutionBody, ExecutionReceipt
from app.execution.models import NodeRun
from app.production.application.commands import ProductionCommands, execution_receipt
from app.production.command_models import ProductionCommandAuthorization
from app.production.workbench_execution import WorkbenchExecutionService, workbench_request_hash
from app.shared.errors import ConflictError, NotFoundError


class ProductionAuthorizations:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _lock(self, *, actor: User, project_id: UUID) -> ProjectCreativeProfile:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        await WorkbenchExecutionService(self._session, user_id=actor.id).lock_command_scope(
            project_id=project_id,
        )
        profile = await self._session.scalar(
            select(ProjectCreativeProfile)
            .where(ProjectCreativeProfile.project_id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if profile is None:
            raise ConflictError("Project has no creative profile")
        return profile

    async def approve_user_action(
        self,
        *,
        actor: User,
        project_id: UUID,
        shot_id: UUID,
        decision_id: UUID,
        body: ExecutionBody,
        expires_at: datetime,
    ) -> UUID:
        """Called only for an explicit product user decision, never a model tool.

        Caller commits this grant before scheduling submission. The exact body
        freezes stage, target version, model choice and plan; each grant allows
        one command only. Repeated submission reuses its persisted key.
        """
        profile = await self._lock(actor=actor, project_id=project_id)
        command_key = f"approved:{decision_id}"
        request_hash = workbench_request_hash(body.model_dump(mode="json"))
        existing = await self._session.scalar(
            select(ProductionCommandAuthorization).where(
                ProductionCommandAuthorization.project_id == project_id,
                ProductionCommandAuthorization.command_key == command_key,
            )
        )
        if existing is not None:
            expiry = existing.expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if (
                existing.actor_id != actor.id
                or existing.shot_id != shot_id
                or existing.request_hash != request_hash
                or expiry != expires_at
            ):
                raise ConflictError(
                    "Decision was already used for a different authorization",
                    details={"code": "PRODUCTION_DECISION_REUSED"},
                )
            # Never renew an expired/revoked decision or reset accepted work.
            return existing.id
        if profile.director_autonomy != "AUTO":
            raise ConflictError(
                "One-shot Director execution requires AUTO mode",
                details={"code": "DIRECTOR_AUTO_REQUIRED", "manual_ok": True},
            )
        if expires_at.tzinfo is None or expires_at <= datetime.now(UTC):
            raise ConflictError("Authorization must have a future timezone-aware expiry")
        shot = await self._session.scalar(
            select(Shot).where(Shot.id == shot_id, Shot.project_id == project_id),
        )
        if shot is None:
            raise NotFoundError("Shot not found")
        authorization_id = uuid4()
        self._session.add(
            ProductionCommandAuthorization(
                id=authorization_id,
                project_id=project_id,
                actor_id=actor.id,
                shot_id=shot_id,
                command_key=command_key,
                request_hash=request_hash,
                body=body.model_dump(mode="json"),
                profile_version=profile.version,
                expires_at=expires_at,
                status="approved",
            )
        )
        await self._session.flush()
        return authorization_id

    async def _get(
        self,
        *,
        actor: User,
        project_id: UUID,
        authorization_id: UUID,
    ) -> ProductionCommandAuthorization:
        grant = await self._session.scalar(
            select(ProductionCommandAuthorization)
            .where(
                ProductionCommandAuthorization.id == authorization_id,
                ProductionCommandAuthorization.project_id == project_id,
                ProductionCommandAuthorization.actor_id == actor.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True),
        )
        if grant is None:
            raise NotFoundError("Authorization not found")
        return grant

    async def revoke(self, *, actor: User, project_id: UUID, authorization_id: UUID) -> None:
        await self._lock(actor=actor, project_id=project_id)
        grant = await self._get(
            actor=actor, project_id=project_id, authorization_id=authorization_id
        )
        if grant.status == "approved":
            grant.status = "revoked"
            await self._session.flush()
        # Already accepted work remains a production fact; revoke cannot cancel it.

    async def submit(
        self,
        *,
        actor: User,
        project_id: UUID,
        authorization_id: UUID,
    ) -> ExecutionReceipt:
        profile = await self._lock(actor=actor, project_id=project_id)
        grant = await self._get(
            actor=actor, project_id=project_id, authorization_id=authorization_id
        )
        if grant.status == "accepted":
            run = await self._session.get(NodeRun, grant.node_run_id)
            if run is None or run.project_id != project_id:
                raise ConflictError("Accepted command receipt is missing")
            return await execution_receipt(self._session, run)
        expiry = grant.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        if (
            grant.status != "approved"
            or expiry <= datetime.now(UTC)
            or profile.director_autonomy != "AUTO"
            or profile.version != grant.profile_version
        ):
            raise ConflictError(
                "Authorization is revoked, expired or stale",
                details={"code": "PRODUCTION_AUTHORIZATION_INVALID"},
            )
        body = ExecutionBody.model_validate(grant.body)
        if workbench_request_hash(body.model_dump(mode="json")) != grant.request_hash:
            raise ConflictError("Authorized command payload changed")
        receipt = await ProductionCommands(self._session).submit_user_execution(
            actor=actor,
            project_id=project_id,
            shot_id=grant.shot_id,
            body=body,
            command_key=grant.command_key,
        )
        grant.status = "accepted"
        grant.node_run_id = receipt.node_run_id
        await self._session.flush()
        return receipt
