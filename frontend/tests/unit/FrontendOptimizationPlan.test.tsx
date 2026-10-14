import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SceneWorkspace } from "../../src/features/scenes/SceneWorkspace";
import { SceneAnimaticPreview } from "../../src/features/scenes/SceneAnimaticPreview";
import { ShotCandidateTray } from "../../src/features/shots/ShotCandidateTray";
import { ShotProductionActions } from "../../src/features/shots/ShotProductionActions";
import type { ShotExecutionReference, ShotLite } from "../../src/features/shots/api";
import type { BindingLite } from "../../src/features/scenes/api";

const PROJECT_ID = "test-project-ac";
const SCENE_ID = "test-scene-ac";

const SHOT_IMAGE_STAGE: ShotLite = {
  id: "shot-img-1",
  project_id: PROJECT_ID,
  scene_id: SCENE_ID,
  shot_number: 1,
  shot_type: "close_up",
  camera_move: "slow_zoom_in",
  visual_description: "主角凝视窗外风雨",
  dialogue: "这雨不会停了。",
  duration_seconds: "3.5",
  status: "draft",
  sort_order: 1,
  version: 1,
  director_state: {},
  image_prompt: "雨夜窗前特写",
  video_prompt: "",
  formal_keyframe_artifact_id: null,
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};

const SHOT_VIDEO_STAGE: ShotLite = {
  id: "shot-vid-2",
  project_id: PROJECT_ID,
  scene_id: SCENE_ID,
  shot_number: 2,
  shot_type: "medium",
  camera_move: "pan_right",
  visual_description: "主角推门而出",
  dialogue: "",
  duration_seconds: "4.0",
  status: "draft",
  sort_order: 2,
  version: 2,
  director_state: {},
  image_prompt: "",
  video_prompt: "推门走进雨中",
  formal_keyframe_artifact_id: "artifact-kf-2",
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};

const SHOT_COMPLETED: ShotLite = {
  id: "shot-comp-3",
  project_id: PROJECT_ID,
  scene_id: SCENE_ID,
  shot_number: 3,
  shot_type: "wide",
  camera_move: "static",
  visual_description: "背影消失在街角",
  dialogue: "",
  duration_seconds: "3.0",
  status: "completed",
  sort_order: 3,
  version: 3,
  director_state: {},
  image_prompt: "",
  video_prompt: "",
  formal_keyframe_artifact_id: "artifact-kf-3",
  formal_video_artifact_id: "artifact-vid-3",
  formal_composite_artifact_id: null,
};

const REFERENCES: ShotExecutionReference[] = [
  {
    purpose: "identity",
    artifact_id: "artifact-char-ref-1",
    resolution_mode: "current_formal",
    mime_type: "image/png",
  },
];
const BINDINGS: BindingLite[] = [
  {
    id: "reference-binding",
    purpose: "identity",
    label: "主角",
    asset_id: "asset-character",
    asset_version_id: "asset-version",
    artifact_id: "artifact-char-ref-1",
    resolution_mode: "current_formal",
    stage: "image_keyframe",
    version: 1,
  },
];

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function mockWorkspaceApi(modelReady = true) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-token" });

    if (url.includes("/workspace") && method === "GET") {
      return json({
        scene: {
          id: SCENE_ID,
          episode_id: "ep-1",
          episode_number: 1,
          scene_number: 1,
          location_name: "雨夜车站",
          time_of_day: "night",
          synopsis: "主角离开的雨夜",
          version: 1,
          design_state: {},
        },
        shots: [SHOT_IMAGE_STAGE, SHOT_VIDEO_STAGE, SHOT_COMPLETED],
        references: { [SHOT_IMAGE_STAGE.id]: BINDINGS, [SHOT_VIDEO_STAGE.id]: BINDINGS },
        candidates: {
          [SHOT_IMAGE_STAGE.id]: [],
          [SHOT_VIDEO_STAGE.id]: [
            {
              artifact_id: "candidate-vid-artifact",
              node_run_id: "run-video-1",
              node_key: "video",
              stage: "video",
              status: "completed",
              artifact_type: "video",
              mime_type: "video/mp4",
              storage_state: "stored",
              review_allowed: true,
              review_decision: "approved",
            },
          ],
        },
        trace: {},
      });
    }

    if (url.includes("/execution-models/preflight")) {
      return json({
        project_id: PROJECT_ID,
        stages: [
          {
            stage: "image_keyframe",
            ready: modelReady,
            source: "project_binding",
            requested_model_id: "agnes/agnes-image-2.1-flash",
            resolved_model_id: "agnes/agnes-image-2.1-flash",
            contract_display_name: "Agnes 图像生成",
            binding_id: "binding-img",
            reason: modelReady ? null : "MODEL_BINDING_MISSING",
          },
          {
            stage: "video",
            ready: true,
            source: "project_binding",
            requested_model_id: "agnes/agnes-video-v2.0",
            resolved_model_id: "agnes/agnes-video-v2.0",
            contract_display_name: "Agnes 视频生成",
            binding_id: "binding-vid",
            reason: null,
          },
        ],
      });
    }

    if (url.includes("/model-catalog") || url.endsWith("/models")) {
      return json([
        {
          id: "agnes/agnes-image-2.1-flash",
          display_name: "Agnes 图像生成",
          capabilities: ["image.generate"],
        },
        {
          id: "agnes/agnes-video-v2.0",
          display_name: "Agnes 视频生成",
          capabilities: ["video.shot"],
        },
      ]);
    }

    if (url.includes("/workspaces")) {
      return json([
        {
          id: "ws-1",
          name: "个人空间",
          role: "owner",
          is_default: true,
        },
      ]);
    }

    if (url.includes("/provider-connections")) {
      return json([]);
    }

    return json({});
  });
}

