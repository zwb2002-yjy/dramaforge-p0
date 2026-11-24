"""Controlled real-process upload barrier for the Final Film crash proof."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from app.config import get_settings
from app.execution.models import GraphNode, NodeRun
from app.production.final_film import execute_final_film_node_run
from app.shared.db import get_session_factory, set_node_run_rls_context
from app.shared.model_registry import load_all_models
from app.storage.minio_store import MinioObjectStore, StoredObject


class UploadBarrierStore(MinioObjectStore):
    async def put_file(self, *, object_key: str, path: Path, mime_type: str) -> StoredObject:
        stored = await super().put_file(object_key=object_key, path=path, mime_type=mime_type)
        print(
            json.dumps({"uploaded_key": stored.object_key, "scratch": str(path.parent)}), flush=True
        )
        # The parent sends an actual SIGKILL after verifying the remote object.
        await asyncio.Event().wait()
        raise AssertionError("Upload barrier unexpectedly released")


async def main() -> None:
    load_all_models()
    run_id = UUID(sys.argv[1])
    async with get_session_factory()() as session:
        assert await set_node_run_rls_context(session, node_run_id=run_id)
        run = await session.get(NodeRun, run_id)
        assert run is not None
        node = await session.get(GraphNode, run.graph_node_id)
        assert node is not None
        run.status = "running"
        await session.commit()
        await execute_final_film_node_run(
            session, run=run, node=node, obj_store=UploadBarrierStore(get_settings())
        )


if __name__ == "__main__":
    asyncio.run(main())
