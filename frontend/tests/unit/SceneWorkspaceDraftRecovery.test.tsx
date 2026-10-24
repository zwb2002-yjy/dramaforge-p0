import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SceneWorkspace } from "../../src/features/scenes/SceneWorkspace";
import {
  saveShotDraft,
  loadShotDraft,
  shotDraftFromServer,
} from "../../src/features/shots/shotDraftStorage";
import { selectValue } from "./selectValue";
import { queryKeys } from "../../src/lib/queryKeys";

const mockSceneWorkspaceData = {
  scene: {
    id: "scene-1",
    episode_id: "ep-1",
    episode_number: 1,
    scene_number: 1,
    location_name: "Rain Station",
    time_of_day: "night",
    synopsis: "Lin Xia waits under the canopy.",
    design_state: {},
  },
  shots: [
    {
      id: "shot-1",
      scene_id: "scene-1",
      shot_number: 1,
      sort_order: 1,
      version: 2,
      visual_description: "Rain streaks the platform.",
      image_prompt: "server image prompt",
      video_prompt: "server video prompt",
      dialogue: "Lin Xia: Last train is late.",
      director_state: {},
      formal_keyframe_artifact_id: null,
      formal_video_artifact_id: null,
    },
  ],
  candidates: {},
  trace: {},
};

describe("SceneWorkspace Draft Recovery", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("surfaces recovery banner when uncommitted draft is in storage, and restores on user click", async () => {
    // Save draft in storage before mounting
    saveShotDraft("proj-1", "shot-1", 2, {
      image_prompt: "recovered local edit",
      video_prompt: "server video prompt",
      dialogue: "recovered dialogue",
      director_state: { camera: "pan" },
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(
      queryKeys.scene.workspace("proj-1", "scene-1"),
      mockSceneWorkspaceData,
    );

    render(
      <QueryClientProvider client={queryClient}>
        <SceneWorkspace projectId="proj-1" sceneId="scene-1" initialShotId="shot-1" />
      </QueryClientProvider>,
    );

    // Expect the recoverable draft banner to be visible
    expect(await screen.findByTestId("recoverable-draft-banner")).toBeInTheDocument();
    expect(screen.getByText("发现未保存的本地草稿")).toBeInTheDocument();

    const restoreBtn = screen.getByRole("button", { name: "恢复草稿" });
    fireEvent.click(restoreBtn);

    // After restoring, banner disappears and draft is marked dirty / populated
    expect(screen.queryByTestId("recoverable-draft-banner")).not.toBeInTheDocument();
  });

  it("allows user to discard uncommitted draft", async () => {
    saveShotDraft("proj-1", "shot-1", 2, {
      image_prompt: "unwanted local edit",
      video_prompt: "server video prompt",
      director_state: {},
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(
      queryKeys.scene.workspace("proj-1", "scene-1"),
      mockSceneWorkspaceData,
    );

    render(
      <QueryClientProvider client={queryClient}>
        <SceneWorkspace projectId="proj-1" sceneId="scene-1" initialShotId="shot-1" />
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("recoverable-draft-banner")).toBeInTheDocument();

    const discardBtn = screen.getByRole("button", { name: "放弃本地草稿" });
    fireEvent.click(discardBtn);

    expect(screen.queryByTestId("recoverable-draft-banner")).not.toBeInTheDocument();
  });

  it("resolves a concurrent prompt per field while retaining an unrelated new server duration", async () => {
    const original = mockSceneWorkspaceData.shots[0];
    const baseline = shotDraftFromServer(original);
    saveShotDraft("proj-1", original.id, 2, { ...baseline, image_prompt: "local image" }, baseline);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.scene.workspace("proj-1", "scene-1"), {
      ...mockSceneWorkspaceData,
      shots: [
        {
          ...original,
          version: 3,
          image_prompt: "concurrent image",
          director_state: { generation_settings: { video: { request_duration_seconds: 4 } } },
        },
      ],
    });
    render(
      <QueryClientProvider client={queryClient}>
        <SceneWorkspace projectId="proj-1" sceneId="scene-1" initialShotId={original.id} />
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "核对并恢复草稿" }));
    const apply = screen.getByRole("button", { name: "恢复选定修改到草稿" });
    expect(apply).toBeDisabled();
    expect(screen.getByTestId("shot-draft-recovery-dialog")).toHaveTextContent("concurrent image");
    await selectValue(screen.getByLabelText("恢复字段 image_prompt"), "local");
    fireEvent.click(apply);
    const restored = loadShotDraft("proj-1", original.id);
    expect(restored?.baselineVersion).toBe(3);
    expect(restored?.draft.image_prompt).toBe("local image");
    expect(restored?.draft.director_state).toEqual({
      generation_settings: { video: { request_duration_seconds: 4 } },
    });
    expect(screen.getByTestId("shot-design-dirty")).toBeInTheDocument();
  });
});
