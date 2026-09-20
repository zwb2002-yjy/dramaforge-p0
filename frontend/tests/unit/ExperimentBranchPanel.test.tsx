import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ExperimentBranchPanel } from "../../src/features/production/ExperimentBranchPanel";
import { ApiError } from "../../src/lib/api";
import type { ExperimentRead, ModelRead } from "../../src/lib/api";
import type { ModelCandidateRead } from "../../src/features/production/modelCandidatesApi";

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
    certified: true,
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
    <ExperimentBranchPanel
      projectId="project-1"
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

describe("ExperimentBranchPanel", () => {
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

  it("keeps an uncertified but bound model selectable and states the missing evidence", () => {
    renderPanel({
      modelCandidates: {
        keyframe: [
          candidate({
            eligible: true,
            certified: false,
            evidence: { quality_gated: false },
          }),
        ],
      },
    });
    fireEvent.change(screen.getByLabelText("实验名称"), { target: { value: "画质未验收" } });
    fireEvent.change(screen.getByLabelText("实验模型"), {
      target: { value: "agnes/agnes-image-2.1-flash" },
    });
    // Decision 2026-09-19: quality certification is evidence, not admission, so
    // the model stays selectable and the form says what is still missing.
    const eligibility = screen.getByTestId("experiment-model-eligibility");
    expect(eligibility.textContent).toContain("尚未通过质量验收");
    expect(eligibility.textContent).not.toContain("MODEL_QUALITY_GATE_MISSING");
    expect(screen.getByRole("button", { name: "创建实验分支" })).toBeEnabled();
  });

  it("still refuses a binding the engine rejects for a hard reason", () => {
    renderPanel({
      modelCandidates: {
        keyframe: [
          candidate({
            eligible: false,
            issues: [{ code: "MODEL_BINDING_DISABLED", detail: "" }],
          }),
        ],
      },
    });
    fireEvent.change(screen.getByLabelText("实验名称"), { target: { value: "绑定已停用" } });
    fireEvent.change(screen.getByLabelText("实验模型"), {
      target: { value: "agnes/agnes-image-2.1-flash" },
    });
    expect(screen.getByTestId("experiment-model-eligibility").textContent).toContain("绑定已停用");
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

  it("labels stage availability per option and keeps the provider codes out of the surface", () => {
    const VIDEO_MODELS: ModelRead[] = [
      {
        id: "agnes/video-v2",
        provider_id: "agnes",
        display_name: "Agnes Video",
        enabled: true,
        configured: true,
        available: true,
        capabilities: ["video.image_to_video"],
      },
      {
        id: "agnes/video-v3",
        provider_id: "agnes",
        display_name: "Agnes Video Pro",
        enabled: true,
        configured: true,
        available: true,
        capabilities: ["video.image_to_video"],
      },
    ];
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const onCreateExperiment = vi.fn(async () => {});
    render(
      <QueryClientProvider client={queryClient}>
        <ExperimentBranchPanel
          projectId="project-1"
          models={VIDEO_MODELS}
          modelCandidates={{
            video: [candidate({ purpose: "video", model_id: "video-v2", certified: false })],
          }}
          onCreateExperiment={onCreateExperiment}
        />
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByLabelText("实验阶段"), { target: { value: "video" } });
    // A bound but uncertified model is selectable: certification is evidence.
    const boundOption = screen.getByRole("option", {
      name: "Agnes Video · 未认证",
    }) as HTMLOptionElement;
    expect(boundOption.disabled).toBe(false);
    expect(boundOption.textContent).toContain("未认证");
    // A model without a binding for this stage is a hard stop.
    const unboundOption = screen.getByRole("option", {
      name: "Agnes Video Pro · 无视频阶段绑定",
    }) as HTMLOptionElement;
    expect(unboundOption.disabled).toBe(true);
    expect(unboundOption.textContent).toContain("无视频阶段绑定");

    fireEvent.change(screen.getByLabelText("实验模型"), { target: { value: "agnes/video-v2" } });
    const eligibility = screen.getByTestId("experiment-model-eligibility");
    expect(eligibility.textContent).toContain("尚未通过质量验收");
    expect(eligibility.textContent).not.toContain("MODEL_QUALITY_GATE_MISSING");
    fireEvent.change(screen.getByLabelText("实验名称"), { target: { value: "换模型验证" } });
    expect(screen.getByRole("button", { name: "创建实验分支" })).toBeEnabled();
  });

  it("keeps the form usable while stage eligibility is still unknown", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const onCreateExperiment = vi.fn(async () => {});
    render(
      <QueryClientProvider client={queryClient}>
        <ExperimentBranchPanel
          projectId="project-1"
          models={[MODELS[1]]}
          onCreateExperiment={onCreateExperiment}
        />
      </QueryClientProvider>,
    );

    // No candidate group at all: the read is pending, so nothing is asserted
    // about eligibility and the Owner is not locked out.
    expect(screen.queryByTestId("experiment-model-eligibility")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("实验名称"), { target: { value: "换模型验证" } });
    fireEvent.change(screen.getByLabelText("实验模型"), {
      target: { value: "agnes/agnes-video-v2.0" },
    });
    expect(screen.getByRole("button", { name: "创建实验分支" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "创建实验分支" }));
    await waitFor(() => expect(onCreateExperiment).toHaveBeenCalledTimes(1));
    expect(onCreateExperiment).toHaveBeenCalledWith({
      name: "换模型验证",
      selected_model: "agnes/agnes-video-v2.0",
      targetNodeKey: "keyframe",
    });
  });
});

it("creates separate candidate drafts without submitting paid generation", async () => {
  const create = vi
    .fn<
      (input: {
        name: string;
        selected_model: string;
        targetNodeKey: "keyframe" | "video";
      }) => Promise<void>
    >()
    .mockResolvedValue(undefined);
  const start = vi.fn(async () => {});
  renderPanel({
    modelCandidates: { keyframe: [candidate({})] },
    onCreateExperiment: create,
    onStartExperiment: start,
  });
  fireEvent.change(screen.getByLabelText("实验名称"), { target: { value: "多图比较" } });
  fireEvent.change(screen.getByLabelText("实验模型"), { target: { value: MODELS[0].id } });
  fireEvent.change(screen.getByLabelText("候选任务数量"), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: "创建实验分支" }));
  await waitFor(() => expect(create).toHaveBeenCalledTimes(3));
  expect(create.mock.calls.map((args) => args[0].name)).toEqual([
    "多图比较 · 1/3",
    "多图比较 · 2/3",
    "多图比较 · 3/3",
  ]);
  expect(start).not.toHaveBeenCalled();
  expect(await screen.findByTestId("experiment-message")).toHaveTextContent("本次创建不调用模型");
});
it("requires a visible selection when an experiment has multiple artifacts", async () => {
  const decide = vi.fn(async () => {});
  render(
    <ExperimentBranchPanel
      projectId="project-1"
      experiments={[experiment({ candidate_artifact_ids: ["first", "best"] })]}
      onDecideExperiment={decide}
    />,
  );
  expect(screen.getByRole("button", { name: "采纳候选" })).toBeDisabled();
  expect(screen.getAllByRole("img")).toHaveLength(2);
  fireEvent.click(screen.getByRole("radio", { name: "候选 2" }));
  fireEvent.click(screen.getByRole("button", { name: "采纳候选" }));
  await waitFor(() =>
    expect(decide).toHaveBeenCalledWith(
      "exp-1",
      expect.objectContaining({ candidate_artifact_id: "best" }),
    ),
  );
});

