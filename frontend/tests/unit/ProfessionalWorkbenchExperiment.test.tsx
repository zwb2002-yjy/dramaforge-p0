import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProfessionalWorkbench } from "../../src/features/production/ProfessionalWorkbench";
import { ApiError } from "../../src/lib/api";
import type { ExperimentRead, ModelRead, ShotRead } from "../../src/lib/api";
import type { ModelCandidateRead } from "../../src/features/production/modelCandidatesApi";

const SHOT = {
  id: "shot-4",
  project_id: "project-1",
  scene_id: "scene-1",
  shot_number: 4,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "A turns",
  dialogue: "",
  duration_seconds: "4",
  status: "draft",
  sort_order: 4,
  version: 6,
  director_state: {},
  image_prompt: "",
  video_prompt: "",
  formal_keyframe_artifact_id: "kf-4",
  formal_video_artifact_id: "video-4",
  formal_composite_artifact_id: null,
} as unknown as ShotRead;

const MODELS: ModelRead[] = [
  {
    id: "agnes/agnes-image-2.1-flash",
    provider_id: "agnes",
    display_name: "Agnes Image Flash",
    enabled: true,
    configured: true,
    available: true,
    capabilities: ["image.generate"],
  },
  {
    id: "agnes/agnes-video-v2.0",
    provider_id: "agnes",
    display_name: "Agnes Video V2.0",
    enabled: true,
    configured: true,
    available: true,
    capabilities: ["video.generate"],
  },
];

function candidate(overrides: Partial<ModelCandidateRead>): ModelCandidateRead {
  return {
    model_binding_id: "e897c142-6bca-4fa4-be90-11f1eda2673e",
    provider: "agnes",
    profile: "agnes",
    model_id: "agnes-image-2.1-flash",
    display_name: "Agnes Image Flash",
    purpose: "keyframe",
    eligible: true,
    supported_capabilities: ["image.generate"],
    unmet_preferences: [],
    evidence: {},
    issues: [],
    estimated_cost: null,
    ...overrides,
  };
}

function experiment(overrides: Partial<ExperimentRead> = {}): ExperimentRead {
  return {
    id: "exp-1",
    project_id: "project-1",
    source_shot_id: "shot-4",
    name: "镜头4 关键帧模型实验",
    branch_type: "model_experiment",
    status: "draft",
    source_artifact_ids: [],
    candidate_artifact_ids: [],
    comparison: {},
    adopted_shot_ids: [],
    parameters: { target_node_key: "keyframe" },
    selected_model: "agnes/agnes-image-2.1-flash",
    created_at: "2026-09-18T12:00:00Z",
    decided_at: null,
    ...overrides,
  } as unknown as ExperimentRead;
}

function renderPanel(overrides: {
  modelCandidates?: { keyframe?: ModelCandidateRead[]; video?: ModelCandidateRead[] };
  experiments?: ExperimentRead[];
  onCreateExperiment?: (input: {
    name: string;
    selected_model: string;
    targetNodeKey: "keyframe" | "video";
  }) => Promise<void>;
  onStartExperiment?: (experimentId: string, targetNodeKey: "keyframe" | "video") => Promise<void>;
}) {
  const onCreateExperiment = overrides.onCreateExperiment ?? vi.fn(async () => {});
  render(
    <ProfessionalWorkbench
      experimentsOnly
      projectId="project-1"
      shots={[SHOT]}
      selectedShotId="shot-4"
      onSelectShot={vi.fn()}
      experiments={overrides.experiments ?? []}
      models={MODELS}
      modelCandidates={overrides.modelCandidates ?? { keyframe: [], video: [] }}
      onCreateExperiment={onCreateExperiment}
      onStartExperiment={overrides.onStartExperiment ?? vi.fn(async () => {})}
      onDecideExperiment={vi.fn(async () => {})}
    />,
  );
  return { onCreateExperiment };
}