describe("Frontend Optimization Plan - Acceptance Criteria Verification", () => {
  beforeEach(() => {
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("AC 1: Immersive Model Settings Drawer opens without leaving canvas", async () => {
    mockWorkspaceApi(false);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <SceneWorkspace
          projectId={PROJECT_ID}
          sceneId={SCENE_ID}
          initialShotId={SHOT_IMAGE_STAGE.id}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("scene-workspace")).toBeInTheDocument();
    expect(await screen.findByText("雨夜车站")).toBeInTheDocument();

    // Verify trigger opens drawer in-place without page reload
    const inspector = await screen.findByTestId("shot-inspector");
    expect(inspector).toBeInTheDocument();

    // The drawer is not rendered until opened
    expect(screen.queryByTestId("scene-model-settings-drawer")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "去设置模型" }));
    expect(await screen.findByTestId("scene-model-settings-drawer")).toBeInTheDocument();
    expect(screen.getByTestId("cinematic-canvas")).toHaveAttribute(
      "data-shot-id",
      SHOT_IMAGE_STAGE.id,
    );
    fireEvent.click(screen.getByRole("button", { name: /^关闭$/ }));
    expect(screen.queryByTestId("scene-model-settings-drawer")).not.toBeInTheDocument();

    // Verify 场景连播 button is in the scene header and can launch the player modal
    const playBtn = screen.getByTestId("scene-animatic-play-btn");
    expect(playBtn).toBeInTheDocument();
    fireEvent.click(playBtn);
    expect(await screen.findByTestId("scene-animatic-player-dialog")).toBeInTheDocument();
    const closeButtons = screen.getAllByRole("button", { name: "关闭" });
    fireEvent.click(closeButtons[0]);
    expect(screen.queryByTestId("scene-animatic-player-dialog")).not.toBeInTheDocument();
  });

  it("AC 2: Phase-Dynamic Model Binding isolates model per active stage", async () => {
    mockWorkspaceApi();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    // 1. Keyframe stage: shot has NO formal keyframe -> shows 生图模型 (画面打样)
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <ShotProductionActions projectId={PROJECT_ID} shot={SHOT_IMAGE_STAGE} dirty={false} />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("shot-production-preflight")).toHaveAttribute(
        "data-active-stage",
        "image_keyframe",
      ),
    );
    expect(screen.getByTestId("production-stage-indicator")).toHaveTextContent("画面打样");
    expect(screen.getByTestId("production-preflight-image_keyframe")).toHaveTextContent("生图模型");
    expect(screen.getByTestId("generate-keyframe")).toBeInTheDocument();

    // 2. Video stage: shot HAS formal keyframe -> isolates and focuses 视频模型 (视频生成)
    rerender(
      <QueryClientProvider client={queryClient}>
        <ShotProductionActions projectId={PROJECT_ID} shot={SHOT_VIDEO_STAGE} dirty={false} />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("shot-production-preflight")).toHaveAttribute(
        "data-active-stage",
        "video",
      ),
    );
    expect(screen.getByTestId("production-stage-indicator")).toHaveTextContent(
      "视频生成 (正式画面作为首帧)",
    );
    expect(screen.getByTestId("production-preflight-video")).toHaveTextContent("视频模型");
    expect(screen.getByTestId("production-preflight-source-frame")).toHaveTextContent(
      "已绑定正式关键帧",
    );
    expect(screen.getByTestId("generate-video")).toBeInTheDocument();
  });

  it("AC 3: Dirty-State Blocker guards shot strip switching until discard", async () => {
    mockWorkspaceApi();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <SceneWorkspace
          projectId={PROJECT_ID}
          sceneId={SCENE_ID}
          initialShotId={SHOT_IMAGE_STAGE.id}
        />
      </QueryClientProvider>,
    );

    await screen.findByText("雨夜车站");

    // Modify visual description text in ShotDesignPanel
    const visualInput = screen.getByLabelText("画面描述");
    fireEvent.change(visualInput, { target: { value: "修改后的画面描述：狂风大作" } });

    // Status changes to un-saved
    expect(await screen.findByTestId("shot-design-dirty")).toBeInTheDocument();

    // Click on another shot in the ShotStrip
    fireEvent.click(screen.getByTestId(`shot-strip-card-${SHOT_VIDEO_STAGE.id}`));

    // Intercepted! Unsaved changes warning dialog pops up
    expect(await screen.findByTestId("unsaved-changes-guard")).toBeInTheDocument();
    expect(screen.getByText("切换镜头前先处理当前草稿")).toBeInTheDocument();

    // Canvas still stays on shot 1
    expect(screen.getByTestId("cinematic-canvas")).toHaveAttribute(
      "data-shot-id",
      SHOT_IMAGE_STAGE.id,
    );

    // Click return to save keeps user on shot 1
    fireEvent.click(screen.getByRole("button", { name: "返回保存" }));
    expect(screen.queryByTestId("unsaved-changes-guard")).not.toBeInTheDocument();

    // Click another shot again, then confirm discard
    fireEvent.click(screen.getByTestId(`shot-strip-card-${SHOT_VIDEO_STAGE.id}`));
    expect(await screen.findByTestId("unsaved-changes-guard")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "放弃并切换" }));

    // Now switched to shot 2!
    await waitFor(() => {
      expect(screen.getByTestId("cinematic-canvas")).toHaveAttribute(
        "data-shot-id",
        SHOT_VIDEO_STAGE.id,
      );
    });
  });

  it("AC 4: Scene Animatic Player and Continuity Reference Overlay", async () => {
    mockWorkspaceApi();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    // 1. Animatic Player: launches continuous sequence preview
    render(
      <SceneAnimaticPreview
        projectId={PROJECT_ID}
        shots={[SHOT_IMAGE_STAGE, SHOT_VIDEO_STAGE, SHOT_COMPLETED]}
      />,
    );

    expect(screen.getByTestId("scene-animatic")).toHaveAttribute(
      "data-shot-id",
      SHOT_IMAGE_STAGE.id,
    );
    expect(screen.getByText("对白参考：这雨不会停了。")).toBeInTheDocument();
    expect(screen.getByTestId("animatic-play-toggle")).toHaveTextContent("播放");

    // Stepper to next shot
    fireEvent.click(screen.getByRole("button", { name: "下一镜" }));
    expect(screen.getByAltText("镜头 2 正式画面")).toBeInTheDocument();

    // Stepper to shot 3 (which has video)
    fireEvent.click(screen.getByRole("button", { name: "下一镜" }));
    expect(screen.getByTestId("scene-animatic")).toHaveAttribute("data-shot-id", SHOT_COMPLETED.id);
    expect(screen.getByLabelText<HTMLVideoElement>("动态分镜视频").muted).toBe(true);

    // 2. Continuity Overlay: in ShotCandidateTray, allows toggling character reference baseline
    const candidates = [
      {
        artifact_id: "candidate-test-video",
        node_run_id: "run-video-test",
        node_key: "video",
        stage: "video",
        status: "completed",
        artifact_type: "video",
        mime_type: "video/mp4",
        storage_state: "stored",
        review_allowed: true,
        review_decision: "approved",
      },
    ];

    render(
      <QueryClientProvider client={queryClient}>
        <ShotCandidateTray
          projectId={PROJECT_ID}
          shot={SHOT_VIDEO_STAGE}
          candidates={candidates}
          references={REFERENCES}
        />
      </QueryClientProvider>,
    );

    // The continuity comparison button is rendered
    const compareBtn = screen.getByTestId("shot-candidate-continuity-candidate-test-video");
    expect(compareBtn).toHaveTextContent("对比设定");

    // Clicking reveals character baseline reference overlay
    fireEvent.click(compareBtn);
    expect(screen.getByTestId("shot-continuity-overlay-candidate-test-video")).toBeInTheDocument();
    expect(screen.getByText(/角色基准设定图/)).toBeInTheDocument();
    expect(screen.getByText("角色基准")).toBeInTheDocument();

    // Toggling collapses it
    fireEvent.click(compareBtn);
    expect(
      screen.queryByTestId("shot-continuity-overlay-candidate-test-video"),
    ).not.toBeInTheDocument();
  });
});
