import { expect, type Page } from "@playwright/test";

import { PROJECT_ID, SCENE_ID, SHOT_ID, type ProfessionalMockState } from "./professional-mocks";

/** Mock the real suggestion API, not the UI or the explicit design-save seam. */
export async function installContextualDirectorMock(page: Page, state: ProfessionalMockState) {
  const suggestionPath = `/api/v1/projects/${PROJECT_ID}/director/shots/${SHOT_ID}/suggestion`;
  const turnPath = `/api/v1/projects/${PROJECT_ID}/director/turns/33333333-3333-4333-8333-333333333333`;
  let generated = false;
  const suggestion = {
    base_shot_version: state.shotVersion,
    suggested_image_prompt: "rainy street, restrained expression, medium close-up",
    suggested_video_prompt: "slow push-in, pause before turning toward camera",
    suggested_director_state: { performance: { beat: "pause_then_turn" } },
    change_summary: "人物先停顿再转头，镜头缓慢推进",
    director_evidence: {
      turn_id: "33333333-3333-4333-8333-333333333333",
      request_key: "suggestion:shot:e2e",
      context_hash: "e".repeat(64),
      output_hash: "f".repeat(64),
      slot: "planning.storyboard",
      model_id: "litellm/script-quality",
      model_binding_ref: "production-model-profile:e2e@4:planning.storyboard",
      actual_model: "upstream/director-e2e",
      transport_status: "succeeded",
      token_usage: { total_tokens: 55 },
      reported_cost: "0.003",
      cost_status: "reported",
      currency: "USD",
      schema_repair_count: 0,
    },
  };
  await page.route(`**${suggestionPath}`, async (route) => {
    const request = route.request();
    const body = request.postDataJSON();
    state.editing.requests.push({ method: request.method(), path: suggestionPath, body });
    expect(request.method()).toBe("POST");
    expect(body).toEqual({
      scene_id: SCENE_ID,
      shot_id: SHOT_ID,
      expected_shot_version: suggestion.base_shot_version,
      user_instruction: "让人物更克制，先停顿再转头，镜头缓慢推进",
      request_key: expect.stringMatching(new RegExp(`^suggestion:${SHOT_ID}:[0-9a-f-]{36}$`)),
    });
    generated = true;
    await route.fulfill({ json: suggestion });
  });
  const turn = () => ({
    id: suggestion.director_evidence.turn_id,
    project_id: PROJECT_ID,
    workspace_id: "workspace-professional",
    actor_id: "owner-professional",
    scope_type: "shot",
    scope_entity_id: SHOT_ID,
    request_key: suggestion.director_evidence.request_key,
    context_hash: suggestion.director_evidence.context_hash,
    input_versions: { shot: suggestion.base_shot_version },
    intent_snapshot: { user_instruction: "让人物更克制，先停顿再转头，镜头缓慢推进" },
    model_resolution: {
      slot: suggestion.director_evidence.slot,
      model_id: suggestion.director_evidence.model_id,
      model_binding_ref: suggestion.director_evidence.model_binding_ref,
    },
    transport_record_id: "provider-request-e2e",
    transport_status: "succeeded",
    request_summary: { task: "shot_director_suggestion", max_steps: 4 },
    response_summary: { actual_model: suggestion.director_evidence.actual_model },
    token_usage: suggestion.director_evidence.token_usage,
    reported_cost: suggestion.director_evidence.reported_cost,
    cost_status: suggestion.director_evidence.cost_status,
    currency: suggestion.director_evidence.currency,
    schema_repair_count: suggestion.director_evidence.schema_repair_count,
    output_hash: suggestion.director_evidence.output_hash,
    output_snapshot: {
      base_shot_version: suggestion.base_shot_version,
      suggested_image_prompt: suggestion.suggested_image_prompt,
      suggested_video_prompt: suggestion.suggested_video_prompt,
      suggested_director_state: suggestion.suggested_director_state,
      change_summary: suggestion.change_summary,
    },
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
  });
  await page.route(`**/api/v1/projects/${PROJECT_ID}/director/turns**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname.endsWith("/director/turns")) {
      await route.fulfill({ json: generated ? [turn()] : [] });
      return;
    }
    if (request.method() === "GET" && url.pathname === turnPath) {
      await route.fulfill({ json: turn() });
      return;
    }
    if (request.method() === "POST" && url.pathname === `${turnPath}/decision`) {
      const body = request.postDataJSON();
      state.editing.requests.push({ method: request.method(), path: url.pathname, body });
      expect(body).toEqual({
        expected_revision: 3,
        decision: "accept",
        accepted_operation_indices: [0],
      });
      await route.fulfill({
        json: {
          ...turn(),
          revision: 4,
          wait_reason: "design_save",
          response_summary: {
            actual_model: suggestion.director_evidence.actual_model,
            user_decision: {
              decision: "accept",
              accepted_operation_indices: [0],
              rejected_operation_indices: [],
              output_hash: suggestion.director_evidence.output_hash,
            },
          },
        },
      });
      return;
    }
    await route.fallback();
  });
  return suggestion;
}

export async function exerciseContextualDirector(
  page: Page,
  state: ProfessionalMockState,
  suggestion: Awaited<ReturnType<typeof installContextualDirectorMock>>,
) {
  const writes = () =>
    state.editing.requests.filter(({ method, path, body }) => {
      if (method === "GET" || path.endsWith("/auth/csrf")) return false;
      if (path === `/api/v1/projects/${PROJECT_ID}/workspace-state`) {
        // Navigation may persist last-view preferences, never creative facts.
        expect(method).toBe("PATCH");
        expect(body).toEqual({ state: { last_view: expect.any(String) } });
        return false;
      }
      return true;
    });
  const before = {
    version: state.shotVersion,
    image: state.imagePrompt,
    video: state.videoPrompt,
    director: structuredClone(state.directorState),
  };
  const assertServerUnchanged = () => {
    expect(state.shotVersion).toBe(before.version);
    expect(state.imagePrompt).toBe(before.image);
    expect(state.videoPrompt).toBe(before.video);
    expect(state.directorState).toEqual(before.director);
    expect(state.proposals).toHaveLength(0);
    expect(state.revisions).toHaveLength(0);
  };
  await expect(page.getByText("补齐动作因果", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/检测到该镜头包含主角/)).toHaveCount(0);
  const target = `/projects/${PROJECT_ID}/scenes/${SCENE_ID}?shotId=${SHOT_ID}&tool=director`;
  await expect(page.getByTestId("open-contextual-director")).toHaveAttribute("href", target);
  expect(writes()).toHaveLength(0);
  await page.getByTestId("open-contextual-director").click();
  await expect(page).toHaveURL(new RegExp(`${SCENE_ID}\\?shotId=${SHOT_ID}&tool=director$`));
  await expect(page.getByTestId("shot-design-panel")).toHaveAttribute("data-shot-id", SHOT_ID);
  await expect(page.getByTestId("request-shot-director-suggestion")).toBeVisible();
  expect(writes()).toHaveLength(0);
  assertServerUnchanged();

  await page
    .getByLabel("导演要求", { exact: true })
    .fill("让人物更克制，先停顿再转头，镜头缓慢推进");
  await page.getByTestId("request-shot-director-suggestion").click();
  await expect(page.getByTestId("shot-director-suggestion-proposal")).toBeVisible();
  await expect(page.getByTestId("suggestion-model-evidence")).toContainText(
    "upstream/director-e2e",
  );
  await expect(page.getByTestId("suggestion-model-evidence")).toContainText("33333333");
  await expect(page.getByTestId("suggestion-old-image-prompt")).toHaveText(before.image);
  await expect(page.getByTestId("suggestion-new-image-prompt")).toHaveText(
    suggestion.suggested_image_prompt,
  );
  expect(writes()).toHaveLength(1);
  assertServerUnchanged();

  await page.getByTestId("apply-shot-director-suggestion").click();
  await expect(page.getByTestId("shot-design-dirty")).toBeVisible();
  await expect(page.getByLabel("图片提示词", { exact: true })).toHaveValue(
    suggestion.suggested_image_prompt,
  );
  expect(writes()).toHaveLength(2);
  expect(writes()[1]).toEqual({
    method: "POST",
    path: `/api/v1/projects/${PROJECT_ID}/director/turns/${suggestion.director_evidence.turn_id}/decision`,
    body: {
      expected_revision: 3,
      decision: "accept",
      accepted_operation_indices: [0],
    },
  });
  assertServerUnchanged();

  await page.getByTestId("save-shot-design").click();
  await expect(page.getByText("已保存设计（版本已递增）", { exact: true })).toBeVisible();
  await expect(page.getByTestId("shot-design-dirty")).toHaveCount(0);
  expect(writes()).toHaveLength(3);
  expect(writes()[2]).toEqual({
    method: "PATCH",
    path: `/api/v1/projects/${PROJECT_ID}/shots/${SHOT_ID}/design`,
    body: {
      expected_version: before.version,
      image_prompt: suggestion.suggested_image_prompt,
      video_prompt: suggestion.suggested_video_prompt,
      director_state: suggestion.suggested_director_state,
    },
  });
  expect(state.shotVersion).toBe(before.version + 1);
  expect(state.directorState).toEqual(suggestion.suggested_director_state);
  expect(state.proposals).toHaveLength(0);
  expect(state.revisions).toHaveLength(0);

  // Reopening reads the saved design; it must not request analysis or production.
  await page.reload();
  await expect(page.getByLabel("图片提示词", { exact: true })).toHaveValue(
    suggestion.suggested_image_prompt,
  );
  await expect(page.getByLabel("视频提示词", { exact: true })).toHaveValue(
    suggestion.suggested_video_prompt,
  );
  await expect(page.getByTestId("save-shot-design")).toBeDisabled();
  expect(writes()).toHaveLength(3);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("professional-workbench")).toBeVisible();
}
