import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShotDirectorSuggestionPanel } from "../../src/features/director/ShotDirectorSuggestionPanel";
import type { DirectorTurnRead } from "../../src/features/director/suggestion-types";
import type { ShotLite } from "../../src/features/shots/api";

const SHOT: ShotLite = {
  id: "shot-1",
  project_id: "project-1",
  scene_id: "scene-1",
  shot_number: 1,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "A turns",
  dialogue: "",
  duration_seconds: "3",
  status: "draft",
  sort_order: 1,
  version: 5,
  director_state: { action: { description: "turns" } },
  image_prompt: "old image prompt",
  video_prompt: "old video prompt",
  formal_keyframe_artifact_id: null,
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function suggestion(baseShotVersion = 5) {
  return {
    base_shot_version: baseShotVersion,
    suggested_image_prompt: "new image prompt",
    suggested_video_prompt: "new video prompt",
    suggested_director_state: { action: { description: "new action" } },
    change_summary: "更克制并缓慢推进",
    director_evidence: {
      turn_id: "11111111-1111-4111-8111-111111111111",
      request_key: "suggestion:shot-1:test",
      context_hash: "a".repeat(64),
      output_hash: "b".repeat(64),
      slot: "planning.storyboard",
      model_id: "litellm/script-quality",
      model_binding_ref: "production-model-profile:p@1:planning.storyboard",
      actual_model: "upstream/director-v1",
      transport_status: "succeeded",
      token_usage: { total_tokens: 42 },
      reported_cost: "0.0042",
      cost_status: "reported",
      currency: "USD",
      schema_repair_count: 0,
    },
  };
}

function recommendation() {
  return {
    base_shot_version: 5,
    scope: "shot",
    category: "PERFORMANCE",
    current_state: "medium static：A turns",
    suggested_change: "先停顿再抬眼看",
    reason: "当前没有可被情绪消化的内部反应节拍。",
    expected_effect: "表演更可信。",
    risk: "需要稍长的镜头时长。",
    affected_facts: ["shot.director_state.performance"],
    typed_operations: [
      {
        op: "update_director_state",
        field: "performance",
        value: { beat: "breath_hold", gaze: "down_then_up" },
      },
    ],
    director_evidence: {
      turn_id: "22222222-2222-4222-8222-222222222222",
      request_key: "recommendation:shot-1:test",
      context_hash: "c".repeat(64),
      output_hash: "d".repeat(64),
      slot: "planning.storyboard",
      model_id: "litellm/script-quality",
      model_binding_ref: "production-model-profile:p@1:planning.storyboard",
      actual_model: null,
      transport_status: "succeeded",
      token_usage: {},
      reported_cost: null,
      cost_status: "unknown",
      currency: "USD",
      schema_repair_count: 0,
    },
  };
}

function directorTurn(
  task: "shot_director_suggestion" | "shot_director_recommendation" | "workbench_followup",
  output: Record<string, unknown>,
  overrides: Partial<DirectorTurnRead> = {},
): DirectorTurnRead {
  const id =
    task === "shot_director_recommendation"
      ? "22222222-2222-4222-8222-222222222222"
      : task === "workbench_followup"
        ? "33333333-3333-4333-8333-333333333333"
        : "11111111-1111-4111-8111-111111111111";
  return {
    id,
    project_id: "project-1",
    workspace_id: "workspace-1",
    actor_id: "actor-1",
    scope_type: "shot",
    scope_entity_id: "shot-1",
    request_key: `${task}:shot-1:test`,
    context_hash: "a".repeat(64),
    input_versions: { shot: 5 },
    intent_snapshot:
      task === "shot_director_suggestion"
        ? { user_instruction: "让情绪更克制，镜头缓慢推进" }
        : { kind: "proactive_shot_analysis" },
    model_resolution: {
      slot: "planning.storyboard",
      model_id: "litellm/script-quality",
      model_binding_ref: "production-model-profile:p@1:planning.storyboard",
    },
    transport_record_id: "provider-request-1",
    transport_status: "succeeded",
    request_summary: { task, max_steps: 4 },
    response_summary: { actual_model: "upstream/director-v1" },
    token_usage: { total_tokens: 42 },
    reported_cost: "0.0042",
    cost_status: "reported",
    currency: "USD",
    schema_repair_count: 1,
    output_hash: "b".repeat(64),
    output_snapshot: output,
    status: "awaiting_user",
    wait_reason: "proposal_decision",
    revision: 3,
    proposal_id: null,
    dispatched_command_key: null,
    node_run_ids: [],
    step_count: 1,
    deadline: "2026-09-09T00:00:00Z",
    last_error: null,
    created_at: "2026-09-08T00:00:00Z",
    updated_at: "2026-09-08T00:00:00Z",
    ...overrides,
  };
}

const suggestionOutput = () => {
  const output = { ...suggestion() } as Record<string, unknown>;
  delete output.director_evidence;
  return output;
};

const recommendationOutput = () => {
  const output = { ...recommendation() } as Record<string, unknown>;
  delete output.director_evidence;
  return output;
};

function renderPanel(onApplyDraft = vi.fn(), dirty = false): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ShotDirectorSuggestionPanel
        projectId="project-1"
        shot={SHOT}
        dirty={dirty}
        onApplyDraft={onApplyDraft}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("ShotDirectorSuggestionPanel", () => {
  it("generates a proactive recommendation without instruction and partially applies selected operations", async () => {
    const calls: Array<{ url: string; method: string; body?: Record<string, unknown> }> = [];
    const turn = directorTurn("shot_director_recommendation", recommendationOutput());
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({
        url,
        method,
        body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined,
      });
      if (url.endsWith("/auth/csrf")) return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url.includes("/director/turns?")) return Promise.resolve(json([]));
      if (url.endsWith(`/turns/${turn.id}`)) return Promise.resolve(json(turn));
      if (url.endsWith(`/turns/${turn.id}/decision`)) {
        return Promise.resolve(
          json({
            ...turn,
            revision: 4,
            response_summary: { user_decision: { decision: "accept" } },
          }),
        );
      }
      if (url.endsWith("/recommendation")) return Promise.resolve(json(recommendation()));
      return Promise.resolve(json({}));
    });
    const onApplyDraft = vi.fn();
    renderPanel(onApplyDraft);

    fireEvent.click(screen.getByTestId("request-proactive-director-recommendation"));
    expect(await screen.findByTestId("director-recommendation-preview")).toBeInTheDocument();
    expect(screen.getByText(/medium static/)).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-model-evidence")).toHaveTextContent(
      "litellm/script-quality",
    );
    expect(screen.getByTestId("recommendation-model-evidence")).toHaveTextContent("22222222");
    const request = calls.find((call) => call.url.endsWith("/recommendation"));
    expect(`${request?.method} ${request?.url}`).toBe(
      "POST /api/v1/projects/project-1/director/shots/shot-1/recommendation",
    );

    fireEvent.click(screen.getByTestId("recommendation-operation-0"));
    expect(screen.getByTestId("apply-director-recommendation")).toBeDisabled();
    fireEvent.click(screen.getByTestId("recommendation-operation-0"));
    fireEvent.click(screen.getByTestId("apply-director-recommendation"));
    await waitFor(() =>
      expect(onApplyDraft).toHaveBeenCalledWith({
        image_prompt: "old image prompt",
        video_prompt: "old video prompt",
        director_state: {
          action: { description: "turns" },
          performance: { beat: "breath_hold", gaze: "down_then_up" },
        },
      }),
    );
    const decision = calls.find((call) => call.url.endsWith("/decision"));
    expect(decision?.body).toEqual({
      expected_revision: 3,
      decision: "accept",
      accepted_operation_indices: [0],
    });
    expect(calls.some((call) => call.url.endsWith("/design"))).toBe(false);
    expect(calls.some((call) => call.url.endsWith("/execution-plan"))).toBe(false);
  });

  it("requests the selected shot, renders old/new diff, and applies only to draft", async () => {
    const calls: Array<{ url: string; method: string; body?: Record<string, unknown> }> = [];
    const turn = directorTurn("shot_director_suggestion", suggestionOutput());
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : undefined;
      calls.push({ url, method, body });
      if (url.endsWith("/auth/csrf")) return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url.includes("/director/turns?")) return Promise.resolve(json([]));
      if (url.endsWith(`/turns/${turn.id}`)) return Promise.resolve(json(turn));
      if (url.endsWith(`/turns/${turn.id}/decision`)) {
        return Promise.resolve(
          json({
            ...turn,
            revision: 4,
            response_summary: { user_decision: { decision: "accept" } },
          }),
        );
      }
      if (url.endsWith("/suggestion")) return Promise.resolve(json(suggestion()));
      return Promise.resolve(json({}));
    });
    const onApplyDraft = vi.fn();
    renderPanel(onApplyDraft);

    fireEvent.change(screen.getByLabelText("导演要求"), {
      target: { value: "让情绪更克制，镜头缓慢推进" },
    });
    fireEvent.click(screen.getByTestId("request-shot-director-suggestion"));

    expect(await screen.findByTestId("shot-director-suggestion-proposal")).toBeInTheDocument();
    expect(screen.getByTestId("suggestion-old-image-prompt")).toHaveTextContent("old image prompt");
    expect(screen.getByTestId("suggestion-new-image-prompt")).toHaveTextContent("new image prompt");
    expect(screen.getByTestId("suggestion-old-video-prompt")).toHaveTextContent("old video prompt");
    expect(screen.getByTestId("suggestion-new-video-prompt")).toHaveTextContent("new video prompt");
    expect(screen.getByTestId("suggestion-change-summary")).toHaveTextContent("更克制");
    expect(screen.getByTestId("suggestion-model-evidence")).toHaveTextContent(
      "upstream/director-v1",
    );
    expect(screen.getByTestId("suggestion-model-evidence")).toHaveTextContent("11111111");

    const request = calls.find((call) => call.url.endsWith("/suggestion"));
    expect(request?.method).toBe("POST");
    expect(request?.url).toBe("/api/v1/projects/project-1/director/shots/shot-1/suggestion");
    expect(request?.body).toEqual({
      scene_id: "scene-1",
      shot_id: "shot-1",
      expected_shot_version: 5,
      user_instruction: "让情绪更克制，镜头缓慢推进",
      request_key: expect.stringMatching(/^suggestion:shot-1:[0-9a-f-]{36}$/),
    });

    fireEvent.click(screen.getByTestId("apply-shot-director-suggestion"));
    await waitFor(() =>
      expect(onApplyDraft).toHaveBeenCalledWith({
        image_prompt: "new image prompt",
        video_prompt: "new video prompt",
        director_state: { action: { description: "new action" } },
      }),
    );
    expect(calls.some((call) => call.url.endsWith("/design"))).toBe(false);
    expect(calls.some((call) => call.url.endsWith("/execution-plan"))).toBe(false);
    expect(screen.getByTestId("apply-shot-director-suggestion")).toBeDisabled();
    expect(screen.getByTestId("discard-shot-director-suggestion")).toBeDisabled();
    expect(calls.find((call) => call.url.endsWith("/decision"))?.body).toEqual({
      expected_revision: 3,
      decision: "accept",
      accepted_operation_indices: [0],
    });
  });

  it("blocks requests while the Shot Design draft is dirty", () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    renderPanel(vi.fn(), true);
    fireEvent.change(screen.getByLabelText("导演要求"), { target: { value: "要求" } });
    expect(screen.getByTestId("request-shot-director-suggestion")).toBeDisabled();
    expect(screen.getByTestId("suggestion-dirty-guard")).toHaveTextContent("先保存或撤销");
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) => String(input).endsWith("/suggestion") && init?.method === "POST",
      ),
    ).toBe(false);
  });

  it("blocks applying a stale proposal and surfaces the backend error", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/director/turns?")) return Promise.resolve(json([]));
      if (url.endsWith("/auth/csrf")) return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url.endsWith("/suggestion")) return Promise.resolve(json(suggestion(4)));
      return Promise.resolve(json({}));
    });
    renderPanel();
    fireEvent.change(screen.getByLabelText("导演要求"), { target: { value: "要求" } });
    fireEvent.click(screen.getByTestId("request-shot-director-suggestion"));
    await screen.findByTestId("suggestion-stale-guard");
    expect(screen.getByTestId("apply-shot-director-suggestion")).toBeDisabled();

    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/director/turns?")) return Promise.resolve(json([]));
      if (url.endsWith("/auth/csrf")) return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url.endsWith("/suggestion")) {
        return Promise.resolve(
          json({ detail: "导演服务暂不可用", code: "DIRECTOR_SUGGESTION_FAILED" }, 422),
        );
      }
      return Promise.resolve(json({}));
    });
    // A new render keeps the test focused on the user-visible server message.
    renderPanel();
    fireEvent.change(screen.getAllByLabelText("导演要求").at(-1)!, { target: { value: "要求" } });
    fireEvent.click(screen.getAllByTestId("request-shot-director-suggestion").at(-1)!);
    expect(await screen.findByText(/导演服务暂不可用/)).toBeInTheDocument();
  });

  it("rehydrates the persisted output and next checkpoint without generating again", async () => {
    const turn = directorTurn("shot_director_suggestion", suggestionOutput(), {
      response_summary: {
        actual_model: "upstream/director-v1",
        coordination: {
          current_action: {
            action: "review_suggestion",
            reason: "The persisted suggestion is waiting for a user decision.",
          },
        },
      },
    });
    const calls: Array<{ url: string; method: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      calls.push({ url, method: init?.method ?? "GET" });
      if (url.includes("/director/turns?")) return Promise.resolve(json([turn]));
      return Promise.resolve(json({}));
    });

    renderPanel();
    expect(await screen.findByTestId("shot-director-suggestion-proposal")).toBeInTheDocument();
    expect(screen.getByTestId("director-current-understanding")).toHaveTextContent("让情绪更克制");
    expect(screen.getByTestId("director-next-action")).toHaveTextContent("review_suggestion");
    expect(screen.getByTestId("suggestion-new-image-prompt")).toHaveTextContent("new image prompt");
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("reconciles and stops only through revision-bound server controls", async () => {
    const waiting = directorTurn(
      "workbench_followup",
      {},
      {
        status: "awaiting_execution",
        wait_reason: "execution_in_progress",
        revision: 6,
        output_hash: null,
        node_run_ids: ["run-1"],
      },
    );
    let current = waiting;
    const calls: Array<{ url: string; body?: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      calls.push({
        url,
        body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined,
      });
      if (url.includes("/director/turns?")) return Promise.resolve(json([current]));
      if (url.endsWith("/auth/csrf")) return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url.endsWith(`/turns/${waiting.id}/resume`)) {
        current = { ...waiting, revision: 7, step_count: 3 };
        return Promise.resolve(
          json({
            turn_id: waiting.id,
            action: "wait_for_execution",
            requires_confirmation: false,
            reason: "Production is still active.",
            autonomy: "AUTO",
            fact_hash: "f".repeat(64),
            event_key: "event",
            turn_status: "awaiting_execution",
            turn_revision: 7,
            step_count: 3,
          }),
        );
      }
      if (url.endsWith(`/turns/${waiting.id}/stop`)) {
        current = { ...current, status: "cancelled", revision: 8 };
        return Promise.resolve(json(current));
      }
      return Promise.resolve(json({}));
    });
    renderPanel();
    await screen.findByTestId("director-current-turn");

    fireEvent.click(screen.getByTestId("resume-director-turn"));
    await waitFor(() =>
      expect(calls.find((call) => call.url.endsWith("/resume"))?.body).toMatchObject({
        expected_revision: 6,
      }),
    );
    await waitFor(() => expect(screen.getByText(/revision 7/)).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("stop-director-turn"));
    await waitFor(() =>
      expect(calls.find((call) => call.url.endsWith("/stop"))?.body).toEqual({
        expected_revision: 7,
      }),
    );
  });

  it("does not touch the draft when the durable decision fails", async () => {
    const turn = directorTurn("shot_director_suggestion", suggestionOutput());
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/director/turns?")) return Promise.resolve(json([]));
      if (url.endsWith("/auth/csrf")) return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url.endsWith("/suggestion")) return Promise.resolve(json(suggestion()));
      if (url.endsWith(`/turns/${turn.id}`)) return Promise.resolve(json(turn));
      if (url.endsWith(`/turns/${turn.id}/decision`)) {
        return Promise.resolve(
          json({ detail: "turn revision conflict", code: "DIRECTOR_TURN_REVISION_CONFLICT" }, 409),
        );
      }
      return Promise.resolve(json({}));
    });
    const onApplyDraft = vi.fn();
    renderPanel(onApplyDraft);
    fireEvent.change(screen.getByLabelText("导演要求"), { target: { value: "要求" } });
    fireEvent.click(screen.getByTestId("request-shot-director-suggestion"));
    await screen.findByTestId("shot-director-suggestion-proposal");
    fireEvent.click(screen.getByTestId("apply-shot-director-suggestion"));
    expect(await screen.findByText(/保存建议决定失败/)).toBeInTheDocument();
    expect(onApplyDraft).not.toHaveBeenCalled();
  });

  it("makes a local preview non-applicable when polling observes a stale turn", async () => {
    const staleTurn = directorTurn("shot_director_suggestion", suggestionOutput(), {
      status: "stale",
      wait_reason: "autonomy_changed",
      revision: 4,
    });
    let generated = false;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/director/turns?")) {
        return Promise.resolve(json(generated ? [staleTurn] : []));
      }
      if (url.endsWith("/auth/csrf")) return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url.endsWith("/suggestion")) {
        generated = true;
        return Promise.resolve(json(suggestion()));
      }
      return Promise.resolve(json({}));
    });
    renderPanel();
    fireEvent.change(screen.getByLabelText("导演要求"), { target: { value: "要求" } });
    fireEvent.click(screen.getByTestId("request-shot-director-suggestion"));
    expect(await screen.findByText(/该导演轮次已变为 stale/)).toBeInTheDocument();
    expect(screen.getByTestId("apply-shot-director-suggestion")).toBeDisabled();
    expect(screen.getByTestId("discard-shot-director-suggestion")).toBeDisabled();
  });

  it("shows a sync warning without fabricating a failed business state", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json({ detail: "network unavailable", code: "HTTP_ERROR" }, 503),
    );
    renderPanel();
    expect(await screen.findByTestId("director-sync-error")).toHaveTextContent("状态待同步");
    expect(screen.queryByText("已停止（失败）")).not.toBeInTheDocument();
  });
});
