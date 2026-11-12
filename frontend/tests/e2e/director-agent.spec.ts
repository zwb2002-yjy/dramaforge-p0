import { expect, test, type Page } from "@playwright/test";

import {
  installProfessionalMock,
  PROJECT_ID,
  SCENE_ID,
  SECOND_SHOT_ID,
  SHOT_ID,
  WORKSPACE_ID,
} from "./professional-mocks";

const BASE = `/api/v1/projects/${PROJECT_ID}/director`;
const PROMPT = "保留石桥原有拱洞，以平视中景呈现人物的犹豫。";
const DATE = "2026-11-11T00:00:00Z";
const THREADS: Record<string, string> = {
  [SHOT_ID]: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
  [SECOND_SHOT_ID]: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
};
type AgentStatus = "thinking" | "completed" | "cancelled";
type RecordedRequest = {
  method: string;
  path: string;
  search: string;
  workspace: string | undefined;
  body: Record<string, unknown> | null;
};
type Round = {
  shotId: string;
  threadId: string;
  requestKey: string;
  content: string;
  status: AgentStatus;
  transportStatus: "submission_started" | "succeeded" | "unknown_submission";
  version: number;
  baseVersion: number;
  proposalStatus: "pending" | "applied" | "decided";
  itemStatus: "pending" | "accepted" | "rejected";
};

