import { expect, test } from "@playwright/test";

import {
  EDITING_PROPOSAL_ID,
  EDITING_PROPOSAL_ITEM_ID,
  EDIT_SESSION_ID,
  PROJECT_ID,
  SECOND_SHOT_ID,
  installProfessionalMock,
} from "./professional-mocks";

const EDIT_SESSIONS_PATH = `/api/v1/projects/${PROJECT_ID}/edit-sessions`;
const EDIT_SESSION_PATH = `${EDIT_SESSIONS_PATH}/${EDIT_SESSION_ID}`;
const MANIFEST_PATH = `/api/v1/projects/${PROJECT_ID}/opencut-manifest`;

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

test("professional edit: formal manifest → persisted session → proposal-only suggestion", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  const initialProductionFacts = {
    shotVersion: state.shotVersion,
    visual: state.visual,
    assets: clone(state.assets),
    experiments: clone(state.experiments),
    annotations: clone(state.annotations),
    revisions: clone(state.revisions),
    board: clone(state.board),
  };

  // The production monitor consumes the current formal OpenCut v2 contract.
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("professional-workbench")).toBeVisible();
  await expect(page.getByText(/正式线镜头 2 个 · 3 条轨道 · opencut-manifest-v2/)).toBeVisible();

  // No session yet: the edit page is a read-only formal manifest preview.
  await page.goto(`/projects/${PROJECT_ID}/edit`);
  await expect(page.getByTestId("editing-workspace")).toBeVisible();
  await expect(page.getByRole("heading", { name: "OpenCut 剪辑交接" })).toBeVisible();
  await expect(page.getByTestId("editing-read-only")).toBeVisible();
  await expect(page.getByRole("heading", { name: "正式时间线" })).toBeVisible();
  await expect(page.getByTestId("create-edit-session")).toBeEnabled();

  // Creation is explicit and unique: one CSRF fetch followed by one POST.
  await page.getByTestId("create-edit-session").click();
  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  await expect(page.getByTestId("edit-session-editor")).toBeVisible();
  await expect(page.getByTestId("edit-session-version")).toHaveText("v1");
  await expect(page.getByTestId("edit-session-lineage")).toContainText("lineage_readonly");
  await expect(page.getByTestId("edit-session-clip")).toHaveCount(2);

  const createRequests = state.editing.requests.filter(
    (request) => request.path === EDIT_SESSIONS_PATH && request.method === "POST",
  );
  expect(createRequests).toHaveLength(1);
  expect(createRequests[0]).toEqual({ method: "POST", path: EDIT_SESSIONS_PATH, body: {} });
  const createIndex = state.editing.requests.indexOf(createRequests[0]);
  expect(state.editing.requests[createIndex - 1]).toEqual({
    method: "GET",
    path: "/api/v1/auth/csrf",
    body: {},
  });
  expect(state.editing.requests.filter((request) => request.path === MANIFEST_PATH)).toHaveLength(
    2,
  );

  // Reorder and duration edits stay local until the explicit save.
  const timelineBeforeManualEdit = clone(state.editing.session.timeline);
  await page.getByLabel("镜头 1 时长").fill("2.5");
  await page.getByTestId("move-clip-down-0").click();
  await expect(page.getByTestId("edit-session-dirty")).toHaveText("有未保存修改");
  await expect(page.getByLabel("镜头 1 时长")).toHaveValue("4");
  await expect(page.getByLabel("镜头 2 时长")).toHaveValue("2.5");
  expect(state.editing.session.timeline).toEqual(timelineBeforeManualEdit);

  const initialClips = timelineBeforeManualEdit.clips;
  const savedTimeline = {
    clips: [
      { ...initialClips[1], order: 1 },
      { ...initialClips[0], duration_seconds: 2.5, order: 2 },
    ],
    metadata: { ...timelineBeforeManualEdit.metadata },
  };
  const lineageBeforeSave = clone(state.editing.session.production_lineage);

  // Save only the editable timeline and let the server response become v2.
  await page.getByTestId("save-edit-timeline").click();
  await expect(page.getByText(/服务器响应已成为新的 clean baseline/)).toBeVisible();
  const saveRequests = state.editing.requests.filter(
    (request) => request.path === `${EDIT_SESSION_PATH}/timeline` && request.method === "PATCH",
  );
  expect(saveRequests).toHaveLength(1);
  expect(saveRequests[0]).toEqual({
    method: "PATCH",
    path: `${EDIT_SESSION_PATH}/timeline`,
    body: { timeline: savedTimeline },
  });
  expect(saveRequests[0].body).not.toHaveProperty("production_lineage");
  expect(JSON.stringify(saveRequests[0].body)).not.toContain("production_lineage");
  expect(state.editing.session.version).toBe(2);
  expect(state.editing.session.timeline).toEqual(savedTimeline);
  expect(state.editing.session.production_lineage).toEqual(lineageBeforeSave);

  // Reopen the exact URL and prove the saved server state, not a fresh manifest,
  // is the editor baseline.
  await page.reload();
  await expect(page.getByTestId("edit-session-editor")).toBeVisible();
  await expect(page.getByTestId("edit-session-version")).toHaveText("v2");
  await expect(page.getByLabel("镜头 1 时长")).toHaveValue("4");
  await expect(page.getByLabel("镜头 2 时长")).toHaveValue("2.5");
  await expect(page.getByTestId("edit-session-clip").nth(0)).toContainText(SECOND_SHOT_ID);
  const sessionGets = state.editing.requests.filter(
    (request) => request.path === EDIT_SESSION_PATH && request.method === "GET",
  );
  expect(sessionGets).toHaveLength(2);
  expect(sessionGets).toEqual([
    { method: "GET", path: EDIT_SESSION_PATH, body: {} },
    { method: "GET", path: EDIT_SESSION_PATH, body: {} },
  ]);

  // Export is read-only and uses the same exact persisted session identity.
  await page.getByTestId("export-edit-session").click();
  const exportPanel = page.getByTestId("edit-session-export");
  await expect(exportPanel).toContainText("dramaforge-edit-v1");
  await expect(exportPanel).toContainText("6.5");
  await expect(exportPanel).toContainText("2");
  const exportRequests = state.editing.requests.filter(
    (request) => request.path === `${EDIT_SESSION_PATH}/export` && request.method === "GET",
  );
  expect(exportRequests).toEqual([
    { method: "GET", path: `${EDIT_SESSION_PATH}/export`, body: {} },
  ]);
  expect(state.editing.session.timeline).toEqual(savedTimeline);
  expect(state.editing.session.production_lineage).toEqual(lineageBeforeSave);

  // The suggestion request uses the actual reopened v2 and remains pending;
  // it is not an implicit timeline apply or save.
  const timelineBeforeSuggestion = clone(state.editing.session.timeline);
  const lineageBeforeSuggestion = clone(state.editing.session.production_lineage);
  await page.getByTestId("editing-director-suggestion-instruction").fill("让开场更快进入冲突");
  await page.getByTestId("request-editing-director-suggestion").click();
  const preview = page.getByTestId("editing-suggestion-preview");
  await expect(preview).toBeVisible();
  await expect(preview).toHaveAttribute("data-proposal-id", EDITING_PROPOSAL_ID);
  await expect(preview).toHaveAttribute("data-item-id", EDITING_PROPOSAL_ITEM_ID);
  await expect(page.getByTestId("editing-suggestion-base-version")).toHaveText("v2");
  await expect(page.getByTestId("editing-suggestion-pending-status")).toHaveText("pending");
  await expect(preview).toContainText("待审核建议预览，不是已应用的时间线事件");
  await expect(page.getByTestId("editing-suggestion-operation")).toHaveCount(2);
  await expect(page.getByTestId("editing-suggestion-operation").nth(0)).toHaveAttribute(
    "data-operation",
    "reorder_clips",
  );
  await expect(page.getByTestId("editing-suggestion-operation").nth(0)).toContainText(
    "edit-clip-1 → edit-clip-2",
  );
  await expect(page.getByTestId("editing-suggestion-operation").nth(1)).toHaveAttribute(
    "data-operation",
    "set_clip_duration",
  );
  await expect(page.getByTestId("editing-suggestion-operation").nth(1)).toContainText(
    "片段 edit-clip-2 · 时长 4s",
  );
  await expect(page.getByTestId("editing-suggestion-rationale")).toContainText(
    "让开场更快进入冲突",
  );
  await expect(page.getByTestId("editing-suggestion-benefit")).toHaveText(
    "只形成待审核建议，不改变正式生产产物。",
  );
  await expect(page.getByTestId("editing-suggestion-cost")).toHaveText(
    "需要人工确认并保存时间线版本。",
  );
  await expect(page.getByTestId("editing-suggestion-risk")).toHaveText(
    "顺序或时长变化会影响剪辑节奏。",
  );
  await expect(page.getByTestId("editing-suggestion-impact")).toHaveText(
    "仅影响当前 EditSession；production lineage 保持只读。",
  );

  const suggestionRequests = state.editing.requests.filter(
    (request) =>
      request.path === `${EDIT_SESSION_PATH}/director-suggestion` && request.method === "POST",
  );
  expect(suggestionRequests).toHaveLength(1);
  expect(suggestionRequests[0]).toEqual({
    method: "POST",
    path: `${EDIT_SESSION_PATH}/director-suggestion`,
    body: {
      expected_session_version: state.editing.session.version,
      user_instruction: "让开场更快进入冲突",
    },
  });
  expect(suggestionRequests[0].body).not.toHaveProperty("project_id");
  expect(suggestionRequests[0].body).not.toHaveProperty("session_id");
  expect(suggestionRequests[0].body).not.toHaveProperty("production_lineage");
  expect(state.editing.suggestionResponses).toHaveLength(1);
  expect(state.editing.suggestionResponses[0]).toMatchObject({
    proposal_id: EDITING_PROPOSAL_ID,
    item_id: EDITING_PROPOSAL_ITEM_ID,
  });
  expect(state.editing.session.timeline).toEqual(timelineBeforeSuggestion);
  expect(state.editing.session.production_lineage).toEqual(lineageBeforeSuggestion);
  expect(saveRequests).toHaveLength(1);
  await expect(page.getByTestId("save-edit-timeline")).toBeDisabled();

  // Suggestion generation must not dispatch provider/runtime/worker/generation work
  // or mutate any formal production fact.
  expect(
    state.editing.requests.filter((request) =>
      /provider|runtime|worker|generation|node-runs|\/professional\/shots\//i.test(request.path),
    ),
  ).toEqual([]);
  expect({
    shotVersion: state.shotVersion,
    visual: state.visual,
    assets: state.assets,
    experiments: state.experiments,
    annotations: state.annotations,
    revisions: state.revisions,
    board: state.board,
  }).toEqual(initialProductionFacts);
});
