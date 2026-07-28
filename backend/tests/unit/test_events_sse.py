"""SSE workspace filtering tests."""

from __future__ import annotations

import asyncio

from app.events.sse import SseHub


def test_workspace_stream_excludes_other_workspace_and_unscoped_events() -> None:
    async def run() -> None:
        hub = SseHub()
        hub.publish(event="node.completed", data={"workspace_id": "workspace-a", "run": "a"})
        hub.publish(event="node.completed", data={"workspace_id": "workspace-b", "run": "b"})
        hub.publish(event="node.completed", data={"run": "unscoped"})

        stream = hub.stream(workspace_id="workspace-a")
        event = await anext(stream)
        assert event.data == {"workspace_id": "workspace-a", "run": "a"}
        await stream.aclose()

    asyncio.run(run())