async function installAgentMock(
  page: Page,
  options: {
    loseResponse?: boolean;
    running?: boolean;
    receiptVisible?: boolean;
    beforeApplyReply?: () => Promise<void>;
  } = {},
) {
  const professional = await installProfessionalMock(page);
  const requests: RecordedRequest[] = [];
  const rounds = new Map<string, Round>();
  const state = { receiptVisible: options.receiptVisible ?? true };
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: { id: "agent-owner", email: "owner@example.com", display_name: "创作者" },
    }),
  );
  await page.route("**/api/v1/workspaces", (route) =>
    route.fulfill({ json: [{ id: WORKSPACE_ID, name: "文化工作空间" }] }),
  );
  const turnId = (round: Round) =>
    round.shotId === SHOT_ID
      ? "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"
      : "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2";
  const proposalId = (round: Round) =>
    round.shotId === SHOT_ID
      ? "cccccccc-cccc-4ccc-8ccc-ccccccccccc1"
      : "cccccccc-cccc-4ccc-8ccc-ccccccccccc2";
  const itemId = (round: Round) =>
    `dddddddd-dddd-4ddd-8ddd-ddddddddddd${round.shotId === SHOT_ID ? 1 : 2}`;
  const receipt = (round: Round) => ({
    turn_id: turnId(round),
    thread_id: round.threadId,
    status: round.status,
    transport_status: round.transportStatus,
    assistant_message_id: round.status === "completed" ? "assistant-message" : null,
    proposal_ids: round.status === "completed" ? [proposalId(round)] : [],
    stop_reason:
      round.status === "completed"
        ? "completed"
        : round.status === "cancelled"
          ? "user_stop"
          : null,
    usage: { total_tokens: 15 },
    model_calls: round.status === "completed" ? 2 : 1,
    tool_calls: round.status === "completed" ? 2 : 1,
    version: round.version,
  });
  const turn = (round: Round) => ({
    ...receipt(round),
    id: turnId(round),
    project_id: PROJECT_ID,
    workspace_id: WORKSPACE_ID,
    actor_id: "agent-owner",
    turn_kind: "agent",
    origin_agent_turn_id: null,
    scope_type: "shot",
    scope_entity_id: round.shotId,
    request_key: round.requestKey,
    context_hash: "a".repeat(64),
    input_versions: { [`shot:${round.shotId}`]: round.baseVersion },
    intent_snapshot: {},
    model_resolution: { model_id: "litellm/owned/director" },
    transport_record_id: null,
    engine_version: "langgraph:test:director-agent-v1",
    state_schema_version: "director-agent-v1",
    runtime_execution_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
    runtime_revision: 1,
    request_summary: {},
    response_summary: {},
    token_usage: { total_tokens: 15 },
    reported_cost: null,
    cost_status: "unknown",
    currency: "USD",
    output_hash: "b".repeat(64),
    output_snapshot: { proposal_ids: receipt(round).proposal_ids },
    wait_reason: receipt(round).stop_reason,
    revision: round.version,
    proposal_id: receipt(round).proposal_ids[0] ?? null,
    dispatched_command_key: null,
    node_run_ids: [],
    step_count: 2,
    schema_repair_count: 0,
    deadline: null,
    last_error: null,
    created_at: DATE,
    updated_at: DATE,
  });

  await page.route(`**${BASE}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const path = url.pathname;
    const body = request.postDataJSON() as Record<string, unknown> | null;
    const workspace = request.headers()["x-workspace-id"];
    requests.push({ method, path, search: url.search, workspace, body });
    if (workspace !== WORKSPACE_ID) {
      await route.fulfill({ status: 404, json: { detail: "Project not found" } });
      return;
    }
    if (path === `${BASE}/capabilities`) {
      await route.fulfill({
        json: {
          effective_engine: "langgraph",
          runtime_turns_available: true,
          checkpoint_configured: true,
          manual_production_available: true,
        },
      });
      return;
    }
    if (path === `${BASE}/threads` && method === "POST") {
      expect(body?.scope_type).toBe("shot");
      const shotId = String(body?.scope_entity_id);
      const threadId = THREADS[shotId];
      expect(threadId).toBeTruthy();
      await route.fulfill({
        status: 201,
        json: { id: threadId, scope_type: "shot", scope_entity_id: shotId },
      });
      return;
    }
    const threadMatch = path.match(/\/threads\/([^/]+)(?:\/(messages|requests))?$/);
    if (threadMatch) {
      const [, threadId, action] = threadMatch;
      const shotId = Object.keys(THREADS).find((id) => THREADS[id] === threadId)!;
      if (action === "messages" && method === "POST") {
        expect(body?.request_key).toEqual(expect.any(String));
        expect(body?.expected_versions).toEqual({ [`shot:${shotId}`]: professional.shotVersion });
        const round: Round = {
          shotId,
          threadId,
          requestKey: String(body?.request_key),
          content: String(body?.content),
          status: options.running ? "thinking" : "completed",
          version: 3,
          transportStatus: options.running ? "submission_started" : "succeeded",
          baseVersion: professional.shotVersion,
          proposalStatus: "pending",
          itemStatus: "pending",
        };
        rounds.set(threadId, round);
        if (options.loseResponse) await route.abort("failed");
        else await route.fulfill({ json: receipt(round) });
        return;
      }
      const round = rounds.get(threadId);
      if (action === "requests" && method === "GET") {
        // The panel probes the receipt as soon as a request is pending, before
        // the POST round exists. Only a known round owns a key to compare.
        if (round) expect(url.searchParams.get("request_key")).toBe(round.requestKey);
        if (!round || !state.receiptVisible) {
          await route.fulfill({
            status: 404,
            json: { code: "AGENT_REQUEST_NOT_FOUND", detail: "Request not found" },
          });
        } else await route.fulfill({ json: receipt(round) });
        return;
      }
      if (!action && method === "GET") {
        const messages = round
          ? [
              {
                id: "user-message",
                turn_id: turnId(round),
                role: "user",
                content: round.content,
                created_at: DATE,
              },
              ...(round.status === "completed"
                ? [
                    {
                      id: "assistant-message",
                      turn_id: turnId(round),
                      role: "assistant",
                      content: "已准备提示词提案，请审阅后采纳。",
                      created_at: DATE,
                    },
                  ]
                : []),
            ]
          : [];
        await route.fulfill({
          json: {
            id: threadId,
            scope_type: "shot",
            scope_entity_id: shotId,
            messages,
            offset: 0,
            limit: 30,
            total: messages.length,
            has_more: false,
            has_previous: false,
          },
        });
        return;
      }
    }
    const round = [...rounds.values()].find(
      (value) => path.includes(turnId(value)) || path.includes(proposalId(value)),
    );
    if (round && path === `${BASE}/turns/${turnId(round)}/tools`) {
      await route.fulfill({
        json: {
          turn_id: turnId(round),
          offset: 0,
          limit: 30,
          tools: [
            {
              call_id: "read-shot",
              step: 1,
              name: "shot_get",
              version: "1",
              status: "completed",
              schema_hash: "c".repeat(64),
              args_hash: "d".repeat(64),
              result_hash: "e".repeat(64),
              ok: true,
              error: null,
              observed_versions: { [`shot:${round.shotId}`]: round.baseVersion },
              provenance: { source: "dramaforge", risk: "READ" },
              latency_ms: 12,
              created_at: DATE,
            },
          ],
        },
      });
      return;
    }
    if (round && path === `${BASE}/turns/${turnId(round)}` && method === "GET") {
      await route.fulfill({ json: turn(round) });
      return;
    }
    if (round && path === `${BASE}/agent/turns/${turnId(round)}/stop` && method === "POST") {
      expect(body?.expected_revision).toBe(round.version);
      expect(body?.request_key).toEqual(expect.any(String));
      round.status = "cancelled";
      if (round.transportStatus === "submission_started")
        round.transportStatus = "unknown_submission";
      round.version += 1;
      await route.fulfill({ json: receipt(round) });
      return;
    }
    if (round && path === `${BASE}/proposals/${proposalId(round)}/apply` && method === "POST") {
      const decisions = body?.decisions as Array<{ item_id: string; decision: string }>;
      expect(decisions).toHaveLength(1);
      expect(decisions[0].item_id).toBe(itemId(round));
      if (decisions[0].decision === "accepted" && round.itemStatus === "pending") {
        expect(professional.shotVersion).toBe(round.baseVersion);
        professional.imagePrompt = PROMPT;
        professional.shotVersion += 1;
        round.itemStatus = "accepted";
        round.proposalStatus = "applied";
      } else if (decisions[0].decision === "rejected") {
        round.itemStatus = "rejected";
        round.proposalStatus = "decided";
      }
      await options.beforeApplyReply?.();
      await route.fulfill({
        json: {
          accepted: round.itemStatus === "accepted" ? [itemId(round)] : [],
          rejected: round.itemStatus === "rejected" ? [itemId(round)] : [],
          failed: [],
        },
      });
      return;
    }
    if (round && path === `${BASE}/proposals/${proposalId(round)}` && method === "GET") {
      await route.fulfill({
        json: {
          id: proposalId(round),
          project_id: PROJECT_ID,
          thread_id: round.threadId,
          scope_type: "shot",
          scope_entity_id: round.shotId,
          status: round.proposalStatus,
          created_at: DATE,
          items: [
            {
              id: itemId(round),
              command: "shot.update_image_prompt",
              payload: { shot_id: round.shotId, image_prompt: PROMPT },
              expected_target_version: round.baseVersion,
              status: round.itemStatus,
              rationale: "保留地方文化资料中的石桥结构。",
              benefit: "",
              cost: "",
              risk: "",
              impact: "",
            },
          ],
        },
      });
      return;
    }
    if (path === `${BASE}/turns` && method === "GET") {
      await route.fulfill({
        json: [...rounds.values()]
          .filter((value) => value.shotId === url.searchParams.get("scope_entity_id"))
          .map(turn),
      });
      return;
    }
    await route.fallback();
  });
  return { professional, requests, rounds, state };
}

async function openAgent(page: Page, shotId = SHOT_ID) {
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}?shotId=${shotId}&tool=director`);
  await page.getByRole("radio", { name: "对话协作", exact: true }).locator("..").click();
  await expect(page.getByRole("radio", { name: "对话协作", exact: true })).toBeChecked();
  await expect(page.getByTestId("director-agent-panel")).toHaveAttribute("data-shot-id", shotId);
  await expect(page.getByLabel("导演要求", { exact: true })).toBeVisible();
}

