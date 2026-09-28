import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HumanReviewDecisionPanel } from "../../src/features/review/HumanReviewDecisionPanel";
import {
  reviewBlockerLabel,
  reviewMachineStatusLabel,
} from "../../src/features/review/reviewLabels";

const PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SHOT_ID = "11111111-1111-4111-8111-111111111111";
const ARTIFACT_ID = "22222222-2222-4222-8222-222222222222";
const REVIEW_RUN_ID = "33333333-3333-4333-8333-333333333333";

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function summary(overrides: Record<string, unknown> = {}) {
  return {
    shot_id: SHOT_ID,
    artifact_id: ARTIFACT_ID,
    review_kind: "identity",
    node_key: "identity_review",
    review_node_run_id: REVIEW_RUN_ID,
    review_artifact_id: "44444444-4444-4444-8444-444444444444",
    machine_status: "needs_human",
    decision: null,
    decision_reason: null,
    applies: false,
    blocked_reason: "REVIEW_AWAITING_HUMAN",
    allowed_actions: ["approve", "reject"],
    shot_version: 4,
    ...overrides,
  };
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <HumanReviewDecisionPanel
        projectId={PROJECT_ID}
        shotId={SHOT_ID}
        artifactId={ARTIFACT_ID}
        reviewKind="identity"
        stage="formal_keyframe"
        shotVersion={4}
        title="关键帧身份审查"
      />
    </QueryClientProvider>,
  );
}

