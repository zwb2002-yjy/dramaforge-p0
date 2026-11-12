import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DirectorAgentPanel } from "../../src/features/director/DirectorAgentPanel";
import { getDirectorAgentRequest } from "../../src/features/director/api";
import { agentPanelStorageKey } from "../../src/features/director/agentPanelStorage";
import type { ShotLite } from "../../src/features/shots/api";
import { setSelectedWorkspaceId } from "../../src/lib/navigationPreferences";
import { queryKeys } from "../../src/lib/queryKeys";

const shot: ShotLite = {
  id: "shot-1",
  project_id: "project-1",
  scene_id: "scene-1",
  shot_number: 1,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "Old bridge",
  dialogue: "",
  duration_seconds: "3",
  status: "draft",
  sort_order: 1,
  version: 5,
  director_state: {},
  image_prompt: "Old prompt",
  video_prompt: "Old video",
  formal_keyframe_artifact_id: null,
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};
const user = { id: "user-1", email: "owner@example.com", display_name: "Owner" };
const result = {
  turn_id: "turn-1",
  thread_id: "thread-1",
  status: "completed",
  assistant_message_id: "answer-1",
  transport_status: "succeeded",
  proposal_ids: ["proposal-1"],
  stop_reason: "completed",
  usage: {},
  model_calls: 2,
  tool_calls: 1,
  version: 4,
};
const turn = {
  id: "turn-1",
  thread_id: "thread-1",
  turn_kind: "agent",
  request_key: "saved-request",
  status: "completed",
  revision: 4,
  output_snapshot: { proposal_ids: ["proposal-1"] },
};
const proposal = {
  id: "proposal-1",
  project_id: "project-1",
  thread_id: "thread-1",
  scope_type: "shot",
  scope_entity_id: "shot-1",
  status: "pending",
  items: [
    {
      id: "item-1",
      command: "shot.update_image_prompt",
      payload: { shot_id: "shot-1", image_prompt: "New prompt" },
      expected_target_version: 5,
      status: "pending",
      rationale: "Keep the documented arches.",
      benefit: "",
      cost: "",
      risk: "",
      impact: "",
    },
  ],
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

function setup({
  restored = false,
  dropped = false,
  applyConflict = false,
  running = false,
  messageErrorStatus,
  requestAccepted,
  applyStale = false,
  applyLost = false,
}: {
  restored?: boolean;
  dropped?: boolean;
  applyConflict?: boolean;
  running?: boolean;
  messageErrorStatus?: number;
  requestAccepted?: boolean;
  applyStale?: boolean;
  applyLost?: boolean;
} = {}) {
  const calls: { path: string; method: string; body: Record<string, unknown> }[] = [];
  let known = restored || running;
  let outcome: typeof result | null = running
    ? { ...result, status: "thinking", proposal_ids: [] }
    : restored
      ? { ...result }
      : null;
  let currentProposal = structuredClone(proposal);
  let requestKey = "saved-request";
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    calls.push({ path, method, body });
    if (path.includes("/auth/me")) return json(user);
    if (path.includes("/auth/csrf")) return json({ csrf_token: "csrf" });
    if (path.includes("/director/turns?") && method === "GET") {
      const scope = new URL(path, "https://test.invalid").searchParams.get("scope_entity_id");
      return json(
        known && scope === shot.id
          ? [
              {
                ...turn,
                request_key: requestKey,
                status: outcome?.status ?? "thinking",
                output_snapshot: { proposal_ids: outcome?.proposal_ids ?? [] },
              },
            ]
          : [],
      );
    }
    if (path.endsWith("/director/threads") && method === "POST")
      return json({ id: "thread-1", scope_type: "shot", scope_entity_id: shot.id }, 201);
    if (path.includes("/threads/thread-1/messages") && method === "POST") {
      requestKey = String(body.request_key);
      known = requestAccepted !== false;
      if (dropped) throw new TypeError("Connection interrupted after submission");
      if (messageErrorStatus)
        return json(
          {
            code: "DOMAIN_ERROR",
            detail: "Receipt phase failed",
            details:
              requestAccepted === false
                ? { request_accepted: false, code: "DIRECTOR_AGENT_TOOLS_UNAVAILABLE" }
                : {},
          },
          messageErrorStatus,
        );
      outcome = { ...result };
      return json(outcome);
    }
    if (path.includes("/threads/thread-1/requests?"))
      return outcome
        ? json(outcome)
        : json({ code: "AGENT_REQUEST_NOT_FOUND", detail: "Not yet visible" }, 404);
    if (path.includes("/threads/thread-1?"))
      return json({
        id: "thread-1",
        scope_type: "shot",
        scope_entity_id: shot.id,
        messages: outcome
          ? [
              {
                id: "answer-1",
                turn_id: "turn-1",
                role: "assistant",
                content: "Review this proposal.",
                created_at: "2026-11-11T00:00:00Z",
              },
            ]
          : [],
        offset: 0,
        limit: 20,
        total: outcome ? 1 : 0,
        has_more: false,
        has_previous: false,
      });
    if (path.includes("/turns/turn-1/tools?"))
      return json({ turn_id: "turn-1", offset: 0, limit: 20, tools: [] });
    if (path.endsWith("/proposals/proposal-1")) return json(currentProposal);
    if (path.endsWith("/proposals/proposal-1/apply")) {
      if (applyConflict) return json({ detail: "Shot version changed", code: "CONFLICT" }, 409);
      if (applyStale) {
        currentProposal = {
          ...currentProposal,
          status: "decided",
          items: currentProposal.items.map((item) => ({
            ...item,
            status: "stale",
          })),
        };
        return json({
          accepted: [],
          rejected: [],
          failed: [{ item_id: "item-1", error: "stale" }],
        });
      }
      const decisions = body.decisions as { item_id: string; decision: string }[];
      const accepted = decisions[0].decision === "accepted";
      currentProposal = {
        ...currentProposal,
        status: "applied",
        items: currentProposal.items.map((item) => ({
          ...item,
          status: accepted ? "accepted" : "rejected",
        })),
      };
      if (applyLost) throw new TypeError("Apply receipt was lost after commit");
      return json({
        accepted: accepted ? ["item-1"] : [],
        rejected: accepted ? [] : ["item-1"],
        failed: [],
      });
    }
    if (path.endsWith("/agent/turns/turn-1/stop")) {
      outcome = { ...result, status: "cancelled", proposal_ids: [], stop_reason: "user_stop" };
      return json(outcome);
    }
    throw new Error(`Unexpected ${method} ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const applied = vi.fn();
  const view = (dirty = false, target = shot) => (
    <QueryClientProvider client={client}>
      <DirectorAgentPanel projectId="project-1" shot={target} dirty={dirty} onApplied={applied} />
    </QueryClientProvider>
  );
  return {
    calls,
    fetcher,
    client,
    applied,
    view,
    complete: () => {
      outcome = { ...result };
    },
    setOutcome: (value: typeof result) => {
      outcome = value;
    },
    unknown: () => {
      outcome = {
        ...result,
        status: "failed",
        proposal_ids: [],
        stop_reason: "unknown_submission",
        transport_status: "unknown_submission",
      };
    },
  };
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  setSelectedWorkspaceId("workspace-1");
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DirectorAgentPanel", () => {
  it("mounts read-only, submits explicitly and only loads diagnostics when opened", async () => {
    const world = setup();
    render(world.view());
    const input = await screen.findByLabelText("导演要求");
    expect(world.calls.some((call) => call.method === "POST")).toBe(false);
    fireEvent.change(input, { target: { value: "Keep the bridge faithful." } });
    await waitFor(() => expect(screen.getByTestId("director-agent-send")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("director-agent-send"));
    await screen.findByTestId("director-agent-proposal");
    const posts = world.calls.filter((call) => call.method === "POST");
    expect(posts.map((call) => call.path)).toEqual([
      "/api/v1/projects/project-1/director/threads",
      "/api/v1/projects/project-1/director/threads/thread-1/messages",
    ]);
    expect(posts[1].body).toMatchObject({
      content: "Keep the bridge faithful.",
      expected_versions: { "shot:shot-1": 5 },
    });
    expect(world.calls.some((call) => call.path.includes("/tools?"))).toBe(false);
    fireEvent.click(screen.getByText("工具活动与诊断"));
    await waitFor(() =>
      expect(world.calls.some((call) => call.path.includes("/tools?"))).toBe(true),
    );
    expect(screen.getByTestId("director-agent-before")).toHaveTextContent("Old prompt");
    expect(screen.getByTestId("director-agent-after")).toHaveTextContent("New prompt");
  });

  it("keeps a dropped request observable across remount without resubmitting", async () => {
    const world = setup({ dropped: true });
    const first = render(world.view());
    fireEvent.change(await screen.findByLabelText("导演要求"), {
      target: { value: "Original instruction" },
    });
    await waitFor(() => expect(screen.getByTestId("director-agent-send")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("director-agent-send"));
    await screen.findByRole("alert");
    expect(screen.getByTestId("director-agent-send")).toBeDisabled();
    first.unmount();
    render(world.view());
    expect(await screen.findByLabelText("导演要求")).toHaveValue("Original instruction");
    fireEvent.click(screen.getByTestId("director-agent-refresh"));
    await waitFor(() =>
      expect(world.calls.some((call) => call.path.includes("/requests?request_key="))).toBe(true),
    );
    expect(
      world.calls.filter((call) => call.method === "POST" && call.path.endsWith("/messages")),
    ).toHaveLength(1);
    world.complete();
    fireEvent.click(screen.getByTestId("director-agent-refresh"));
    await screen.findByTestId("director-agent-proposal");
    expect(
      world.calls.filter((call) => call.method === "POST" && call.path.endsWith("/messages")),
    ).toHaveLength(1);
  });

  it.each([400, 401, 403, 409, 422])(
    "does not clear admitted-request identity merely on HTTP %s",
    async (status) => {
      const world = setup({ messageErrorStatus: status });
      render(world.view());
      fireEvent.change(await screen.findByLabelText("导演要求"), {
        target: { value: "Retain this instruction" },
      });
      await waitFor(() => expect(screen.getByTestId("director-agent-send")).not.toBeDisabled());
      fireEvent.click(screen.getByTestId("director-agent-send"));
      await screen.findByRole("alert");
      expect(screen.getByTestId("director-agent-send")).toBeDisabled();
      const key = agentPanelStorageKey("user-1", "workspace-1", "project-1", "shot-1");
      const retained = JSON.parse(sessionStorage.getItem(key)!);
      expect(retained.pending.requestKey).toEqual(expect.any(String));
      expect(retained.draft).toBe("Retain this instruction");
      fireEvent.click(screen.getByTestId("director-agent-refresh"));
      await waitFor(() =>
        expect(world.calls.some((call) => call.path.includes("/requests?"))).toBe(true),
      );
      expect(screen.getByTestId("director-agent-send")).toBeDisabled();
      expect(JSON.parse(sessionStorage.getItem(key)!).pending.requestKey).toBe(
        retained.pending.requestKey,
      );
      expect(
        world.calls.filter((call) => call.method === "POST" && call.path.endsWith("/messages")),
      ).toHaveLength(1);
    },
  );

  it("keeps an unknown-submission terminal receipt blocked without replaying its POST", async () => {
    const world = setup({ dropped: true });
    render(world.view());
    fireEvent.change(await screen.findByLabelText("导演要求"), {
      target: { value: "Observe uncertain request" },
    });
    await waitFor(() => expect(screen.getByTestId("director-agent-send")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("director-agent-send"));
    await screen.findByRole("alert");
    world.unknown();
    fireEvent.click(screen.getByTestId("director-agent-refresh"));
    await waitFor(() =>
      expect(screen.getByTestId("director-agent-status")).toHaveTextContent("提交状态待核实"),
    );
    expect(screen.getByTestId("director-agent-send")).toBeDisabled();
    expect(
      world.calls.filter((call) => call.method === "POST" && call.path.endsWith("/messages")),
    ).toHaveLength(1);
  });

  it("blocks dirty send/apply, preserves inputs on conflict, and supports explicit rejection", async () => {
    const world = setup({ restored: true, applyConflict: true });
    const rendered = render(world.view(true));
    fireEvent.change(await screen.findByLabelText("导演要求"), {
      target: { value: "Keep my draft" },
    });
    await screen.findByTestId("director-agent-proposal");
    expect(screen.getByTestId("director-agent-send")).toBeDisabled();
    expect(screen.getByTestId("director-agent-apply")).toBeDisabled();
    expect(screen.getByTestId("director-agent-reject")).not.toBeDisabled();
    rendered.rerender(world.view(false));
    fireEvent.click(screen.getByTestId("director-agent-apply"));
    await screen.findByText(/未覆盖你的输入/);
    expect(screen.getByLabelText("导演要求")).toHaveValue("Keep my draft");
    expect(world.applied).not.toHaveBeenCalled();
    expect(world.calls.find((call) => call.path.endsWith("/apply"))?.body).toEqual({
      decisions: [{ item_id: "item-1", decision: "accepted" }],
    });
  });

  it.each(["accepted", "rejected"])("uses the explicit %s proposal decision", async (decision) => {
    const world = setup({ restored: true });
    render(world.view());
    await screen.findByTestId("director-agent-proposal");
    fireEvent.click(
      screen.getByTestId(
        decision === "accepted" ? "director-agent-apply" : "director-agent-reject",
      ),
    );
    await waitFor(() =>
      expect(world.calls.some((call) => call.path.endsWith("/apply"))).toBe(true),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("director-agent-proposal")).not.toBeInTheDocument(),
    );
    expect(world.applied).toHaveBeenCalledTimes(decision === "accepted" ? 1 : 0);
  });

  it("never exposes a cached previous user's recovery before fresh authentication", async () => {
    const world = setup();
    world.client.setQueryData(queryKeys.auth.currentUser(), { ...user, id: "old-user" });
    sessionStorage.setItem(
      agentPanelStorageKey("old-user", "workspace-1", "project-1", "shot-1"),
      JSON.stringify({ draft: "PRIVATE OLD USER DRAFT", pending: null }),
    );
    let confirm!: (response: Response) => void;
    const original = world.fetcher.getMockImplementation()!;
    world.fetcher.mockImplementation((input, init) =>
      String(input).includes("/auth/me")
        ? new Promise<Response>((resolve) => {
            confirm = resolve;
          })
        : original(input, init),
    );
    render(world.view());
    expect(screen.queryByText("PRIVATE OLD USER DRAFT")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("导演要求")).not.toBeInTheDocument();
    await waitFor(() => expect(confirm).toBeDefined());
    confirm(json(user));
    expect(await screen.findByLabelText("导演要求")).toHaveValue("");
    expect(world.calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("restores drafts only for the same shot and workspace", async () => {
    const world = setup();
    const rendered = render(world.view());
    fireEvent.change(await screen.findByLabelText("导演要求"), {
      target: { value: "Shot one draft" },
    });
    rendered.rerender(world.view(false, { ...shot, id: "shot-2" }));
    expect(await screen.findByLabelText("导演要求")).toHaveValue("");
    rendered.rerender(world.view());
    expect(await screen.findByLabelText("导演要求")).toHaveValue("Shot one draft");
    setSelectedWorkspaceId("workspace-2");
    await waitFor(() => expect(screen.getByLabelText("导演要求")).toHaveValue(""));
    expect(world.calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("stops an existing Agent turn through its dedicated revision-gated endpoint", async () => {
    const world = setup({ running: true });
    render(world.view());
    fireEvent.click(await screen.findByTestId("director-agent-stop"));
    await waitFor(() =>
      expect(screen.getByTestId("director-agent-status")).toHaveTextContent("已停止"),
    );
    const writes = world.calls.filter((call) => call.method === "POST");
    expect(writes).toHaveLength(1);
    expect(writes[0].path).toBe("/api/v1/projects/project-1/director/agent/turns/turn-1/stop");
    expect(writes[0].body).toMatchObject({ expected_revision: 4 });
    expect(writes[0].body.request_key).toEqual(expect.any(String));
  });

  it("does not clear new dirty input when an earlier Apply finishes", async () => {
    const world = setup({ restored: true });
    const original = world.fetcher.getMockImplementation()!;
    let release!: () => void;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    world.fetcher.mockImplementation(async (input, init) => {
      if (String(input).endsWith("/proposal-1/apply")) await pending;
      return original(input, init);
    });
    const rendered = render(world.view());
    fireEvent.change(await screen.findByLabelText("导演要求"), {
      target: { value: "Keep this input" },
    });
    fireEvent.click(await screen.findByTestId("director-agent-apply"));
    await waitFor(() => expect(screen.getByTestId("director-agent-apply")).toBeDisabled());
    rendered.rerender(world.view(true));
    release();
    await waitFor(() =>
      expect(screen.queryByTestId("director-agent-proposal")).not.toBeInTheDocument(),
    );
    expect(world.applied).not.toHaveBeenCalled();
    expect(screen.getByLabelText("导演要求")).toHaveValue("Keep this input");
  });

  it("encodes request identities as query data and never posts when reading a receipt", async () => {
    const world = setup({ restored: true });
    const requestKey = "request/with spaces?and=parameters#fragment";
    await getDirectorAgentRequest("project-1", "thread-1", requestKey);
    expect(world.calls).toHaveLength(1);
    expect(world.calls[0].method).toBe("GET");
    const url = new URL(world.calls[0].path, "https://test.invalid");
    expect(url.pathname).toBe("/api/v1/projects/project-1/director/threads/thread-1/requests");
    expect(url.searchParams.get("request_key")).toBe(requestKey);
  });
});