async function sendInstruction(page: Page) {
  await page.getByLabel("导演要求", { exact: true }).fill("先核对当前镜头，再建议更克制的提示词。");
  await page.getByTestId("director-agent-send").click();
}

async function openPrompts(page: Page) {
  if (!(await page.getByLabel("图片提示词", { exact: true }).isVisible())) {
    await page
      .getByTestId("shot-design-prompts")
      .getByRole("button", { name: "提示词", exact: true })
      .click();
  }
  await expect(page.getByLabel("图片提示词", { exact: true })).toBeVisible();
}

function barrier() {
  let release!: () => void;
  const reached = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { reached, release };
}

test("Agent conversation reads tools and requires explicit Apply to save the prompt", async ({
  page,
}) => {
  const mock = await installAgentMock(page);
  const original = mock.professional.imagePrompt;
  await openAgent(page);
  await sendInstruction(page);
  await expect(page.getByTestId("director-agent-proposal")).toBeVisible();
  await page
    .getByTestId("director-agent-tools")
    .getByRole("button", { name: /工具活动与诊断/ })
    .click();
  await expect(page.getByTestId("director-agent-tools")).toContainText(/镜头|shot_get/);
  await expect(page.getByTestId("director-agent-before")).toContainText(original);
  await expect(page.getByTestId("director-agent-after")).toContainText(PROMPT);
  expect(mock.professional.shotVersion).toBe(1);
  expect(mock.requests.filter((item) => item.path.endsWith("/apply"))).toEqual([]);
  await page.getByTestId("director-agent-apply").click();
  await expect.poll(() => mock.professional.shotVersion).toBe(2);
  expect(mock.professional.imagePrompt).toBe(PROMPT);
  await openPrompts(page);
  await expect(page.getByLabel("图片提示词", { exact: true })).toHaveValue(PROMPT);
  await expect(page.getByTestId("shot-design-dirty")).toHaveCount(0);
  await expect(page.getByTestId("shot-design-conflict")).toHaveCount(0);
  await expect(page.getByTestId("shot-primary-save")).toHaveCount(0);
  await expect(
    page.getByTestId("shot-inspector").getByTestId("shot-design-saved-state"),
  ).toBeVisible();
  expect(
    mock.requests.filter((item) => item.method === "POST" && item.path.endsWith("/apply")),
  ).toHaveLength(1);
  expect(
    mock.professional.editing.requests.filter(
      (item) =>
        item.method !== "GET" && /\/(design|executions|execution-plan|formal)$/.test(item.path),
    ),
  ).toEqual([]);
});