describe("ProfessionalWorkbench experiment branch", () => {
  it("creates the experiment on the stage the Owner chose", async () => {
    const { onCreateExperiment } = renderPanel({
      modelCandidates: {
        keyframe: [candidate({})],
        video: [
          candidate({
            model_binding_id: "586179ca-f511-44cc-91be-c11a38184cbc",
            model_id: "agnes-video-v2.0",
            display_name: "Agnes Video V2.0",
            purpose: "video",
            supported_capabilities: ["video.generate"],
          }),
        ],
      },
    });
    fireEvent.change(screen.getByLabelText("实验名称"), {
      target: { value: "镜头4 关键帧模型实验" },
    });
    fireEvent.change(screen.getByLabelText("实验模型"), {
      target: { value: "agnes/agnes-image-2.1-flash" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建实验分支" }));

    await waitFor(() => expect(onCreateExperiment).toHaveBeenCalledTimes(1));
    expect(onCreateExperiment).toHaveBeenCalledWith({
      name: "镜头4 关键帧模型实验",
      selected_model: "agnes/agnes-image-2.1-flash",
      targetNodeKey: "keyframe",
    });

    // Switching the stage carries the video model's binding through unchanged.
    // A successful create clears the form, so the second one is filled again.
    fireEvent.change(screen.getByLabelText("实验阶段"), { target: { value: "video" } });
    fireEvent.change(screen.getByLabelText("实验名称"), {
      target: { value: "镜头4 视频模型实验" },
    });
    fireEvent.change(screen.getByLabelText("实验模型"), {
      target: { value: "agnes/agnes-video-v2.0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建实验分支" }));
    await waitFor(() => expect(onCreateExperiment).toHaveBeenCalledTimes(2));
    expect(onCreateExperiment).toHaveBeenLastCalledWith({
      name: "镜头4 视频模型实验",
      selected_model: "agnes/agnes-video-v2.0",
      targetNodeKey: "video",
    });
  });

  it("refuses a model that has no binding for the chosen stage instead of failing at start", () => {
    renderPanel({
      modelCandidates: {
        keyframe: [candidate({})],
        video: [
          candidate({
            model_binding_id: "586179ca-f511-44cc-91be-c11a38184cbc",
            model_id: "agnes-video-v2.0",
            display_name: "Agnes Video V2.0",
            purpose: "video",
            supported_capabilities: ["video.generate"],
          }),
        ],
      },
    });
    const imageOption = screen.getByRole("option", {
      name: /Agnes Image Flash/,
    }) as HTMLOptionElement;
    const videoOption = screen.getByRole("option", {
      name: /Agnes Video V2.0/,
    }) as HTMLOptionElement;
    // Keyframe stage is the default, so the video-only model is not selectable.
    expect(imageOption.disabled).toBe(false);
    expect(videoOption.disabled).toBe(true);
    expect(videoOption.textContent).toContain("无关键帧阶段绑定");

    fireEvent.change(screen.getByLabelText("实验阶段"), { target: { value: "video" } });
    expect(
      (screen.getByRole("option", { name: /Agnes Video V2.0/ }) as HTMLOptionElement).disabled,
    ).toBe(false);
    expect(
      (screen.getByRole("option", { name: /Agnes Image Flash/ }) as HTMLOptionElement).disabled,
    ).toBe(true);
  });

  it("blocks a branch the eligibility engine would refuse, with the reason in Chinese", () => {
    renderPanel({
      modelCandidates: {
        keyframe: [
          candidate({
            eligible: false,
            issues: [{ code: "MODEL_QUALITY_GATE_MISSING", detail: "" }],
          }),
        ],
      },
    });
    fireEvent.change(screen.getByLabelText("实验名称"), { target: { value: "画质未验收" } });
    fireEvent.change(screen.getByLabelText("实验模型"), {
      target: { value: "agnes/agnes-image-2.1-flash" },
    });
    const eligibility = screen.getByTestId("experiment-model-eligibility");
    expect(eligibility.textContent).toContain("尚未通过画质验收");
    expect(eligibility.textContent).not.toContain("MODEL_QUALITY_GATE_MISSING");
    // Measured on the live stack: a keyframe branch on a binding without the
    // quality gate fails with MODEL_INELIGIBLE and produces no candidate.
    expect(screen.getByRole("button", { name: "创建实验分支" })).toBeDisabled();
  });

  it("shows the stage of an existing branch and reports a refused start in product terms", async () => {
    const onStartExperiment = vi.fn(async () => {
      throw new ApiError(
        "selected experiment model has no enabled workspace binding",
        422,
        "VALIDATION_ERROR",
        { code: "MODEL_BINDING_MISSING", purpose: "video" },
      );
    });
    renderPanel({ experiments: [experiment()], onStartExperiment });

    expect(screen.getByTestId("experiment-stage-exp-1").textContent).toContain("关键帧阶段");
    fireEvent.click(screen.getByRole("button", { name: "运行实验" }));

    await waitFor(() => expect(screen.getByTestId("experiment-message")).toBeTruthy());
    expect(onStartExperiment).toHaveBeenCalledWith("exp-1", "keyframe");
    const message = screen.getByTestId("experiment-message");
    expect(message.textContent).toContain("没有可用于关键帧阶段的绑定");
    // The raw backend detail stays behind the collapsed diagnostics block.
    expect(message.textContent).not.toContain("no enabled workspace binding");
    expect(screen.getByTestId("experiment-error-diagnostics").textContent).toContain(
      "no enabled workspace binding",
    );
  });
});
