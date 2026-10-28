import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { ShotDetailsBody } from "../../src/features/shots/ShotDetailsPanel";
import type { ShotLite } from "../../src/features/shots/api";
import { fetchExecutionTrace, type ExecutionTraceRead } from "../../src/lib/api";

vi.mock("../../src/lib/api", () => ({ fetchExecutionTrace: vi.fn() }));
afterEach(() => vi.clearAllMocks());

function shot(id: string): ShotLite {
  return {
    id,
    project_id: "project",
    scene_id: "scene",
    shot_number: 1,
    shot_type: "medium",
    camera_move: "static",
    visual_description: "Saved",
    dialogue: "",
    duration_seconds: "3",
    status: "draft",
    sort_order: 1,
    version: 1,
    director_state: {},
    image_prompt: "",
    video_prompt: "",
    formal_keyframe_artifact_id: null,
    formal_video_artifact_id: null,
    formal_composite_artifact_id: null,
  };
}

function detail(id: string): ExecutionTraceRead {
  return {
    run_id: id,
    node_key: "video",
    status: "completed",
    director_intent: {},
    prompt: "",
    resolved_asset_versions: [],
    model_binding: {},
    capability: "video.image_to_video",
    approximations: [],
    actual_provider: "provider",
    actual_model: id,
    operation_status: "succeeded",
    operation_outcome_unknown: false,
    effective_request_redacted: {},
    artifact: null,
  };
}

it("aborts the old Run query on Shot switch and never displays its late response", async () => {
  let release!: (value: ExecutionTraceRead) => void;
  const previous = new Promise<ExecutionTraceRead>((resolve) => {
    release = resolve;
  });
  const signals: AbortSignal[] = [];
  vi.mocked(fetchExecutionTrace).mockImplementation((_project, run, signal) => {
    signals.push(signal!);
    return run === "old-run" ? previous : Promise.resolve(detail("current-run"));
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const body = (id: string, run: string) => (
    <QueryClientProvider client={client}>
      <ShotDetailsBody
        projectId="project"
        shot={shot(id)}
        trace={[{ node_run_id: run, node_key: "video", status: "completed" }]}
      />
    </QueryClientProvider>
  );
  const view = render(body("old-shot", "old-run"));
  fireEvent.click(screen.getByRole("button", { name: "查看完整证据" }));
  await waitFor(() => expect(signals).toHaveLength(1));
  view.rerender(body("current-shot", "current-run"));
  await waitFor(() => expect(signals[0]?.aborted).toBe(true));
  expect(screen.queryByTestId("execution-trace-detail")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "查看完整证据" }));
  expect(await screen.findByTestId("execution-trace-detail")).toHaveTextContent("current-run");
  await act(async () => release(detail("old-run")));
  expect(screen.getByTestId("execution-trace-detail")).not.toHaveTextContent("old-run");
});

it("retries a failed read only after the user requests the same Run again", async () => {
  vi.mocked(fetchExecutionTrace)
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue(detail("current-run"));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ShotDetailsBody
        projectId="project"
        shot={shot("current-shot")}
        trace={[{ node_run_id: "current-run", node_key: "video", status: "completed" }]}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "查看完整证据" }));
  expect(await screen.findByTestId("execution-trace-error")).toHaveTextContent("读取失败");
  expect(fetchExecutionTrace).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "重新读取执行记录" }));
  expect(await screen.findByTestId("execution-trace-detail")).toHaveTextContent("current-run");
  expect(fetchExecutionTrace).toHaveBeenCalledTimes(2);
});