test("unsaved shot drafts block Agent send and Apply without discarding local edits", async ({
  page,
}) => {
  const mock = await installAgentMock(page);
  await openAgent(page);
  await sendInstruction(page);
  await expect(page.getByTestId("director-agent-proposal")).toBeVisible();
  await page.getByLabel("画面描述", { exact: true }).fill("尚未保存的地方文化画面修改");
  await expect(page.getByTestId("director-agent-dirty-guard")).toBeVisible();
  await expect(page.getByTestId("director-agent-send")).toBeDisabled();
  await expect(page.getByTestId("director-agent-apply")).toBeDisabled();
  await expect(page.getByLabel("画面描述", { exact: true })).toHaveValue(
    "尚未保存的地方文化画面修改",
  );
  expect(mock.professional.shotVersion).toBe(1);
  expect(mock.requests.filter((item) => item.path.endsWith("/apply"))).toEqual([]);
});

test("edits made while Apply is pending survive its response and server refetch", async ({
  page,
}) => {
  const submitted = barrier();
  const response = barrier();
  const mock = await installAgentMock(page, {
    beforeApplyReply: async () => {
      submitted.release();
      await response.reached;
    },
  });
  try {
    await openAgent(page);
    await sendInstruction(page);
    await expect(page.getByTestId("director-agent-proposal")).toBeVisible();
    await openPrompts(page);
    await page.getByTestId("director-agent-apply").click();
    await submitted.reached;
    const newDraft = "等待采纳回复期间，我新写的镜头提示词。";
    const newVisual = "等待期间新增的地方文化画面描述。";
    await page.getByLabel("图片提示词", { exact: true }).fill(newDraft);
    await page.getByLabel("画面描述", { exact: true }).fill(newVisual);
    await expect(page.getByTestId("director-agent-dirty-guard")).toBeVisible();
    response.release();
    await expect(page.getByTestId("director-agent-proposal")).toHaveCount(0);
    await expect(page.getByTestId("shot-design-conflict")).toBeVisible();
    await expect(page.getByLabel("图片提示词", { exact: true })).toHaveValue(newDraft);
    await expect(page.getByLabel("画面描述", { exact: true })).toHaveValue(newVisual);
    await expect(page.getByTestId("shot-design-dirty")).toBeVisible();
    expect(mock.professional.imagePrompt).toBe(PROMPT);
    expect(mock.professional.shotVersion).toBe(2);
    expect(
      mock.requests.filter((item) => item.method === "POST" && item.path.endsWith("/apply")),
    ).toHaveLength(1);
    expect(
      mock.professional.editing.requests.filter(
        (item) => item.method === "PATCH" && /\/(design|canvas)$/.test(item.path),
      ),
    ).toEqual([]);
  } finally {
    response.release();
  }
});

