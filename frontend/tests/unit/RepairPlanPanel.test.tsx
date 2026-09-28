import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RepairPlanPanel } from "../../src/features/review/RepairPlanPanel";
import {
  repairIsWaitingForHuman,
  repairStageLabel,
  repairStepActionLabel,
  type RepairPlanRead,
  type RepairRequestRead,
  type RepairStepExecuteBody,
  type RepairStepPlanBody,
  type RepairStepPlanRead,
  type RepairStepRead,
} from "../../src/features/review/repairApi";

const PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SHOT_ID = "11111111-1111-4111-8111-111111111111";
const REPAIR_ID = "44444444-4444-4444-8444-444444444444";
const ARTIFACT_ID = "77777777-7777-4777-8777-777777777777";
const ASSET_VERSION_ID = "88888888-8888-4888-8888-888888888888";
const BASE = `/api/v1/projects/${PROJECT_ID}/shots/${SHOT_ID}`;
const PLAN: RepairPlanRead = {
  shot_id: SHOT_ID,
  repair_options: ["rerun_video", "regenerate_keyframe_then_video"],
  suggested_option: "regenerate_keyframe_then_video",
  affected_nodes: ["keyframe", "video"],
  retained_assets: [],
  expected_rerun_scope: "keyframe_then_video",
  annotation_count: 2,
  annotation_ids: ["33333333-3333-4333-8333-333333333333"],
  plan_hash: "a".repeat(64),
  plan_schema_version: 1,
  steps: ["keyframe_regenerate", "keyframe_review", "video_rerun", "video_review"],
  cost_estimate_note: "修复执行会真实调用已绑定的媒体模型；此处不做确定性报价。",
};
const FIRST_STEP: RepairStepRead = {
  id: "55555555-5555-4555-8555-555555555555",
  ordinal: 1,
  stage: "keyframe_regenerate",
  plan_fingerprint: "b".repeat(64),
  command_key: "repair:step:1",
  node_run_id: "66666666-6666-4666-8666-666666666666",
  node_run_status: "completed",
  node_run_error_code: null,
  result_artifact_id: ARTIFACT_ID,
  confirmed_at: "2026-09-15T00:00:00Z",
  adopted_artifact_id: null,
  review_decision_id: null,
  next_action: "review_candidate",
};
const NEW_REPAIR: RepairRequestRead = {
  id: REPAIR_ID,
  shot_id: SHOT_ID,
  option: "regenerate_keyframe_then_video",
  plan_hash: "a".repeat(64),
  plan_schema_version: 1,
  annotation_ids: PLAN.annotation_ids,
  source_formal_artifact_id: null,
  closed_reason: null,
  created_at: "2026-09-15T00:00:00Z",
  next_action: "execute_step",
  next_step_ordinal: 1,
  steps: [],
};
const REVIEW_REPAIR: RepairRequestRead = {
  ...NEW_REPAIR,
  next_action: "human_decision",
  next_step_ordinal: null,
  steps: [FIRST_STEP],
};
const VIDEO_REPAIR: RepairRequestRead = {
  ...NEW_REPAIR,
  next_step_ordinal: 3,
  steps: [
    {
      ...FIRST_STEP,
      adopted_artifact_id: ARTIFACT_ID,
      review_decision_id: "review-1",
      next_action: "adopted",
    },
  ],
};
const WAIT_REPAIR: RepairRequestRead = {
  ...NEW_REPAIR,
  next_action: "wait",
  next_step_ordinal: null,
  steps: [
    { ...FIRST_STEP, node_run_status: "running", result_artifact_id: null, next_action: "wait" },
  ],
};

function stepPlan(request = NEW_REPAIR): RepairStepPlanRead {
  const video = request.next_step_ordinal === 3 || request.option === "rerun_video";
  return {
    repair_id: request.id,
    step_ordinal: request.next_step_ordinal ?? 1,
    stage: video ? "video_rerun" : "keyframe_regenerate",
    plan: {
      plan_fingerprint: "b".repeat(64),
      project_id: PROJECT_ID,
      shot_id: SHOT_ID,
      stage: video ? "video" : "image_keyframe",
      prompt: video ? "沿用已通过审核的关键帧，镜头缓慢推进" : "角色穿过庭院，保持人物身份一致",
      mode_id: "explicit_binding",
      resolved_model: {
        resolved_model_id: "provider/exact-model",
        status: "RESOLVED",
        source: "project_profile",
        provider_model_binding_id: "binding-1",
        capability: video ? "video.image_to_video" : "image.generate",
      },
      capability: video ? "video.image_to_video" : "image.generate",
      planned_references: [
        {
          artifact_id: ARTIFACT_ID,
          asset_version_id: video ? null : ASSET_VERSION_ID,
          purpose: video ? "first_frame" : "identity",
          delivery: "exact",
          resolution_mode: "current_formal",
          mime_type: "image/png",
        },
      ],
    },
  };
}

function approximationPlan(accepted = false): RepairStepPlanRead {
  const preview = stepPlan();
  return {
    ...preview,
    plan: {
      ...preview.plan,
      plan_fingerprint: (accepted ? "c" : "b").repeat(64),
      planned_references: ["style", "scene_layout"].map((purpose) => ({
        ...preview.plan.planned_references![0]!,
        purpose,
        delivery: "approximate" as const,
        reason: "delivered as a generic visual reference",
      })),
      capability_gaps: accepted
        ? []
        : [
            {
              capability: "image.generate",
              severity: "warning",
              controls: ["style", "scene_layout"],
              reason: "approximate references require explicit acceptance",
            },
          ],
      accepted_approximations: accepted ? ["style", "scene_layout"] : [],
    },
  };
}

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
}

