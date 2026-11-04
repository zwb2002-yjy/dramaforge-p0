import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { queryKeys } from "../../src/lib/queryKeys";

import { ShotDetailsBody } from "../../src/features/shots/ShotDetailsPanel";

const SHOT = {
  id: "shot-1",
  project_id: "project-1",
  scene_id: "scene-1",
  shot_number: 3,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "A turns",
  dialogue: "",
  duration_seconds: "4",
  status: "draft",
  sort_order: 3,
  version: 7,
  director_state: {},
  image_prompt: "",
  video_prompt: "",
  formal_keyframe_artifact_id: "formal-kf",
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};

describe("ShotDetailsPanel", () => {
  it("opens the latest failed run and shows the HTTP boundary rather than claiming acceptance", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { staleTime: Infinity, retry: false } },
    });
    client.setQueryData(queryKeys.shot.executionTrace("project-1", SHOT.id, "failed-run"), {
      run_id: "failed-run",
      status: "failed",
      node_key: "video",
      operation_status: "failed",
      actual_model: "agnes-video-2.5-flash",
      submission_diagnostics: {
        phase: "response_received",
        http_status: 503,
        endpoint: "https://api.agnes-ai.cn/v1/videos",
        duration_ms: 145,
        response_error: "No healthy upstream",
        response_request_id: "req-503",
      },
    });
    render(
      <QueryClientProvider client={client}>
        <ShotDetailsBody
          projectId="project-1"
          shot={SHOT}
          trace={[{ node_run_id: "failed-run", node_key: "video", status: "failed" }]}
        />
      </QueryClientProvider>,
    );
    const status = await screen.findByTestId("execution-submission-status");
    expect(status).toHaveTextContent("未取得远端任务 ID");
    expect(status).toHaveTextContent("HTTP 503");
    expect(status).toHaveTextContent("No healthy upstream");
    expect(screen.getByTestId("execution-trace-diagnostics")).toHaveTextContent("req-503");
  });

  it("surfaces shot metadata and production trace on demand", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ShotDetailsBody
          shot={SHOT}
          trace={[{ node_run_id: "run-1", node_key: "keyframe", status: "completed" }]}
        />
      </QueryClientProvider>,
    );

    const sheet = screen.getByTestId("shot-details-sheet");
    expect(sheet).toHaveAttribute("data-shot-id", "shot-1");
    expect(sheet).toHaveTextContent("v7");
    // Status and confirmed artifacts speak product vocabulary; the stored tokens
    // and artifact ids stay in the collapsed diagnostics block.
    expect(screen.getByTestId("shot-details-status")).toHaveTextContent("草稿");
    const body = (() => {
      const clone = sheet.cloneNode(true) as HTMLElement;
      clone.querySelectorAll(".ant-collapse").forEach((element) => element.remove());
      return clone.textContent ?? "";
    })();
    expect(body).toContain("已确认");
    expect(body).toContain("未确认");
    expect(body).not.toContain("formal-kf");
    expect(body).not.toContain("draft");
    const ownDiagnostics = screen.getByTestId("shot-details-diagnostics");
    expect(ownDiagnostics).toHaveTextContent("formal-kf");
    expect(ownDiagnostics).not.toHaveAttribute("open");
    expect(screen.getByTestId("shot-production-trace")).toHaveAttribute("data-shot-id", "shot-1");
    // The trace speaks product vocabulary; the stored token stays in the
    // collapsed diagnostics block instead of the ordinary surface.
    const trace = screen.getByTestId("shot-production-trace");
    const visible = (() => {
      const clone = trace.cloneNode(true) as HTMLElement;
      clone.querySelectorAll(".ant-collapse").forEach((element) => element.remove());
      return clone.textContent ?? "";
    })();
    expect(visible).toContain("已完成");
    expect(visible).not.toContain("completed");
  });
});
