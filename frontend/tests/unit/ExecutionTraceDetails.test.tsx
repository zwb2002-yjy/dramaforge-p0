import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShotDetailsPanel } from "../../src/features/shots/ShotDetailsPanel";
import { fetchExecutionTrace } from "../../src/lib/api";

vi.mock("../../src/lib/api", () => ({ fetchExecutionTrace: vi.fn() }));
vi.mock("../../src/features/shots/changeProposalsApi", () => ({
  listShotChangeProposals: vi.fn().mockResolvedValue([]),
  confirmShotChangeProposal: vi.fn(),
}));

afterEach(() => vi.clearAllMocks());

describe("Execution trace details", () => {
  it("loads the full secret-free trace on demand for one run", async () => {
    vi.mocked(fetchExecutionTrace).mockResolvedValue({
      run_id: "run-1",
      node_key: "video",
      status: "completed",
      director_intent: {},
      prompt: "a rainy street",
      resolved_asset_versions: [],
      model_binding: {},
      capability: "video.image_to_video",
      approximations: [],
      actual_provider: "agnes",
      actual_model: "agnes-video-v2.0",
      operation_status: "succeeded",
      operation_outcome_unknown: false,
      effective_request_redacted: {},
      artifact: null,
    });

    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ShotDetailsPanel
          open
          projectId="project-1"
          shot={{
            id: "shot-1",
            project_id: "project-1",
            scene_id: "scene-1",
            shot_number: 1,
            shot_type: "medium",
            camera_move: "static",
            visual_description: "A rainy street",
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
          }}
          trace={[{ node_run_id: "run-1", node_key: "video", status: "completed" }]}
          onClose={vi.fn()}
        />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "查看完整证据" }));
    await waitFor(() => expect(fetchExecutionTrace).toHaveBeenCalledWith("project-1", "run-1"));
    expect(await screen.findByTestId("execution-trace-detail")).toHaveTextContent(
      "agnes-video-v2.0",
    );
    expect(screen.getByTestId("execution-trace-detail")).not.toHaveTextContent("a rainy street");
  });
});