type Call = { url: string; method: string; body: Record<string, unknown> | undefined };
function mockApi(initial: RepairRequestRead[] = []) {
  const server = {
    repairs: [...initial],
    calls: [] as Call[],
    preview: stepPlan(initial[0] ?? NEW_REPAIR),
    onStep: null as ((body: RepairStepExecuteBody) => Promise<Response>) | null,
    onClose: null as (() => Promise<Response>) | null,
    onPreview: null as ((body: RepairStepPlanBody | undefined) => Promise<Response>) | null,
    onList: null as (() => Promise<Response>) | null,
    onCreate: null as (() => Promise<Response>) | null,
  };
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body
      ? (JSON.parse(String(init.body)) as Record<string, unknown>)
      : undefined;
    server.calls.push({ url, method, body });
    if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
    if (url.endsWith("/models"))
      return json([{ id: "provider/exact-model", display_name: "本项目已绑定模型" }]);
    if (url === `${BASE}/repair-plan`) return json(PLAN);
    if (url === `${BASE}/repairs` && method === "POST") {
      if (server.onCreate) return server.onCreate();
      const created = { ...NEW_REPAIR, option: body?.repair_option as RepairRequestRead["option"] };
      server.repairs = [created, ...server.repairs];
      server.preview = stepPlan(created);
      return json(created, 201);
    }
    if (url === `${BASE}/repairs`) return server.onList ? server.onList() : json(server.repairs);
    if (url.endsWith("/step-plan"))
      return server.onPreview
        ? server.onPreview(body as RepairStepPlanBody | undefined)
        : json(server.preview);
    if (url.endsWith("/steps")) {
      if (server.onStep) return server.onStep(body as RepairStepExecuteBody);
      const current = server.repairs[0]!;
      server.repairs = [
        {
          ...current,
          next_action: "wait",
          next_step_ordinal: null,
          steps: [
            ...current.steps,
            {
              ...FIRST_STEP,
              id: `step-${String(body?.expected_step_ordinal)}`,
              ordinal: Number(body?.expected_step_ordinal),
              stage: server.preview.stage,
              plan_fingerprint: String(body?.expected_plan_fingerprint),
              command_key: String(body?.idempotency_key),
              node_run_status: "queued",
              result_artifact_id: null,
              next_action: "wait",
            },
          ],
        },
      ];
      return json({
        node_run_id: FIRST_STEP.node_run_id,
        status: "queued",
        repair_option: current.option,
        repair_id: current.id,
        step_ordinal: body?.expected_step_ordinal,
        next_action: "wait",
      });
    }
    if (url.endsWith("/close")) {
      if (server.onClose) return server.onClose();
      const closed = {
        ...server.repairs[0]!,
        closed_reason: String(body?.reason),
        next_action: "closed",
        next_step_ordinal: null,
      };
      server.repairs = [closed];
      return json(closed);
    }
    if (url === `${BASE}/repairs/${REPAIR_ID}`) return json(server.repairs[0]);
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  return server;
}

const clients: QueryClient[] = [];
function renderPanel(shotId = SHOT_ID) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  clients.push(client);
  const onClose = vi.fn();
  const result = render(
    <QueryClientProvider client={client}>
      <RepairPlanPanel projectId={PROJECT_ID} shotId={shotId} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { ...result, onClose, client };
}
function writes(server: ReturnType<typeof mockApi>, suffix: string) {
  return server.calls.filter((call) => call.method === "POST" && call.url.endsWith(suffix));
}
async function previewAndAcknowledge() {
  const preview = await screen.findByTestId("repair-preview-step");
  await waitFor(() => expect(preview).toBeEnabled());
  fireEvent.click(preview);
  await screen.findByTestId("repair-step-preview");
  fireEvent.click(screen.getByRole("checkbox", { name: /我已核对本步实际模型/ }));
  await waitFor(() => expect(screen.getByTestId("repair-execute-step")).toBeEnabled());
}

