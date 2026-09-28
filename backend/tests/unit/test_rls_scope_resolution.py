"""RLS discovery and transaction application contracts (no database service)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.access.models import Project, Workspace
from app.execution.models import Artifact, NodeRun
from app.shared import db, rls_scopes
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

USER, WORKSPACE, PROJECT, ENTITY = (uuid4() for _ in range(4))
CUTOFF = datetime(2026, 9, 17, tzinfo=UTC)

# Every PostgreSQL entrypoint must keep its precise function and bound arguments.
DISCOVERY = [
    (
        "resolve_node_run_rls_scope",
        "node_run_context",
        {"node_run_id": ENTITY},
        None,
        db.NodeRunRlsScope,
    ),
    (
        "resolve_artifact_rls_scope",
        "artifact_context",
        {"artifact_id": ENTITY},
        None,
        db.ArtifactRlsScope,
    ),
    (
        "list_queued_node_run_rls_scopes",
        "queued_node_run_contexts",
        {"limit": 7, "project_id": PROJECT, "source_commit": "exact-commit"},
        "node_run_id",
        db.NodeRunRlsScope,
    ),
    (
        "list_resumable_provider_node_run_rls_scopes",
        "resumable_provider_node_run_contexts",
        {
            "limit": 7, "source_commit": "exact-commit",
            "after_node_run_id": ENTITY, "stale_before": CUTOFF,
        },
        "node_run_id",
        db.NodeRunRlsScope,
    ),
    (
        "list_pending_outbox_event_rls_scopes",
        "pending_outbox_event_contexts",
        {"limit": 7, "project_id": PROJECT},
        "outbox_event_id",
        db.OutboxEventRlsScope,
    ),
    (
        "list_recoverable_director_turn_rls_scopes",
        "recoverable_director_turn_contexts",
        {"limit": 7, "stale_before": CUTOFF},
        "turn_id",
        db.DirectorTurnRlsScope,
    ),
    (
        "list_reconcilable_director_turn_rls_scopes",
        "reconcilable_director_turn_contexts",
        {"limit": 7, "after_turn_id": ENTITY},
        "turn_id",
        db.DirectorTurnRlsScope,
    ),
]


def session_stub(dialect="postgresql"):
    session = MagicMock(spec=AsyncSession)
    session.get_bind.return_value = (
        SimpleNamespace(dialect=SimpleNamespace(name=dialect)) if dialect else None
    )
    session.execute = AsyncMock()
    session.get = AsyncMock()
    return session


@pytest.mark.parametrize(
    "name",
    [case[0] for case in DISCOVERY]
    + [
        "NodeRunRlsScope",
        "ArtifactRlsScope",
        "OutboxEventRlsScope",
        "DirectorTurnRlsScope",
    ],
)
def test_db_explicit_reexports_preserve_identity(name):
    assert getattr(db, name) is getattr(rls_scopes, name)


@pytest.mark.parametrize("name,function,kwargs,id_key,scope_type", DISCOVERY)
@pytest.mark.parametrize("found", [True, False])
async def test_postgresql_discovery_uses_only_scoped_function(
    name,
    function,
    kwargs,
    id_key,
    scope_type,
    found,
):
    session = session_stub()
    row = {"owner_user_id": USER, "workspace_id": WORKSPACE, "project_id": PROJECT}
    if id_key:
        row[id_key] = ENTITY
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = row if found else None
    result.mappings.return_value.all.return_value = [row] if found else []
    session.execute.return_value = result

    actual = await getattr(db, name)(session, **kwargs)

    statement, params = session.execute.await_args.args
    columns = "owner_user_id, workspace_id, project_id"
    if id_key:
        columns = f"{id_key}, {columns}"
    args = ", ".join(f":{key}" for key in kwargs)
    assert " ".join(str(statement).split()) == f"SELECT {columns} FROM app.{function}({args})"
    assert params == kwargs
    session.execute.assert_awaited_once()
    session.get.assert_not_awaited()
    if not found:
        assert actual == ([] if id_key else None)
        return
    scope_kwargs = {"user_id": USER, "workspace_id": WORKSPACE, "project_id": PROJECT}
    if id_key == "outbox_event_id":
        expected = [scope_type(event_id=ENTITY, **scope_kwargs)]
    elif id_key:
        expected = [(ENTITY, scope_type(**scope_kwargs))]
    else:
        expected = scope_type(**scope_kwargs)
    assert actual == expected


@pytest.mark.parametrize("name,function,kwargs,id_key,scope_type", DISCOVERY)
async def test_postgresql_failure_never_falls_back_to_orm(
    name,
    function,
    kwargs,
    id_key,
    scope_type,
):
    session = session_stub()
    session.execute.side_effect = SQLAlchemyError("resolver denied")
    with pytest.raises(SQLAlchemyError, match="resolver denied"):
        await getattr(db, name)(session, **kwargs)
    session.get.assert_not_awaited()
    session.execute.assert_awaited_once()


@pytest.mark.parametrize(
    "name,model,id_arg,scope_type",
    [
        ("resolve_node_run_rls_scope", NodeRun, "node_run_id", db.NodeRunRlsScope),
        ("resolve_artifact_rls_scope", Artifact, "artifact_id", db.ArtifactRlsScope),
    ],
)
@pytest.mark.parametrize("missing", ["entity", "project", "workspace", None])
async def test_non_postgresql_ownership_requires_complete_persisted_chain(
    name,
    model,
    id_arg,
    scope_type,
    missing,
):
    session = session_stub("sqlite")
    chain = [
        SimpleNamespace(project_id=PROJECT),
        SimpleNamespace(id=PROJECT, workspace_id=WORKSPACE),
        SimpleNamespace(id=WORKSPACE, owner_user_id=USER),
    ]
    calls = [(model, ENTITY), (Project, PROJECT), (Workspace, WORKSPACE)]
    if missing:
        index = ["entity", "project", "workspace"].index(missing)
        chain = chain[:index] + [None]
        calls = calls[: index + 1]
    session.get.side_effect = chain
    actual = await getattr(db, name)(session, **{id_arg: ENTITY})
    assert [call.args for call in session.get.await_args_list] == calls
    assert actual == (None if missing else scope_type(USER, WORKSPACE, PROJECT))
    session.execute.assert_not_awaited()


@pytest.mark.parametrize("dialect", ["sqlite", None])
async def test_setting_context_without_postgresql_is_a_noop(dialect):
    session = session_stub(dialect)
    await db.set_rls_context(session, user_id=USER, workspace_id=WORKSPACE, project_id=PROJECT)
    session.execute.assert_not_awaited()


async def test_context_is_transaction_local_and_omitted_values_clear_previous_scope():
    session = session_stub()
    await db.set_rls_context(session, user_id=USER, workspace_id=WORKSPACE, project_id=PROJECT)
    await db.set_rls_context(session, user_id=USER)
    calls = session.execute.await_args_list
    keys = ["app.current_user_id", "app.current_workspace_id", "app.current_project_id"]
    for call, key, value in zip(calls[:3], keys, [USER, WORKSPACE, PROJECT], strict=True):
        assert str(call.args[0]) == "SELECT set_config(:k, :v, true)"
        assert call.args[1] == {"k": key, "v": str(value)}
    assert calls[3].args[1] == {"k": keys[0], "v": str(USER)}
    for call, key in zip(calls[4:], keys[1:], strict=True):
        assert str(call.args[0]) == f"SELECT set_config('{key}', '', true)"
    session.commit.assert_not_called()


@pytest.mark.parametrize("kind", ["node_run", "artifact"])
@pytest.mark.parametrize("found", [True, False])
async def test_context_setters_keep_db_monkeypatch_seams(monkeypatch, kind, found):
    session = session_stub()
    scope_type = db.NodeRunRlsScope if kind == "node_run" else db.ArtifactRlsScope
    scope = scope_type(USER, WORKSPACE, PROJECT) if found else None
    resolve = AsyncMock(return_value=scope)
    apply = AsyncMock()
    monkeypatch.setattr(db, f"resolve_{kind}_rls_scope", resolve)
    monkeypatch.setattr(db, "set_rls_context", apply)
    kwargs = {f"{kind}_id": ENTITY}
    if kind == "artifact":
        kwargs["expected_workspace_id"] = WORKSPACE
    assert await getattr(db, f"set_{kind}_rls_context")(session, **kwargs) is scope
    resolve.assert_awaited_once_with(session, **{f"{kind}_id": ENTITY})
    if found:
        apply.assert_awaited_once_with(
            session,
            user_id=USER,
            workspace_id=WORKSPACE,
            project_id=PROJECT,
        )
    else:
        apply.assert_not_awaited()


async def test_artifact_scope_mismatch_never_applies_owner_context(monkeypatch):
    session = session_stub()
    monkeypatch.setattr(
        db,
        "resolve_artifact_rls_scope",
        AsyncMock(
            return_value=db.ArtifactRlsScope(USER, WORKSPACE, PROJECT),
        ),
    )
    apply = AsyncMock()
    monkeypatch.setattr(db, "set_rls_context", apply)
    assert (
        await db.set_artifact_rls_context(
            session,
            artifact_id=ENTITY,
            expected_workspace_id=uuid4(),
        )
        is None
    )
    apply.assert_not_awaited()


@pytest.mark.parametrize(
    "scope_type",
    [
        db.NodeRunRlsScope,
        db.ArtifactRlsScope,
        db.DirectorTurnRlsScope,
    ],
)
def test_resolved_scope_is_immutable(scope_type):
    scope = scope_type(USER, WORKSPACE, PROJECT)
    with pytest.raises(FrozenInstanceError):
        scope.project_id = uuid4()


@pytest.mark.parametrize(
    "name",
    [
        "list_pending_outbox_event_rls_scopes",
        "list_recoverable_director_turn_rls_scopes",
        "list_reconcilable_director_turn_rls_scopes",
    ],
)
@pytest.mark.parametrize("missing", ["project", "workspace", None])
async def test_non_postgresql_lists_skip_orphaned_ownership(name, missing):
    session = session_stub("sqlite")
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        SimpleNamespace(event_id=ENTITY, project_id=PROJECT),
    ]
    result.tuples.return_value.all.return_value = [(ENTITY, PROJECT)]
    session.execute.return_value = result
    project = SimpleNamespace(id=PROJECT, workspace_id=WORKSPACE)
    workspace = SimpleNamespace(id=WORKSPACE, owner_user_id=USER)
    session.get.side_effect = {
        "project": [None],
        "workspace": [project, None],
        None: [project, workspace],
    }[missing]

    actual = await getattr(db, name)(session, limit=7)

    if missing:
        assert actual == []
    elif name == "list_pending_outbox_event_rls_scopes":
        assert actual == [db.OutboxEventRlsScope(ENTITY, USER, WORKSPACE, PROJECT)]
    else:
        assert actual == [(ENTITY, db.DirectorTurnRlsScope(USER, WORKSPACE, PROJECT))]
    assert session.get.await_count == (1 if missing == "project" else 2)


async def test_non_project_outbox_event_retains_explicit_empty_scope():
    session = session_stub("sqlite")
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        SimpleNamespace(event_id=ENTITY, project_id=None),
    ]
    session.execute.return_value = result
    assert await db.list_pending_outbox_event_rls_scopes(session, limit=7) == [
        db.OutboxEventRlsScope(ENTITY, None, None, None),
    ]
    session.get.assert_not_awaited()


@pytest.mark.parametrize(
    "name",
    [
        "list_queued_node_run_rls_scopes",
        "list_resumable_provider_node_run_rls_scopes",
    ],
)
async def test_node_run_lists_keep_source_commit_filter_and_skip_missing_scope(name):
    session = session_stub("sqlite")
    orphan_id = uuid4()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [orphan_id, ENTITY]
    session.execute.return_value = result
    session.get.side_effect = [
        None,
        SimpleNamespace(project_id=PROJECT),
        SimpleNamespace(id=PROJECT, workspace_id=WORKSPACE),
        SimpleNamespace(id=WORKSPACE, owner_user_id=USER),
    ]
    kwargs = {"limit": 7, "source_commit": "exact-commit"}
    if name == "list_queued_node_run_rls_scopes":
        kwargs["project_id"] = PROJECT
    assert await getattr(db, name)(session, **kwargs) == [
        (ENTITY, db.NodeRunRlsScope(USER, WORKSPACE, PROJECT)),
    ]
    statement = session.execute.await_args.args[0]
    params = statement.compile().params
    assert "exact-commit" in params.values()
    assert "source_commit" in params.values()
    assert 7 in params.values()
    if name == "list_queued_node_run_rls_scopes":
        assert PROJECT in params.values()
        assert "queued" in params.values()
    else:
        assert "unified-v1" in params.values()
        assert set(params["status_1"]) == {"running", "cancel_requested"}


async def test_session_with_rls_retains_factory_and_context_patch_points(monkeypatch):
    session = session_stub()
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=session)
    context_manager.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=context_manager)
    monkeypatch.setattr(db, "get_session_factory", lambda: factory)
    apply = AsyncMock()
    monkeypatch.setattr(db, "set_rls_context", apply)
    generator = db.get_session_with_rls(
        user_id=USER,
        workspace_id=WORKSPACE,
        project_id=PROJECT,
    )
    assert await anext(generator) is session
    apply.assert_awaited_once_with(
        session,
        user_id=USER,
        workspace_id=WORKSPACE,
        project_id=PROJECT,
    )
    await generator.aclose()
    context_manager.__aexit__.assert_awaited_once()