describe("HumanReviewDecisionPanel", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the machine verdict as evidence and says a decision is pending", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/review-summary")) return json(summary());
      return json({});
    });
    renderPanel();

    await waitFor(() =>
      expect(screen.getByTestId("review-machine-status")).toHaveTextContent("待人工判断"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("review-current-decision")).toHaveTextContent("尚未判断"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("review-blocker")).toHaveTextContent("尚未记录决定"),
    );
    // A machine `needs_human` is never presented as a pass.
    expect(screen.queryByText("已通过")).not.toBeInTheDocument();
  });

  it("requires a reason and records one explicit approval with an idempotency key", async () => {
    const writes: Array<{ url: string; body: Record<string, unknown>; key: string | undefined }> =
      [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.includes("/review-summary")) return json(summary());
      if (url.includes("/review-decisions")) {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        writes.push({
          url,
          body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {},
          key: headers["Idempotency-Key"],
        });
        return json(
          {
            id: "55555555-5555-4555-8555-555555555555",
            shot_id: SHOT_ID,
            artifact_id: ARTIFACT_ID,
            review_node_run_id: REVIEW_RUN_ID,
            review_artifact_id: "44444444-4444-4444-8444-444444444444",
            review_kind: "identity",
            decision: "approved",
            reason: "口型一致",
            actor_id: "66666666-6666-4666-8666-666666666666",
            shot_version_at_decision: 4,
            supersedes_id: null,
            created_at: "2026-09-15T00:00:00Z",
          },
          201,
        );
      }
      return json({});
    });
    renderPanel();

    const approve = await screen.findByTestId("review-approve-identity");
    expect(approve).toBeDisabled();
    fireEvent.change(screen.getByLabelText("关键帧身份审查判断理由"), {
      target: { value: "口型一致" },
    });
    fireEvent.click(approve);

    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]?.url).toBe(`/api/v1/projects/${PROJECT_ID}/shots/${SHOT_ID}/review-decisions`);
    expect(writes[0]?.key).toMatch(/^review:/);
    expect(writes[0]?.body).toMatchObject({
      artifact_id: ARTIFACT_ID,
      review_node_run_id: REVIEW_RUN_ID,
      review_kind: "identity",
      decision: "approved",
      reason: "口型一致",
      expected_shot_version: 4,
    });
    expect(await screen.findByTestId("review-decision-feedback")).toHaveTextContent(
      "已记录人工通过",
    );
  });

  it("records a rejection as its own decision", async () => {
    const decisions: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.includes("/review-summary")) return json(summary());
      if (url.includes("/review-decisions")) {
        const body = JSON.parse(String(init?.body)) as { decision: string };
        decisions.push(body.decision);
        return json(
          {
            id: "55555555-5555-4555-8555-555555555555",
            shot_id: SHOT_ID,
            artifact_id: ARTIFACT_ID,
            review_node_run_id: REVIEW_RUN_ID,
            review_artifact_id: "44444444-4444-4444-8444-444444444444",
            review_kind: "identity",
            decision: "rejected",
            reason: "脸部崩坏",
            actor_id: "66666666-6666-4666-8666-666666666666",
            shot_version_at_decision: 4,
            supersedes_id: null,
            created_at: "2026-09-15T00:00:00Z",
          },
          201,
        );
      }
      return json({});
    });
    renderPanel();

    fireEvent.change(await screen.findByLabelText("关键帧身份审查判断理由"), {
      target: { value: "脸部崩坏" },
    });
    fireEvent.click(screen.getByTestId("review-reject-identity"));

    await waitFor(() => expect(decisions).toEqual(["rejected"]));
    expect(await screen.findByTestId("review-decision-feedback")).toHaveTextContent(
      "已记录人工拒绝",
    );
  });

  it("records demo confirmation without presenting it as a quality approval", async () => {
    const decisions: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.includes("/review-summary")) return json(summary());
      if (url.includes("/review-decisions")) {
        const body = JSON.parse(String(init?.body)) as { decision: string };
        decisions.push(body.decision);
        return json({ ...summary(), decision: "demo_confirmed", reason: "演示链路完成" }, 201);
      }
      return json({});
    });
    renderPanel();

    fireEvent.change(await screen.findByLabelText("关键帧身份审查判断理由"), {
      target: { value: "演示链路完成" },
    });
    fireEvent.click(screen.getByTestId("review-demo-confirm-identity"));

    await waitFor(() => expect(decisions).toEqual(["demo_confirmed"]));
    expect(await screen.findByTestId("review-decision-feedback")).toHaveTextContent(
      "不会放行正式素材",
    );
  });

  it("refuses to record a decision when no automatic evidence exists", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/review-summary")) {
        return json(
          summary({
            review_node_run_id: null,
            review_artifact_id: null,
            machine_status: null,
            blocked_reason: "REVIEW_DECISION_MISSING",
          }),
        );
      }
      return json({});
    });
    renderPanel();

    expect(await screen.findByTestId("review-evidence-missing")).toHaveTextContent(
      "还没有自动检查证据",
    );
    fireEvent.change(screen.getByLabelText("关键帧身份审查判断理由"), {
      target: { value: "看起来还行" },
    });
    expect(screen.getByTestId("review-approve-identity")).toBeDisabled();
    expect(screen.getByTestId("review-reject-identity")).toBeDisabled();
  });

  it("explains a stale decision instead of silently reusing it", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/review-summary")) {
        return json(
          summary({
            decision: "approved",
            decision_reason: "之前通过",
            applies: false,
            blocked_reason: "REVIEW_DECISION_STALE",
          }),
        );
      }
      return json({});
    });
    renderPanel();

    await waitFor(() =>
      expect(screen.getByTestId("review-current-decision")).toHaveTextContent("已通过"),
    );
    await waitFor(() => expect(screen.getByTestId("review-blocker")).toHaveTextContent("不再适用"));
  });

  it("clears the previous artifact's draft when the review target changes", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      const artifactId = new URL(url, "http://localhost").searchParams.get("artifact_id");
      return json(summary({ artifact_id: artifactId }));
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const panel = (artifactId: string) => (
      <QueryClientProvider client={client}>
        <HumanReviewDecisionPanel
          projectId={PROJECT_ID}
          shotId={SHOT_ID}
          artifactId={artifactId}
          reviewKind="identity"
          stage="formal_keyframe"
          shotVersion={4}
          title="关键帧身份审查"
        />
      </QueryClientProvider>
    );
    const view = render(panel(ARTIFACT_ID));
    fireEvent.change(await screen.findByLabelText("关键帧身份审查判断理由"), {
      target: { value: "甲的判断理由" },
    });
    view.rerender(panel("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"));
    expect(screen.getByLabelText("关键帧身份审查判断理由")).toHaveValue("");
    expect(screen.getByTestId("review-approve-identity")).toBeDisabled();
  });
  it("does not show A's late approval in B's review session", async () => {
    let finish!: (response: Response) => void;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.includes("/review-decisions")) {
        return new Promise<Response>((resolve) => {
          finish = resolve;
        });
      }
      const artifactId = new URL(url, "http://localhost").searchParams.get("artifact_id");
      return json(summary({ artifact_id: artifactId }));
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const panel = (artifactId: string) => (
      <QueryClientProvider client={client}>
        <HumanReviewDecisionPanel
          projectId={PROJECT_ID}
          shotId={SHOT_ID}
          artifactId={artifactId}
          reviewKind="identity"
          stage="formal_keyframe"
          shotVersion={4}
          title="关键帧身份审查"
        />
      </QueryClientProvider>
    );
    const view = render(panel(ARTIFACT_ID));
    fireEvent.change(await screen.findByLabelText("关键帧身份审查判断理由"), {
      target: { value: "甲的判断理由" },
    });
    await waitFor(() => expect(screen.getByTestId("review-approve-identity")).toBeEnabled());
    fireEvent.click(screen.getByTestId("review-approve-identity"));
    await waitFor(() => expect(finish).toBeDefined());
    view.rerender(panel("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"));
    finish(
      new Response(JSON.stringify({ decision: "approved" }), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    await waitFor(() => expect(client.isMutating()).toBe(0));
    expect(screen.queryByTestId("review-decision-feedback")).not.toBeInTheDocument();
    expect(screen.getByLabelText("关键帧身份审查判断理由")).toHaveValue("");
  });
  it("translates the machine and blocker vocabulary", () => {
    expect(reviewMachineStatusLabel(null)).toBe("尚无自动检查证据");
    expect(reviewMachineStatusLabel("needs_human")).toBe("待人工判断");
    expect(reviewMachineStatusLabel("not_applicable")).toBe("无需自动检查");
    // An unknown stored value must not reach the surface as a raw token.
    expect(reviewMachineStatusLabel("weird_status")).toBe("自动检查状态待同步");
    expect(reviewBlockerLabel(null)).toBeNull();
    expect(reviewBlockerLabel("REVIEW_DECISION_REJECTED")).toContain("拒绝");
    expect(reviewBlockerLabel("SOMETHING_ELSE")).toBe("该素材尚未满足采用条件。");
  });
});