function inspectReferenceIdentity(expectedVersion: string | null) {
  const identity = screen.getByTestId("repair-reference-identity-1");
  expect(identity).not.toHaveAttribute("open");
  fireEvent.click(within(identity).getByText("查看引用 1 身份（只读）"));
  expect(identity).toHaveAttribute("open");
  expect(within(identity).getByText(`产物：${ARTIFACT_ID}`)).toBeVisible();
  expect(within(identity).getByText(`素材版本：${expectedVersion ?? "无"}`)).toBeVisible();
}

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("RepairPlanPanel preview and confirmation gates", () => {
  it("shows the selected option's steps and scope, not the suggested option", async () => {
    const server = mockApi();
    renderPanel();
    expect(await screen.findByTestId("repair-plan-summary")).toHaveTextContent("2 条待处理标注");
    expect(screen.getByTestId("repair-plan-cost")).toHaveTextContent("不做确定性报价");
    expect(within(screen.getByTestId("repair-plan-steps")).getAllByRole("listitem")).toHaveLength(
      4,
    );
    fireEvent.click(screen.getByRole("radio", { name: "保留已确认关键帧，只重跑视频" }));
    expect(within(screen.getByTestId("repair-plan-steps")).getAllByRole("listitem")).toHaveLength(
      2,
    );
    expect(screen.getByTestId("repair-plan-steps")).not.toHaveTextContent("审查并确认关键帧");
    expect(screen.getByTestId("repair-plan-summary")).toHaveTextContent("本方案范围：仅视频");
    expect(writes(server, "/steps")).toHaveLength(0);
  });

  it("confirms only the displayed intent and never dispatches media or step-plan automatically", async () => {
    const server = mockApi();
    renderPanel();
    fireEvent.click(await screen.findByTestId("repair-confirm"));
    expect(await screen.findByTestId("repair-plan-feedback")).toHaveTextContent("已确认修复计划");
    expect(writes(server, "/repairs")[0]?.body).toMatchObject({
      repair_option: "regenerate_keyframe_then_video",
      plan_hash: PLAN.plan_hash,
      idempotency_key: expect.stringMatching(/^repair:/),
    });
    expect(writes(server, "/steps")).toHaveLength(0);
    expect(writes(server, "/step-plan")).toHaveLength(0);
    expect(await screen.findByTestId("repair-preview-step")).toBeInTheDocument();
  });

  it.each([NEW_REPAIR, { ...NEW_REPAIR, option: "rerun_video" as const }, VIDEO_REPAIR])(
    "previews actual inputs then explicitly submits the backend ordinal ($option, $next_step_ordinal)",
    async (request) => {
      const server = mockApi([request]);
      renderPanel();
      expect(await screen.findByTestId("repair-preview-step")).toBeInTheDocument();
      expect(screen.queryByTestId("repair-execute-step")).not.toBeInTheDocument();
      fireEvent.click(screen.getByTestId("repair-preview-step"));
      expect(await screen.findByTestId("repair-step-preview")).toHaveTextContent(
        `第 ${request.next_step_ordinal} 步`,
      );
      expect(writes(server, "/step-plan")[0]?.body).toBeUndefined();
      await waitFor(() =>
        expect(screen.getByTestId("repair-step-model")).toHaveTextContent("本项目已绑定模型"),
      );
      const referenceLabel = screen.getByTestId("repair-reference-label-1");
      expect(referenceLabel).toHaveTextContent(
        server.preview.plan.stage === "image_keyframe" ? "角色身份 1" : "首帧 1",
      );
      expect(referenceLabel).toHaveTextContent("完全支持");
      expect(referenceLabel).not.toHaveTextContent(ARTIFACT_ID);
      expect(referenceLabel).not.toHaveTextContent(ASSET_VERSION_ID);
      inspectReferenceIdentity(
        server.preview.plan.planned_references?.[0]?.asset_version_id ?? null,
      );
      expect(screen.getByTestId("repair-step-prompt")).toHaveValue(server.preview.plan.prompt);
      expect(screen.getByTestId("repair-step-scope")).toHaveTextContent("不是标注区域的局部修补");
      expect(screen.getByTestId("repair-execute-step")).toBeDisabled();
      expect(writes(server, "/steps")).toHaveLength(0);
      fireEvent.click(screen.getByRole("checkbox"));
      fireEvent.click(screen.getByTestId("repair-execute-step"));
      await waitFor(() => expect(writes(server, "/steps")).toHaveLength(1));
      expect(writes(server, "/steps")[0]?.body).toEqual({
        expected_plan_fingerprint: "b".repeat(64),
        expected_step_ordinal: request.next_step_ordinal,
        accept_approximations: false,
        idempotency_key: expect.stringMatching(/^repair-step:/),
      });
      expect(await screen.findByTestId("repair-wait-hint")).toBeInTheDocument();
      expect(screen.queryByTestId("repair-review-hint")).not.toBeInTheDocument();
    },
  );

  it("keeps exact artifact, repair and step lineage in candidate review links", async () => {
    mockApi([REVIEW_REPAIR]);
    renderPanel();
    const active = await screen.findByTestId("repair-active");
    expect(active).toHaveAttribute("data-next-action", "human_decision");
    expect(screen.getByTestId("repair-step-1")).toHaveTextContent("运行状态 已完成");
    expect(screen.getByTestId("repair-step-1")).not.toHaveTextContent("completed");
    const target = new URL(
      screen.getByRole("link", { name: "审查本步候选" }).getAttribute("href")!,
      "http://localhost",
    );
    expect(Object.fromEntries(target.searchParams)).toEqual({
      shotId: SHOT_ID,
      artifactId: ARTIFACT_ID,
      stage: "formal_keyframe",
      reviewKind: "identity",
      repairRequestId: REPAIR_ID,
      repairStepId: FIRST_STEP.id,
    });
    expect(screen.getByTestId("repair-review-hint")).toHaveTextContent("修复尚未完成");
    expect(screen.queryByTestId("repair-preview-step")).not.toBeInTheDocument();
  });

  it("does not offer ordinal 3 before the exact keyframe is reviewed and adopted, even with inconsistent next_action", async () => {
    const server = mockApi([
      { ...REVIEW_REPAIR, next_action: "execute_step", next_step_ordinal: 3 },
    ]);
    renderPanel();
    await screen.findByTestId("repair-active");
    expect(screen.queryByTestId("repair-preview-step")).not.toBeInTheDocument();
    expect(writes(server, "/step-plan")).toHaveLength(0);
  });

  it("refreshes a stale step preview without ever automatically resubmitting the new fingerprint", async () => {
    const server = mockApi([NEW_REPAIR]);
    server.onStep = () =>
      json({ code: "CONFLICT", details: { code: "REPAIR_STEP_PLAN_MISMATCH" } }, 409);
    renderPanel();
    await previewAndAcknowledge();
    fireEvent.click(screen.getByTestId("repair-execute-step"));
    expect(await screen.findByTestId("repair-feedback")).toHaveTextContent("计划已过期");
    expect(screen.queryByTestId("repair-execute-step")).not.toBeInTheDocument();
    server.preview = {
      ...server.preview,
      plan: { ...server.preview.plan, plan_fingerprint: "c".repeat(64), prompt: "更新后的提示词" },
    };
    await waitFor(() => expect(screen.getByTestId("repair-preview-step")).toBeEnabled());
    fireEvent.click(screen.getByTestId("repair-preview-step"));
    await waitFor(() =>
      expect(screen.getByTestId("repair-step-prompt")).toHaveValue("更新后的提示词"),
    );
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByTestId("repair-execute-step")).toBeDisabled();
    expect(writes(server, "/steps")).toHaveLength(1);
  });

  it("offers configuration exits when the fail-closed compiler refuses a preview", async () => {
    const server = mockApi([NEW_REPAIR]);
    server.onPreview = () =>
      json({ code: "VALIDATION_ERROR", detail: "unresolved model or reference" }, 422);
    renderPanel();
    fireEvent.click(await screen.findByTestId("repair-preview-step"));
    expect(await screen.findByTestId("repair-feedback")).toHaveTextContent("无法预览本步");
    expect(screen.getByRole("link", { name: "前往分镜工作台修改镜头引用" })).toHaveAttribute(
      "href",
      `/projects/${PROJECT_ID}/scenes`,
    );
    expect(screen.getByRole("link", { name: "修改本项目模型配置" })).toHaveAttribute(
      "href",
      expect.stringContaining(`/settings/projects/${PROJECT_ID}?returnTo=`),
    );
    expect(screen.queryByTestId("repair-execute-step")).not.toBeInTheDocument();
    expect(writes(server, "/steps")).toHaveLength(0);
  });

  it.each(["fingerprint", "scope", "model", "prompt"])(
    "does not execute a plan with invalid %s",
    async (invalid) => {
      const server = mockApi([NEW_REPAIR]);
      server.preview = {
        ...server.preview,
        plan: {
          ...server.preview.plan,
          ...(invalid === "fingerprint" ? { plan_fingerprint: null } : {}),
          ...(invalid === "scope" ? { shot_id: "another-shot" } : {}),
          ...(invalid === "model"
            ? {
                resolved_model: {
                  ...server.preview.plan.resolved_model,
                  status: "UNAVAILABLE" as const,
                },
              }
            : {}),
          ...(invalid === "prompt" ? { prompt: "" } : {}),
        },
      };
      renderPanel();
      fireEvent.click(await screen.findByTestId("repair-preview-step"));
      expect(await screen.findByRole("alert")).toHaveTextContent("缺少凭据");
      expect(screen.queryByTestId("repair-execute-step")).not.toBeInTheDocument();
      expect(writes(server, "/steps")).toHaveLength(0);
    },
  );
});