test("lost Agent response is recovered by the same request key using only GET, including reload", async ({
  page,
}) => {
  const mock = await installAgentMock(page, { loseResponse: true, receiptVisible: false });
  await openAgent(page);
  await sendInstruction(page);
  await expect(page.getByTestId("director-agent-refresh")).toBeVisible();
  await expect(page.getByTestId("director-agent-send")).toBeDisabled();
  // The panel fetches CSRF before the message POST; poll instead of racing it.
  const messageOf = () =>
    mock.requests.find((item) => item.method === "POST" && item.path.endsWith("/messages"));
  await expect.poll(() => Boolean(messageOf())).toBe(true);
  const message = messageOf()!;
  expect(message.body?.request_key).toEqual(expect.any(String));
  mock.state.receiptVisible = true;
  await page.getByTestId("director-agent-refresh").click();
  await expect(page.getByTestId("director-agent-proposal")).toBeVisible();
  const writes = mock.requests.filter((item) => item.method === "POST").length;
  await page.reload();
  await page.getByRole("radio", { name: "对话协作", exact: true }).locator("..").click();
  await expect(page.getByTestId("director-agent-proposal")).toBeVisible();
  expect(mock.requests.filter((item) => item.method === "POST")).toHaveLength(writes);
  expect(
    mock.requests.filter((item) => item.path.endsWith("/messages") && item.method === "POST"),
  ).toHaveLength(1);
  const lookups = mock.requests.filter((item) => item.path.endsWith("/requests"));
  expect(lookups.length).toBeGreaterThan(0);
  for (const lookup of lookups) {
    expect(lookup.method).toBe("GET");
    expect(new URLSearchParams(lookup.search).get("request_key")).toBe(message.body?.request_key);
  }
});

test("restored Agent identity never follows another shot or workspace", async ({ page }) => {
  const mock = await installAgentMock(page);
  await openAgent(page);
  await sendInstruction(page);
  await expect(page.getByTestId("director-agent-proposal")).toBeVisible();
  const writes = mock.requests.filter((item) => item.method === "POST").length;
  await openAgent(page, SECOND_SHOT_ID);
  await expect(page.getByTestId("director-agent-proposal")).toHaveCount(0);
  await expect(page.getByLabel("导演要求", { exact: true })).toHaveValue("");
  expect(mock.requests.filter((item) => item.method === "POST")).toHaveLength(writes);
  await openAgent(page);
  await expect(page.getByTestId("director-agent-proposal")).toBeVisible();
  await page.evaluate(() => {
    sessionStorage.setItem("dramaforge.selected-workspace-id", "workspace-other");
    localStorage.setItem("dramaforge.selected-workspace-id", "workspace-other");
    window.dispatchEvent(new Event("dramaforge:selected-workspace-changed"));
  });
  await expect(page.getByTestId("director-agent-proposal")).toHaveCount(0);
  await expect(page.getByLabel("导演要求", { exact: true })).toHaveValue("");
  expect(
    mock.requests.filter(
      (item) =>
        item.workspace === "workspace-other" &&
        (item.method === "POST" || item.path.includes("/requests")),
    ),
  ).toEqual([]);
});

test("an active recovered Agent turn stops through its own stop endpoint", async ({ page }) => {
  const mock = await installAgentMock(page, { loseResponse: true, running: true });
  await openAgent(page);
  await sendInstruction(page);
  await page.getByTestId("director-agent-refresh").click();
  await expect(page.getByTestId("director-agent-stop")).toBeEnabled();
  await page.getByTestId("director-agent-stop").click();
  await expect(page.getByTestId("director-agent-status")).toContainText(/停止|取消/);
  const stops = mock.requests.filter(
    (item) => item.method === "POST" && item.path.endsWith("/stop"),
  );
  expect(stops).toHaveLength(1);
  expect(stops[0].path).toContain("/director/agent/turns/");
  expect(
    mock.requests.some((item) => item.method === "POST" && item.path.includes("/runtime/")),
  ).toBe(false);
  expect(mock.professional.shotVersion).toBe(1);
});

test("Agent controls and proposal comparison remain accessible in a narrow workbench", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 768, height: 1000 });
  await installAgentMock(page);
  await openAgent(page);
  const input = page.getByRole("textbox", { name: "导演要求", exact: true });
  await input.fill("检查角色的镜头表现。");
  const send = page.getByTestId("director-agent-send");
  await expect(send).toHaveAccessibleName(/发送|导演|建议/);
  await send.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("director-agent-proposal")).toBeVisible();
  await expect(page.getByTestId("director-agent-apply")).toHaveAccessibleName(/采纳|应用|保存/);
  await expect(page.getByTestId("director-agent-reject")).toHaveAccessibleName(/拒绝|不采纳/);
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true);
  const panel = await page.getByTestId("director-agent-panel").boundingBox();
  expect(panel).not.toBeNull();
  expect(panel!.x).toBeGreaterThanOrEqual(0);
  expect(panel!.x + panel!.width).toBeLessThanOrEqual(769);
  expect(errors).toEqual([]);
});