it("stops a partially created group and preserves the same identities for recovery", async () => {
  const create = vi
    .fn<
      (input: {
        name: string;
        selected_model: string;
        targetNodeKey: "keyframe" | "video";
      }) => Promise<void>
    >()
    .mockResolvedValue(undefined)
    .mockResolvedValueOnce(undefined)
    .mockRejectedValueOnce(new Error("network"));
  const start = vi.fn(async () => {});
  renderPanel({
    modelCandidates: { keyframe: [candidate({})] },
    onCreateExperiment: create,
    onStartExperiment: start,
  });
  fireEvent.change(screen.getByLabelText("实验名称"), { target: { value: "稳定候选" } });
  fireEvent.change(screen.getByLabelText("实验模型"), { target: { value: MODELS[0].id } });
  fireEvent.change(screen.getByLabelText("候选任务数量"), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: "创建实验分支" }));
  await waitFor(() => expect(screen.getByTestId("experiment-message")).toHaveClass("status-bad"));
  expect(create).toHaveBeenCalledTimes(2);
  expect(screen.getByLabelText("实验名称")).toHaveValue("稳定候选");
  fireEvent.click(screen.getByRole("button", { name: "创建实验分支" }));
  await waitFor(() => expect(create).toHaveBeenCalledTimes(5));
  expect(create.mock.calls[0][0]).toEqual(create.mock.calls[2][0]);
  expect(create.mock.calls[1][0]).toEqual(create.mock.calls[3][0]);
  expect(start).not.toHaveBeenCalled();
});