describe("RepairPlanPanel explicit approximation consent", () => {
  it("shows warnings and approximate purposes but blocks execution until a true preview returns with a new fingerprint", async () => {
    const server = mockApi([NEW_REPAIR]);
    let finishAcceptedPreview: (response: Response) => void = () => {
      throw new Error("accepted preview not requested");
    };
    server.onPreview = (body) =>
      body?.accept_approximations
        ? new Promise<Response>((resolve) => {
            finishAcceptedPreview = resolve;
          })
        : json(approximationPlan());
    renderPanel();
    fireEvent.click(await screen.findByTestId("repair-preview-step"));
    expect(await screen.findByTestId("repair-capability-gaps")).toHaveTextContent("需要注意");
    expect(screen.getByTestId("repair-capability-gaps")).toHaveTextContent("风格、场景布局");
    expect(screen.getByTestId("repair-reference-label-1")).toHaveTextContent("风格 1 · 近似支持");
    expect(screen.getByTestId("repair-reference-label-2")).toHaveTextContent(
      "场景布局 2 · 近似支持",
    );
    expect(screen.getByTestId("repair-reference-label-1")).not.toHaveTextContent("完全支持");
    inspectReferenceIdentity(ASSET_VERSION_ID);
    expect(screen.queryByTestId("repair-execute-step")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("checkbox", { name: /我已核对本步实际模型/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "接受所列近似处理" })).not.toBeChecked();
    expect(writes(server, "/step-plan")[0]?.body).toBeUndefined();
    fireEvent.click(screen.getByRole("checkbox", { name: "接受所列近似处理" }));
    await screen.findByTestId("repair-preview-pending");
    expect(writes(server, "/step-plan")[1]?.body).toEqual({ accept_approximations: true });
    expect(screen.queryByTestId("repair-execute-step")).not.toBeInTheDocument();
    expect(writes(server, "/steps")).toHaveLength(0);
    const response = await json(approximationPlan(true));
    await act(async () => {
      finishAcceptedPreview(response);
    });
    expect(await screen.findByTestId("repair-accepted-approximations")).toHaveTextContent(
      "风格 · 近似处理",
    );
    expect(screen.getByTestId("repair-accepted-approximations")).toHaveTextContent(
      "场景布局 · 近似处理",
    );
    expect(screen.getByTestId("repair-reference-label-1")).toHaveTextContent("近似支持");
    expect(screen.getByTestId("repair-execute-step")).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /我已核对本步实际模型/ }));
    fireEvent.click(screen.getByTestId("repair-execute-step"));
    await waitFor(() => expect(writes(server, "/steps")).toHaveLength(1));
    expect(writes(server, "/steps")[0]?.body).toEqual({
      expected_plan_fingerprint: "c".repeat(64),
      expected_step_ordinal: 1,
      accept_approximations: true,
      idempotency_key: expect.stringMatching(/^repair-step:/),
    });
  });

  it("rebuilds an unaccepted false preview on uncheck and does not carry execution confirmation forward", async () => {
    const server = mockApi([NEW_REPAIR]);
    server.onPreview = (body) => json(approximationPlan(Boolean(body?.accept_approximations)));
    renderPanel();
    fireEvent.click(await screen.findByTestId("repair-preview-step"));
    fireEvent.click(await screen.findByRole("checkbox", { name: "接受所列近似处理" }));
    await screen.findByTestId("repair-accepted-approximations");
    fireEvent.click(screen.getByRole("checkbox", { name: /我已核对本步实际模型/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "接受所列近似处理" }));
    await screen.findByTestId("repair-capability-gaps");
    expect(writes(server, "/step-plan")[2]?.body).toEqual({ accept_approximations: false });
    expect(screen.queryByTestId("repair-execute-step")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "接受所列近似处理" }));
    await screen.findByTestId("repair-accepted-approximations");
    expect(screen.getByRole("checkbox", { name: /我已核对本步实际模型/ })).not.toBeChecked();
    expect(screen.getByTestId("repair-execute-step")).toBeDisabled();
    expect(writes(server, "/steps")).toHaveLength(0);
  });

  it("does not treat a checked box or lost preview response as a successfully accepted frozen plan", async () => {
    const server = mockApi([NEW_REPAIR]);
    server.onPreview = (body) =>
      body?.accept_approximations
        ? Promise.reject(new TypeError("preview response lost"))
        : json(approximationPlan());
    renderPanel();
    fireEvent.click(await screen.findByTestId("repair-preview-step"));
    fireEvent.click(await screen.findByRole("checkbox", { name: "接受所列近似处理" }));
    expect(await screen.findByTestId("repair-feedback")).toHaveTextContent("无法预览本步");
    expect(screen.queryByTestId("repair-execute-step")).not.toBeInTheDocument();
    expect(writes(server, "/step-plan")).toHaveLength(2);
    expect(writes(server, "/steps")).toHaveLength(0);
  });

  it("fails closed when the accepted preview does not name all of its actual approximate references", async () => {
    const server = mockApi([NEW_REPAIR]);
    server.onPreview = (body) => {
      const preview = approximationPlan(Boolean(body?.accept_approximations));
      return json({
        ...preview,
        plan: {
          ...preview.plan,
          accepted_approximations: body?.accept_approximations ? ["style"] : [],
        },
      });
    };
    renderPanel();
    fireEvent.click(await screen.findByTestId("repair-preview-step"));
    fireEvent.click(await screen.findByRole("checkbox", { name: "接受所列近似处理" }));
    await screen.findByTestId("repair-accepted-approximations");
    expect(screen.getByTestId("repair-approximation-required")).toBeInTheDocument();
    expect(screen.queryByTestId("repair-execute-step")).not.toBeInTheDocument();
    expect(writes(server, "/steps")).toHaveLength(0);
  });

  it("keeps the accepted flag, fingerprint, ordinal and key identical after a lost execution response and reopening", async () => {
    const server = mockApi([NEW_REPAIR]);
    server.onPreview = (body) => json(approximationPlan(Boolean(body?.accept_approximations)));
    server.onStep = () => Promise.reject(new TypeError("execution response lost"));
    const mounted = renderPanel();
    fireEvent.click(await screen.findByTestId("repair-preview-step"));
    fireEvent.click(await screen.findByRole("checkbox", { name: "接受所列近似处理" }));
    await screen.findByTestId("repair-accepted-approximations");
    fireEvent.click(screen.getByRole("checkbox", { name: /我已核对本步实际模型/ }));
    fireEvent.click(screen.getByTestId("repair-execute-step"));
    await waitFor(() => expect(screen.getByTestId("repair-retry-submission")).toBeEnabled());
    const original = writes(server, "/steps")[0]?.body;
    expect(original).toMatchObject({
      accept_approximations: true,
      expected_plan_fingerprint: "c".repeat(64),
    });
    mounted.unmount();
    renderPanel();
    await waitFor(() => expect(screen.getByTestId("repair-retry-submission")).toBeEnabled());
    expect(screen.queryByTestId("repair-preview-step")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "接受所列近似处理" })).not.toBeInTheDocument();
    server.onStep = null;
    fireEvent.click(screen.getByTestId("repair-retry-submission"));
    await waitFor(() => expect(writes(server, "/steps")).toHaveLength(2));
    expect(writes(server, "/steps")[1]?.body).toEqual(original);
    expect(writes(server, "/step-plan")).toHaveLength(2);
  });
});

