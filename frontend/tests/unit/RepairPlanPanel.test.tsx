import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RepairPlanPanel } from "../../src/features/review/RepairPlanPanel";
import {
  repairIsWaitingForHuman,
  repairStageLabel,
  repairStepActionLabel,
  type RepairRequestRead,
} from "../../src/features/review/repairApi";

const PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SHOT_ID = "11111111-1111-4111-8111-111111111111";

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const PLAN = {
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

const ACTIVE_REPAIR: RepairRequestRead = {
  id: "44444444-4444-4444-8444-444444444444",
  shot_id: SHOT_ID,
  option: "regenerate_keyframe_then_video",
  plan_hash: "a".repeat(64),
  plan_schema_version: 1,
  annotation_ids: ["33333333-3333-4333-8333-333333333333"],
  source_formal_artifact_id: null,
  closed_reason: null,
  created_at: "2026-09-15T00:00:00Z",
  next_action: "human_decision",
  steps: [
    {
      id: "55555555-5555-4555-8555-555555555555",
      ordinal: 1,
      stage: "keyframe_regenerate",
      plan_fingerprint: "b".repeat(64),
      command_key: "repair:step:1",
      node_run_id: "66666666-6666-4666-8666-666666666666",
      node_run_status: "completed",
      result_artifact_id: "77777777-7777-4777-8777-777777777777",
      confirmed_at: "2026-09-15T00:00:00Z",
      adopted_artifact_id: null,
      review_decision_id: null,
      next_action: "review_candidate",
    },
  ],
};

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <RepairPlanPanel projectId={PROJECT_ID} shotId={SHOT_ID} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("RepairPlanPanel", () => {
  afterEach(() => vi.restoreAllMocks());

  it("previews the plan, both options, the step list and the cost boundary", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/repair-plan") && init?.method === "POST") return json(PLAN);
      return json([]);
    });
    renderPanel();

    expect(await screen.findByTestId("repair-plan-summary")).toHaveTextContent("2 条待处理标注");
    expect(screen.getByTestId("repair-plan-cost")).toHaveTextContent("不做确定性报价");
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(screen.getByTestId("repair-plan-steps")).toHaveTextContent("审查并确认关键帧");
  });

  it("confirms the previewed plan hash and never dispatches media by itself", async () => {
    const writes: Array<{ url: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/repair-plan") && init?.method === "POST") return json(PLAN);
      if (url.endsWith("/repairs") && init?.method === "POST") {
        writes.push({
          url,
          body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {},
        });
        return json({ ...ACTIVE_REPAIR, next_action: "execute_step", steps: [] }, 201);
      }
      return json([]);
    });
    renderPanel();

    fireEvent.click(await screen.findByTestId("repair-confirm"));

    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]?.url).toBe(`/api/v1/projects/${PROJECT_ID}/shots/${SHOT_ID}/repairs`);
    expect(writes[0]?.body).toMatchObject({
      repair_option: "regenerate_keyframe_then_video",
      plan_hash: "a".repeat(64),
      idempotency_key: expect.stringMatching(/^repair:/),
    });
    // Only the intent was persisted; no step request was sent.
    expect(writes.every((call) => !call.url.includes("/steps"))).toBe(true);
    expect(await screen.findByTestId("repair-feedback")).toHaveTextContent("已确认修复计划");
  });

  it("shows an in-progress repair with review required instead of 'repair complete'", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/repair-plan") && init?.method === "POST") return json(PLAN);
      return json([ACTIVE_REPAIR]);
    });
    renderPanel();

    const active = await screen.findByTestId("repair-active");
    expect(active).toHaveAttribute("data-next-action", "human_decision");
    expect(screen.getByTestId("repair-step-1")).toHaveTextContent("第 1 步");
    // The stored run status is a contract token; the surface states it in Chinese.
    expect(screen.getByTestId("repair-step-1")).toHaveTextContent("运行状态 已完成");
    expect(screen.getByTestId("repair-step-1")).not.toHaveTextContent("completed");
    expect(screen.getByTestId("repair-review-hint")).toHaveTextContent("修复尚未完成");
    expect(screen.queryByTestId("repair-execute-step")).not.toBeInTheDocument();
    expect(screen.queryByTestId("repair-finished")).not.toBeInTheDocument();
  });

  it("offers the next step only when the server says one may be executed", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/repair-plan") && init?.method === "POST") return json(PLAN);
      if (url.includes("/steps")) {
        return json({
          node_run_id: "77777777-7777-4777-8777-777777777777",
          status: "queued",
          repair_id: ACTIVE_REPAIR.id,
          step_ordinal: 3,
          next_action: "human_decision",
        });
      }
      return json([{ ...ACTIVE_REPAIR, next_action: "execute_step" }]);
    });
    renderPanel();

    fireEvent.click(await screen.findByTestId("repair-execute-step"));

    await waitFor(() => expect(calls.some((url) => url.includes("/steps"))).toBe(true));
    const stepCall = calls.find((url) => url.includes("/steps"));
    expect(stepCall).toBe(
      `/api/v1/projects/${PROJECT_ID}/shots/${SHOT_ID}/repairs/${ACTIVE_REPAIR.id}/steps`,
    );
    expect(await screen.findByTestId("repair-feedback")).toHaveTextContent("已提交本步");
  });

  it("surfaces a stale plan instead of silently confirming it", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/repair-plan") && init?.method === "POST") return json(PLAN);
      if (url.endsWith("/repairs") && init?.method === "POST") {
        return json(
          { code: "CONFLICT", detail: "repair plan changed since it was previewed" },
          409,
        );
      }
      return json([]);
    });
    renderPanel();

    fireEvent.click(await screen.findByTestId("repair-confirm"));

    expect(await screen.findByTestId("repair-feedback")).toHaveTextContent("确认修复失败");
  });

  it("labels stages and step actions in the product vocabulary", () => {
    expect(repairStageLabel("keyframe_review")).toBe("审查并确认关键帧");
    // An unknown stored stage must not be printed raw on the surface.
    expect(repairStageLabel("unknown_stage")).toBe("修复环节待同步");
    expect(repairStepActionLabel("review_candidate")).toContain("等待人工审查");
    expect(repairStepActionLabel("unknown_action")).toBe("按修复计划继续");
    expect(repairIsWaitingForHuman(ACTIVE_REPAIR)).toBe(true);
    expect(repairIsWaitingForHuman({ ...ACTIVE_REPAIR, next_action: "execute_step" })).toBe(false);
  });
});
