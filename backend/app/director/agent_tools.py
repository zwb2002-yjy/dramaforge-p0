"""Typed, server-scoped READ tools for a bounded Director turn.

The executor owns one short read transaction per call. The caller owns durable
call identity, receipts and cancellation; no model receives a session or factory.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.agent_read_service import AgentReadService
from app.assets.models import Asset, Scene, Shot
from app.contracts.director_model_tools import (
    ModelCapabilitiesInput,
    ModelCapabilitiesRead,
    ModelCompilePreviewInput,
    ModelCompilePreviewRead,
    ModelToolScope,
    ModelToolsPort,
)
from app.director.agent_proposals import AgentProposalRead, ShotPromptProposalInput
from app.shared.errors import AppError


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolContext(_Strict):
    actor_id: UUID
    workspace_id: UUID
    project_id: UUID
    turn_id: UUID
    thread_id: UUID
    scope_type: Literal["project", "story", "scene", "shot"]
    scope_entity_id: UUID
    expected_versions: dict[str, int] = Field(default_factory=dict)
    deadline: AwareDatetime | None = None


class ToolError(_Strict):
    code: str
    message: str
    recoverable: bool
    retry_class: Literal["none", "correct_input", "transient", "refresh_context"] = "none"
    details: dict[str, object] = Field(default_factory=dict)


class ToolResult(_Strict):
    call_id: str
    ok: bool
    data: dict[str, object] | None = None
    error: ToolError | None = None
    observed_versions: dict[str, int] = Field(default_factory=dict)
    provenance: dict[str, str] = Field(default_factory=dict)
    truncated: bool = False
    result_hash: str = ""


class ToolSpec(_Strict):
    name: str
    version: str = "1"
    description: str
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    risk: Literal["READ", "PROPOSE"] = "READ"
    side_effect: Literal["none", "proposal"] = "none"
    requires_confirmation: Literal[False] = False
    timeout_ms: int = 5000
    # Stay below AgentMessage's 32,000-character content bound including JSON framing.
    max_result_bytes: int = 24576
    source: str = "dramaforge"
    schema_hash: str


class EmptyInput(_Strict):
    pass


class PageInput(_Strict):
    limit: int = Field(default=20, ge=1, le=50, strict=True)
    offset: int = Field(default=0, ge=0, le=100000, strict=True)


class SceneInput(_Strict):
    scene_id: UUID


class ShotsInput(PageInput):
    scene_id: UUID


class ShotInput(_Strict):
    shot_id: UUID


class AssetInput(_Strict):
    asset_id: UUID


class ProjectRead(_Strict):
    id: UUID
    name: str
    aspect_ratio: str
    stage: str
    version: int


class SceneRead(_Strict):
    id: UUID
    episode_id: UUID
    scene_number: int
    location_name: str
    time_of_day: str
    synopsis: str
    version: int


class ShotRead(_Strict):
    id: UUID
    scene_id: UUID
    shot_number: int
    shot_type: str
    camera_move: str
    visual_description: str
    image_prompt: str
    video_prompt: str
    dialogue: str
    duration_seconds: float
    status: str
    version: int


class AssetRead(_Strict):
    id: UUID
    kind: str
    name: str
    description: str
    status: str
    version: int
    current_version_id: UUID | None


class ScenePage(_Strict):
    items: list[SceneRead]
    next_offset: int | None


class ShotPage(_Strict):
    items: list[ShotRead]
    next_offset: int | None


class AssetPage(_Strict):
    items: list[AssetRead]
    next_offset: int | None


@dataclass(frozen=True)
class _Definition:
    name: str
    description: str
    inputs: type[BaseModel]
    outputs: type[BaseModel]
    scopes: tuple[str, ...] = ("project", "story", "scene", "shot")
    risk: Literal["READ", "PROPOSE"] = "READ"

    def spec(self) -> ToolSpec:
        input_schema = self.inputs.model_json_schema()
        output_schema = self.outputs.model_json_schema()
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=input_schema,
            output_schema=output_schema,
            schema_hash=_hash({"input": input_schema, "output": output_schema}),
            risk=self.risk,
            side_effect="proposal" if self.risk == "PROPOSE" else "none",
        )


_DEFINITIONS = (
    _Definition(
        "project_get", "Read the current project's identity and version.", EmptyInput, ProjectRead
    ),
    _Definition(
        "scenes_list",
        "List this project's scenes, ordered by episode and scene.",
        PageInput,
        ScenePage,
        ("project", "story"),
    ),
    _Definition("scene_get", "Read one scene within the authorized scope.", SceneInput, SceneRead),
    _Definition(
        "shots_list",
        "List shots in one scene within the authorized scope.",
        ShotsInput,
        ShotPage,
        ("project", "story", "scene"),
    ),
    _Definition("shot_get", "Read one shot within the authorized scope.", ShotInput, ShotRead),
    _Definition(
        "assets_list", "List available project assets without adopting them.", PageInput, AssetPage
    ),
    _Definition(
        "asset_get",
        "Read a project asset's current identity and description.",
        AssetInput,
        AssetRead,
    ),
    _Definition(
        "shot_prompt_propose",
        "Propose exactly one image OR video prompt change after reading the shot. "
        "Returns a pending proposal for explicit user Apply; never generates media.",
        ShotPromptProposalInput,
        AgentProposalRead,
        risk="PROPOSE",
    ),
)

_MODEL_DEFINITIONS = (
    _Definition(
        "model_capabilities",
        "Inspect the current media binding and exact capability/revision hashes. "
        "This checks contracts only, never calls a provider or tests an account.",
        ModelCapabilitiesInput,
        ModelCapabilitiesRead,
    ),
    _Definition(
        "model_compile_preview",
        "Preview the saved shot prompt using exact hashes from model_capabilities. "
        "Pure compilation only: no generation, credentials, transport tokens or adoption.",
        ModelCompilePreviewInput,
        ModelCompilePreviewRead,
    ),
)


class ToolRegistry:
    """Fixed allowlist. Every returned spec is detached from registry state."""

    def __init__(self, *, include_model_tools: bool = False) -> None:
        self._definitions = _DEFINITIONS + (_MODEL_DEFINITIONS if include_model_tools else ())

    def specs(self, context: ToolContext | None = None) -> tuple[ToolSpec, ...]:
        return tuple(
            item.spec()
            for item in self._definitions
            if context is None or context.scope_type in item.scopes
        )

    def fingerprint(self, context: ToolContext | None = None) -> str:
        return _hash([item.model_dump(mode="json") for item in self.specs(context)])

    def openai_tools(self, context: ToolContext | None = None) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.input_schema,
                },
            }
            for spec in self.specs(context)
        ]

    def resolve(self, name: str, context: ToolContext) -> _Definition | None:
        return next(
            (
                item
                for item in self._definitions
                if item.name == name and context.scope_type in item.scopes
            ),
            None,
        )


class _ToolFailure(Exception):
    def __init__(self, error: ToolError) -> None:
        super().__init__(error.code)
        self.error = error


def _failure(
    code: str,
    message: str,
    *,
    recoverable: bool = True,
    retry_class: Literal["none", "correct_input", "transient", "refresh_context"] = "correct_input",
) -> _ToolFailure:
    return _ToolFailure(
        ToolError(
            code=code,
            message=message,
            recoverable=recoverable,
            retry_class=retry_class,
        )
    )


def _scene_read(row: Scene) -> SceneRead:
    return SceneRead.model_validate({key: getattr(row, key) for key in SceneRead.model_fields})


def _shot_read(row: Shot) -> ShotRead:
    return ShotRead.model_validate({key: getattr(row, key) for key in ShotRead.model_fields})


def _asset_read(row: Asset) -> AssetRead:
    return AssetRead.model_validate({key: getattr(row, key) for key in AssetRead.model_fields})


class ToolExecutor:
    def __init__(
        self,
        factory: Callable[[], AsyncSession],
        registry: ToolRegistry | None = None,
        *,
        model_tools: ModelToolsPort | None = None,
    ) -> None:
        self._factory = factory
        self._model_tools = model_tools
        self.registry = registry or ToolRegistry(include_model_tools=model_tools is not None)

    async def execute(
        self,
        *,
        name: str,
        arguments: dict[str, object],
        call_id: str,
        context: ToolContext,
    ) -> ToolResult:
        observed: dict[str, int] = {}
        definition = self.registry.resolve(name, context)
        provenance = {"source": "dramaforge", "tool": name, "version": "1"}
        spec = definition.spec() if definition else None
        try:
            if definition is None or spec is None:
                raise _failure("ToolNotFound", "Tool is not available in this scope.")
            if spec.risk != "READ":
                raise _failure(
                    "ToolTransactionRequired",
                    "Proposal requires the durable tool receipt.",
                    recoverable=False,
                    retry_class="none",
                )
            try:
                inputs = definition.inputs.model_validate(arguments)
            except ValidationError as exc:
                raise _failure(
                    "ToolInputInvalid",
                    "Arguments do not match the tool schema.",
                ) from exc
            timeout = spec.timeout_ms / 1000
            if context.deadline is not None:
                timeout = min(timeout, (context.deadline - datetime.now(UTC)).total_seconds())
            if timeout <= 0:
                raise _failure(
                    "DeadlineExceeded",
                    "The turn deadline has elapsed.",
                    recoverable=False,
                    retry_class="none",
                )
            async with asyncio.timeout(timeout):
                output = await self._read(definition, inputs, context, observed)
            result = ToolResult(
                call_id=call_id,
                ok=True,
                data=output.model_dump(mode="json"),
                observed_versions=observed,
                provenance=provenance,
            )
            if len(result.model_dump_json().encode()) + 64 > spec.max_result_bytes:
                result = ToolResult(
                    call_id=call_id,
                    ok=False,
                    truncated=True,
                    provenance=provenance,
                    error=ToolError(
                        code="ToolResultTooLarge",
                        message="Narrow the requested result.",
                        recoverable=True,
                        retry_class="correct_input",
                    ),
                )
        except _ToolFailure as exc:
            result = ToolResult(
                call_id=call_id,
                ok=False,
                error=exc.error,
                observed_versions=observed,
                provenance=provenance,
            )
        except TimeoutError:
            result = ToolResult(
                call_id=call_id,
                ok=False,
                provenance=provenance,
                error=ToolError(
                    code="ToolTimeout",
                    message="The read timed out.",
                    recoverable=True,
                    retry_class="transient",
                ),
            )
        except AppError as exc:
            stale = exc.details.get("code") in {"CONTEXT_STALE", "ContextStale"}
            code = (
                "ContextStale"
                if stale
                else "ToolPermissionDenied"
                if exc.status_code in {401, 403}
                else "ToolExecutionFailed"
            )
            result = ToolResult(
                call_id=call_id,
                ok=False,
                provenance=provenance,
                error=ToolError(
                    code=code,
                    message="The requested resource is unavailable in this scope.",
                    recoverable=not stale,
                    retry_class="refresh_context" if stale else "correct_input",
                ),
            )
        except Exception:
            result = ToolResult(
                call_id=call_id,
                ok=False,
                provenance=provenance,
                error=ToolError(
                    code="ToolExecutionFailed",
                    message="The read could not be completed.",
                    recoverable=True,
                    retry_class="transient",
                ),
            )
        return result.model_copy(update={"result_hash": _hash(result.model_dump(mode="json"))})

    async def _read(
        self,
        definition: _Definition,
        inputs: BaseModel,
        context: ToolContext,
        observed: dict[str, int],
    ) -> BaseModel:
        if isinstance(inputs, (ModelCapabilitiesInput, ModelCompilePreviewInput)):
            if self._model_tools is None:
                raise _failure("ToolNotFound", "Model tools are not available.")
            scope = ModelToolScope.model_validate(
                context.model_dump(
                    exclude={
                        "turn_id",
                        "thread_id",
                        "deadline",
                    }
                )
            )
            if isinstance(inputs, ModelCapabilitiesInput):
                inspected = await self._model_tools.inspect(scope=scope, request=inputs)
                observed.update(inspected.observed_versions)
                return inspected
            preview = await self._model_tools.preview(scope=scope, request=inputs)
            observed.update(preview.observed_versions)
            return preview

        def observe(kind: str, entity_id: UUID, version: int) -> None:
            key = f"{kind}:{entity_id}"
            observed[key] = version
            expected = context.expected_versions.get(key)
            if expected is not None and expected != version:
                raise _failure(
                    "ContextStale",
                    "A referenced object changed; refresh context.",
                    recoverable=False,
                    retry_class="refresh_context",
                )

        async with self._factory() as session:
            reader = AgentReadService(
                session,
                actor_id=context.actor_id,
                workspace_id=context.workspace_id,
                project_id=context.project_id,
            )
            project = await reader.project()
            observe("project", project.id, project.version)
            scope_scene: UUID | None = None
            if context.scope_type in {"project", "story"}:
                if context.scope_entity_id != context.project_id:
                    raise _failure("ToolPermissionDenied", "Scope does not match the project.")
            elif context.scope_type == "scene":
                scene = await reader.scene(context.scope_entity_id)
                observe("scene", scene.id, scene.version)
                scope_scene = scene.id
            else:
                shot = await reader.shot(context.scope_entity_id)
                observe("shot", shot.id, shot.version)
                scope_scene = shot.scene_id

            if definition.name == "project_get":
                return ProjectRead(
                    id=project.id,
                    name=project.name,
                    aspect_ratio=project.aspect_ratio,
                    stage=str(project.stage),
                    version=project.version,
                )
            if definition.name == "scenes_list" and isinstance(inputs, PageInput):
                scenes = await reader.scenes(limit=inputs.limit + 1, offset=inputs.offset)
                for scene in scenes[: inputs.limit]:
                    observe("scene", scene.id, scene.version)
                return ScenePage(
                    items=[_scene_read(row) for row in scenes[: inputs.limit]],
                    next_offset=inputs.offset + inputs.limit
                    if len(scenes) > inputs.limit
                    else None,
                )
            if definition.name in {"scene_get", "shots_list"}:
                assert isinstance(inputs, (SceneInput, ShotsInput))
                if scope_scene is not None and inputs.scene_id != scope_scene:
                    raise _failure("ToolPermissionDenied", "Scene is outside the current scope.")
                scene = await reader.scene(inputs.scene_id)
                observe("scene", scene.id, scene.version)
                if isinstance(inputs, SceneInput):
                    return _scene_read(scene)
                shots = await reader.shots(
                    scene_id=inputs.scene_id, limit=inputs.limit + 1, offset=inputs.offset
                )
                for shot in shots[: inputs.limit]:
                    observe("shot", shot.id, shot.version)
                return ShotPage(
                    items=[_shot_read(row) for row in shots[: inputs.limit]],
                    next_offset=inputs.offset + inputs.limit if len(shots) > inputs.limit else None,
                )
            if definition.name == "shot_get" and isinstance(inputs, ShotInput):
                if context.scope_type == "shot" and inputs.shot_id != context.scope_entity_id:
                    raise _failure("ToolPermissionDenied", "Shot is outside the current scope.")
                shot = await reader.shot(inputs.shot_id)
                if scope_scene is not None and shot.scene_id != scope_scene:
                    raise _failure("ToolPermissionDenied", "Shot is outside the current scope.")
                observe("shot", shot.id, shot.version)
                return _shot_read(shot)
            if definition.name == "assets_list" and isinstance(inputs, PageInput):
                assets = await reader.assets(limit=inputs.limit + 1, offset=inputs.offset)
                for asset in assets[: inputs.limit]:
                    observe("asset", asset.id, asset.version)
                return AssetPage(
                    items=[_asset_read(row) for row in assets[: inputs.limit]],
                    next_offset=inputs.offset + inputs.limit
                    if len(assets) > inputs.limit
                    else None,
                )
            if definition.name == "asset_get" and isinstance(inputs, AssetInput):
                card = await reader.asset(inputs.asset_id)
                data = {key: card[key] for key in AssetRead.model_fields if key != "id"}
                output = AssetRead.model_validate({"id": card["asset_id"], **data})
                observe("asset", output.id, output.version)
                return output
            raise _failure("ToolNotFound", "Tool is not available.")