describe("RepairPlanPanel durable recovery and closure", () => {
  it("recovers an already-active creation conflict by showing that repair, not trapping the user", async () => {
    const server = mockApi();
    server.onCreate = () => {
      server.repairs = [REVIEW_REPAIR];
      return json({ code: "CONFLICT", details: { code: "REPAIR_ALREADY_ACTIVE" } }, 409);
    };
    renderPanel();
    fireEvent.click(await screen.findByTestId("repair-confirm"));
    expect(await screen.findByTestId("repair-review-hint")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "审查本步候选" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("repair-abandon")).toBeEnabled());
    expect(writes(server, "/repairs")).toHaveLength(1);
    expect(writes(server, "/steps")).toHaveLength(0);
  });

  it("recovers the real failed + PROVIDER_SUBMISSION_UNKNOWN run across reopening without resubmission or closure", async () => {
    const server = mockApi([NEW_REPAIR]);
    const mounted = renderPanel();
    await previewAndAcknowledge();
    fireEvent.click(screen.getByTestId("repair-execute-step"));
    await screen.findByTestId("repair-wait-hint");
    server.repairs = [
      {
        ...WAIT_REPAIR,
        next_action: "reconcile_submission",
        steps: [
          {
            ...WAIT_REPAIR.steps[0]!,
            node_run_status: "failed",
            node_run_error_code: "PROVIDER_SUBMISSION_UNKNOWN",
            next_action: "reconcile_submission",
          },
        ],
      },
    ];
    fireEvent.click(screen.getByTestId("repair-refresh"));
    await screen.findByTestId("repair-unknown-hint");
    mounted.unmount();
    renderPanel();
    expect(await screen.findByTestId("repair-unknown-hint")).toHaveTextContent("可能已计费");
    expect(screen.getByTestId("repair-active")).toHaveAttribute(
      "data-next-action",
      "reconcile_submission",
    );
    expect(screen.getByTestId("repair-active")).toHaveTextContent("提交结果待核实，请核对原任务");
    expect(screen.queryByTestId("repair-preview-step")).not.toBeInTheDocument();
    expect(screen.queryByTestId("repair-retry-submission")).not.toBeInTheDocument();
    expect(screen.getByTestId("repair-abandon")).toBeDisabled();
    expect(writes(server, "/steps")).toHaveLength(1);
  });

  it("preserves the original key when an explicit submission error identifies an unknown provider outcome", async () => {
    const server = mockApi([NEW_REPAIR]);
    server.onStep = () =>
      json({ code: "CONFLICT", details: { code: "PROVIDER_SUBMISSION_UNKNOWN" } }, 409);
    const mounted = renderPanel();
    await previewAndAcknowledge();
    fireEvent.click(screen.getByTestId("repair-execute-step"));
    await screen.findByTestId("repair-unknown-hint");
    mounted.unmount();
    renderPanel();
    await screen.findByTestId("repair-unknown-hint");
    expect(screen.queryByTestId("repair-retry-submission")).not.toBeInTheDocument();
    expect(screen.getByTestId("repair-abandon")).toBeDisabled();
    expect(writes(server, "/steps")).toHaveLength(1);
  });

  it("fails closed before POST when the original submission identity cannot be saved", async () => {
    const server = mockApi([NEW_REPAIR]);
    renderPanel();
    await previewAndAcknowledge();
    vi.spyOn(Object.getPrototypeOf(window.localStorage), "setItem").mockImplementation(() => {
      throw new Error("Storage denied");
    });
    fireEvent.click(screen.getByTestId("repair-execute-step"));
    expect(await screen.findByRole("alert")).toHaveTextContent("无法安全保存或恢复提交凭据");
    expect(writes(server, "/steps")).toHaveLength(0);
    expect(screen.getByTestId("repair-abandon")).toBeDisabled();
  });

  it("requires a fresh ordinal-3 preview after first-keyframe adoption and explicit closure after final-video adoption", async () => {
    const server = mockApi([NEW_REPAIR]);
    renderPanel();
    await previewAndAcknowledge();
    fireEvent.click(screen.getByTestId("repair-execute-step"));
    await screen.findByTestId("repair-wait-hint");
    server.repairs = [REVIEW_REPAIR];
    fireEvent.click(screen.getByTestId("repair-refresh"));
    await screen.findByTestId("repair-review-hint");
    expect(screen.queryByTestId("repair-preview-step")).not.toBeInTheDocument();
    server.repairs = [VIDEO_REPAIR];
    server.preview = stepPlan(VIDEO_REPAIR);
    fireEvent.click(screen.getByTestId("repair-refresh"));
    await screen.findByTestId("repair-preview-step");
    expect(screen.queryByTestId("repair-step-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("repair-execute-step")).not.toBeInTheDocument();
    await previewAndAcknowledge();
    expect(screen.getByTestId("repair-reference-label-1")).toHaveTextContent("首帧 1 · 完全支持");
    inspectReferenceIdentity(null);
    fireEvent.click(screen.getByTestId("repair-execute-step"));
    await screen.findByTestId("repair-wait-hint");
    const lastStep = {
      ...server.repairs[0]!.steps[1]!,
      node_run_status: "completed",
      result_artifact_id: "final-video",
      next_action: "review_candidate",
    };
    server.repairs = [
      {
        ...VIDEO_REPAIR,
        next_action: "human_decision",
        next_step_ordinal: null,
        steps: [VIDEO_REPAIR.steps[0]!, lastStep],
      },
    ];
    fireEvent.click(screen.getByTestId("repair-refresh"));
    await screen.findByTestId("repair-review-hint");
    expect(screen.queryByTestId("repair-complete")).not.toBeInTheDocument();
    const link = within(screen.getByTestId("repair-step-3")).getByRole("link", {
      name: "审查本步候选",
    });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("artifactId=final-video&stage=formal_video&reviewKind=video_drift"),
    );
    server.repairs = [
      {
        ...server.repairs[0]!,
        next_action: "ready_to_close",
        steps: [
          VIDEO_REPAIR.steps[0]!,
          {
            ...lastStep,
            adopted_artifact_id: "final-video",
            review_decision_id: "review-3",
            next_action: "adopted",
          },
        ],
      },
    ];
    fireEvent.click(screen.getByTestId("repair-refresh"));
    await waitFor(() => expect(screen.getByTestId("repair-complete")).toBeEnabled());
    expect(writes(server, "/close")).toHaveLength(0);
    fireEvent.click(screen.getByTestId("repair-complete"));
    await screen.findByTestId("repair-history");
    expect(writes(server, "/steps").map((call) => call.body?.expected_step_ordinal)).toEqual([
      1, 3,
    ]);
    expect(writes(server, "/close")[0]?.body).toEqual({ reason: "completed" });
    expect(screen.queryByTestId("repair-step-2")).not.toBeInTheDocument();
    expect(screen.queryByTestId("repair-step-4")).not.toBeInTheDocument();
  });

  it("retains the identical payload/key after a lost response and reopening; retries only after a read", async () => {
    const server = mockApi([VIDEO_REPAIR]);
    server.onStep = () => Promise.reject(new TypeError("response lost"));
    const mounted = renderPanel();
    await previewAndAcknowledge();
    fireEvent.click(screen.getByTestId("repair-execute-step"));
    expect(await screen.findByTestId("repair-feedback")).toHaveTextContent("未取得明确");
    await screen.findByTestId("repair-retry-submission");
    const original = writes(server, "/steps")[0]?.body;
    mounted.unmount();
    renderPanel();
    await waitFor(() => expect(screen.getByTestId("repair-retry-submission")).toBeEnabled());
    expect(screen.queryByTestId("repair-preview-step")).not.toBeInTheDocument();
    expect(writes(server, "/steps")).toHaveLength(1);
    server.onStep = null;
    fireEvent.click(screen.getByTestId("repair-retry-submission"));
    await waitFor(() => expect(writes(server, "/steps")).toHaveLength(2));
    expect(writes(server, "/steps")[1]?.body).toEqual(original);
    const secondPostIndex = server.calls
      .map((call) => call.url.endsWith("/steps"))
      .lastIndexOf(true);
    expect(
      server.calls
        .slice(0, secondPostIndex)
        .some((call) => call.method === "GET" && call.url === `${BASE}/repairs/${REPAIR_ID}`),
    ).toBe(true);
    expect(writes(server, "/step-plan")).toHaveLength(1);
  });

  it("reconciles an accepted but lost response from persisted steps without sending another POST", async () => {
    const server = mockApi([NEW_REPAIR]);
    server.onStep = () => {
      server.repairs = [WAIT_REPAIR];
      return Promise.reject(new TypeError("response lost after commit"));
    };
    const mounted = renderPanel();
    await previewAndAcknowledge();
    fireEvent.click(screen.getByTestId("repair-execute-step"));
    await screen.findByTestId("repair-wait-hint");
    mounted.unmount();
    renderPanel();
    await screen.findByTestId("repair-wait-hint");
    expect(screen.queryByTestId("repair-retry-submission")).not.toBeInTheDocument();
    expect(writes(server, "/steps")).toHaveLength(1);
  });

  it("reads before recovery and never retries a request that has become unknown_submission", async () => {
    const server = mockApi([NEW_REPAIR]);
    server.onStep = () => Promise.reject(new TypeError("lost"));
    renderPanel();
    await previewAndAcknowledge();
    fireEvent.click(screen.getByTestId("repair-execute-step"));
    await waitFor(() => expect(screen.getByTestId("repair-retry-submission")).toBeEnabled());
    server.repairs = [
      {
        ...WAIT_REPAIR,
        next_action: "close_or_replan",
        steps: [
          {
            ...WAIT_REPAIR.steps[0]!,
            node_run_status: "failed",
            node_run_error_code: "PROVIDER_SUBMISSION_UNKNOWN",
          },
        ],
      },
    ];
    fireEvent.click(screen.getByTestId("repair-retry-submission"));
    expect(await screen.findByTestId("repair-unknown-hint")).toHaveTextContent("可能已计费");
    expect(writes(server, "/steps")).toHaveLength(1);
    expect(screen.getByTestId("repair-abandon")).toBeDisabled();
    expect(screen.getByTestId("repair-active")).toHaveTextContent("提交结果待核实，请核对原任务");
    expect(screen.queryByText(/本次结果无法继续。可显式放弃/)).not.toBeInTheDocument();
  });

  it("polls wait → human decision → reviewed/adopted ordinal 3 without creating review steps or auto-submitting", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const server = mockApi([WAIT_REPAIR]);
    renderPanel();
    expect(await screen.findByTestId("repair-wait-hint")).toHaveTextContent("现在无需人工审查");
    expect(screen.queryByTestId("repair-review-hint")).not.toBeInTheDocument();
    server.repairs = [REVIEW_REPAIR];
    await act(async () => {
      vi.advanceTimersByTime(4000);
    });
    await screen.findByTestId("repair-review-hint");
    expect(screen.queryByTestId("repair-preview-step")).not.toBeInTheDocument();
    server.repairs = [VIDEO_REPAIR];
    await act(async () => {
      vi.advanceTimersByTime(4000);
    });
    await screen.findByTestId("repair-preview-step");
    expect(writes(server, "/steps")).toHaveLength(0);
    expect(writes(server, "/step-plan")).toHaveLength(0);
    expect(screen.queryByTestId("repair-step-2")).not.toBeInTheDocument();
  });

  it("keeps closure disabled while running and gives the original cancellation entry instead", async () => {
    const server = mockApi([WAIT_REPAIR]);
    const { onClose } = renderPanel();
    await screen.findByTestId("repair-wait-hint");
    expect(screen.getByTestId("repair-abandon")).toBeDisabled();
    expect(screen.getByRole("link", { name: /生成任务.*取消入口/ })).toHaveAttribute(
      "href",
      `/projects/${PROJECT_ID}/production`,
    );
    fireEvent.click(screen.getByTestId("repair-close"));
    expect(onClose).toHaveBeenCalledOnce();
    expect(writes(server, "/close")).toHaveLength(0);
    expect(screen.getByText(/放弃只结束本次修复流程，不取消远端任务/)).toBeInTheDocument();
  });

  it("handles a backend running-close race without reporting success or creating another repair", async () => {
    const server = mockApi([REVIEW_REPAIR]);
    server.onClose = () => {
      server.repairs = [WAIT_REPAIR];
      return json({ code: "CONFLICT", details: { code: "REPAIR_RUNNING" } }, 409);
    };
    renderPanel();
    await waitFor(() => expect(screen.getByTestId("repair-abandon")).toBeEnabled());
    fireEvent.click(screen.getByTestId("repair-abandon"));
    expect(await screen.findByTestId("repair-feedback")).toHaveTextContent("不能关闭");
    expect(await screen.findByTestId("repair-wait-hint")).toBeInTheDocument();
    expect(screen.queryByTestId("repair-confirm")).not.toBeInTheDocument();
    expect(writes(server, "/close")[0]?.body).toEqual({ reason: "abandoned" });
  });

  it.each([
    ["ready_to_close", "repair-complete", "completed"],
    ["close_or_replan", "repair-abandon", "abandoned"],
  ] as const)(
    "explicitly closes %s, preserves history and permits a new plan",
    async (next_action, button, reason) => {
      const server = mockApi([{ ...VIDEO_REPAIR, next_action, next_step_ordinal: null }]);
      renderPanel();
      await waitFor(() => expect(screen.getByTestId(button)).toBeEnabled());
      expect(writes(server, "/close")).toHaveLength(0);
      expect(screen.queryByTestId("repair-execute-step")).not.toBeInTheDocument();
      fireEvent.click(screen.getByTestId(button));
      expect(await screen.findByTestId("repair-history")).toHaveTextContent("历史修复（1）");
      await waitFor(() => expect(screen.getByTestId("repair-confirm")).toBeEnabled());
      expect(writes(server, "/close")[0]?.body).toEqual({ reason });
      expect(writes(server, "/steps")).toHaveLength(0);
      expect(writes(server, "/repairs")).toHaveLength(0);
    },
  );

  it("does not interpret list read errors as an empty repair history", async () => {
    const server = mockApi();
    server.onList = () => json({ code: "HTTP_ERROR" }, 503);
    renderPanel();
    expect(await screen.findByTestId("repair-list-error")).toHaveTextContent(
      "不会把读取失败当成没有修复",
    );
    expect(screen.queryByTestId("repair-confirm")).not.toBeInTheDocument();
    expect(writes(server, "/repair-plan")).toHaveLength(0);
  });

  it("surfaces a stale creation plan without silently confirming a replacement", async () => {
    const server = mockApi();
    server.onCreate = () => json({ code: "CONFLICT" }, 409);
    renderPanel();
    fireEvent.click(await screen.findByTestId("repair-confirm"));
    expect(await screen.findByTestId("repair-plan-feedback")).toHaveTextContent("确认修复失败");
    expect(writes(server, "/repairs")).toHaveLength(1);
    expect(writes(server, "/steps")).toHaveLength(0);
  });

  it("uses the product vocabulary without calling normal wait or closure a human decision", () => {
    expect(repairStageLabel("keyframe_review")).toBe("审查并确认关键帧");
    expect(repairStageLabel("unknown_stage")).toBe("修复环节待同步");
    expect(repairStepActionLabel("review_candidate")).toContain("等待人工审查");
    expect(repairStepActionLabel("adopted")).toContain("设为正式");
    expect(repairStepActionLabel("ready_to_close")).toContain("显式完成");
    expect(repairStepActionLabel("reconcile_submission")).toBe("提交结果待核实，请核对原任务");
    expect(repairStepActionLabel("unknown_action")).toBe("按修复计划继续");
    expect(repairIsWaitingForHuman(REVIEW_REPAIR)).toBe(true);
    expect(repairIsWaitingForHuman(WAIT_REPAIR)).toBe(false);
    expect(repairIsWaitingForHuman({ ...NEW_REPAIR, next_action: "closed" })).toBe(false);
  });
});
