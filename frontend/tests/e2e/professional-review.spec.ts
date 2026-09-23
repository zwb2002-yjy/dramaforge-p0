import { expect, test } from "@playwright/test";
import { PROJECT_ID, SHOT_ID, installProfessionalMock } from "./professional-mocks";

test("review workspace persists time and image-region annotations without changing production", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  state.formalKeyframeArtifactId = "artifact-keyframe";
  state.formalVideoArtifactId = "artifact-video";
  const version = state.shotVersion;
  await page.route(`**/shots/${SHOT_ID}/workbench`, (route) =>
    route.fulfill({
      json: {
        shot: {
          id: SHOT_ID,
          version,
          formal_keyframe_artifact_id: state.formalKeyframeArtifactId,
          formal_video_artifact_id: state.formalVideoArtifactId,
          duration_seconds: "5",
        },
        candidates: [],
      },
    }),
  );
  await page.goto(`/projects/${PROJECT_ID}/review`);
  await expect(page.getByTestId("review-workspace")).toBeVisible();
  // The mock does not provide decodable video. Wait for its failure before
  // supplying deterministic metadata, otherwise a late native error races it.
  await expect(page.getByRole("alert").filter({ hasText: "无法加载正式视频" })).toBeVisible();
  await expect(page.getByRole("button", { name: "保存视频批注" })).toBeDisabled();
  const player = page.getByLabel("正式视频审片播放器");
  await player.evaluate((element) => {
    element.removeAttribute("src");
    (element as HTMLVideoElement).load();
    Object.defineProperty(element, "duration", { configurable: true, value: 5 });
    element.dispatchEvent(new Event("loadedmetadata"));
  });
  await page.getByLabel("批注说明").fill("转头时人物身份漂移");
  await page.getByLabel("批注类型").selectOption("range");
  await page.getByLabel("批注开始时间").fill("1.2");
  await page.getByLabel("批注结束时间").fill("2.5");
  expect(state.annotations).toHaveLength(0);
  await page.getByRole("button", { name: "保存视频批注" }).click();
  await expect.poll(() => state.annotations.length).toBe(1);
  expect(state.annotations[0]).toMatchObject({
    target_kind: "video_time",
    time_start: "1.2",
    time_end: "2.5",
  });
  await expect(page.getByLabel("批注说明")).toHaveValue("");
  await page.getByLabel("批注说明").fill("右手区域曝光过曝");
  await page.getByRole("img", { name: "review target" }).evaluate((element) => {
    const svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450"><rect width="800" height="450" fill="gray"/></svg>';
    (element as HTMLImageElement).src = `data:image/svg+xml,${encodeURIComponent(svg)}`;
  });
  await expect
    .poll(() =>
      page
        .getByRole("img", { name: "review target" })
        .evaluate((element) => (element as HTMLImageElement).naturalWidth),
    )
    .toBe(800);
  const canvas = page.getByTestId("media-review-canvas");
  await canvas.scrollIntoViewIfNeeded();
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.6);
  await page.mouse.up();
  await expect.poll(() => state.annotations.length).toBe(2);
  expect(state.annotations[1].target_kind).toBe("image_region");
  expect(Number(state.annotations[1].width)).toBeCloseTo(0.3, 1);
  await expect(page.getByTestId("review-annotation-list")).toContainText("右手区域曝光过曝");
  expect(state.shotVersion).toBe(version);
});

test("repair preview requires explicit execution and explicit completion", async ({ page }) => {
  await installProfessionalMock(page);
  const repairId = "44444444-4444-4444-8444-444444444444";
  const base = `/api/v1/projects/${PROJECT_ID}/shots/${SHOT_ID}`;
  const writes: Array<{ path: string; body: Record<string, unknown> }> = [];
  let repair: Record<string, unknown> = {
    id: repairId,
    shot_id: SHOT_ID,
    option: "rerun_video",
    plan_hash: "a".repeat(64),
    plan_schema_version: 1,
    annotation_ids: [],
    source_formal_artifact_id: "artifact-video",
    closed_reason: null,
    created_at: "2026-09-22T00:00:00Z",
    next_action: "execute_step",
    next_step_ordinal: 1,
    steps: [],
  };

  await page.route(`**${base}/repair-plan`, (route) =>
    route.fulfill({
      json: {
        shot_id: SHOT_ID,
        repair_options: ["rerun_video"],
        suggested_option: "rerun_video",
        affected_nodes: ["video"],
        retained_assets: ["artifact-keyframe"],
        expected_rerun_scope: "video_only",
        annotation_count: 1,
        annotation_ids: [],
        plan_hash: "a".repeat(64),
        plan_schema_version: 1,
        steps: ["video_rerun", "video_review"],
        cost_estimate_note: "执行前需显式确认实际模型与费用。",
      },
    }),
  );
  await page.route(`**${base}/repairs**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const body = request.postDataJSON() as Record<string, unknown> | null;
    if (method === "GET") {
      await route.fulfill({ json: path.endsWith(repairId) ? repair : [repair] });
      return;
    }
    writes.push({ path, body: body ?? {} });
    if (path.endsWith("/step-plan")) {
      await route.fulfill({
        json: {
          repair_id: repairId,
          step_ordinal: 1,
          stage: "video_rerun",
          plan: {
            plan_fingerprint: "b".repeat(64),
            project_id: PROJECT_ID,
            shot_id: SHOT_ID,
            stage: "video",
            prompt: "使用已确认关键帧重跑视频",
            mode_id: "explicit_binding",
            resolved_model: {
              resolved_model_id: "provider/model-b",
              status: "RESOLVED",
              source: "project_profile",
              provider_model_binding_id: "binding-1",
              capability: "video.image_to_video",
            },
            capability: "video.image_to_video",
            planned_references: [],
            capability_gaps: [],
            accepted_approximations: [],
          },
        },
      });
      return;
    }
    if (path.endsWith("/steps")) {
      repair = {
        ...repair,
        next_action: "ready_to_close",
        next_step_ordinal: null,
        steps: [
          {
            id: "55555555-5555-4555-8555-555555555555",
            ordinal: 1,
            stage: "video_rerun",
            plan_fingerprint: "b".repeat(64),
            command_key: body?.idempotency_key,
            node_run_id: "66666666-6666-4666-8666-666666666666",
            node_run_status: "completed",
            node_run_error_code: null,
            result_artifact_id: "candidate-video-repair",
            confirmed_at: "2026-09-22T00:01:00Z",
            adopted_artifact_id: "candidate-video-repair",
            review_decision_id: "77777777-7777-4777-8666-777777777777",
            next_action: "adopted",
          },
        ],
      };
      await route.fulfill({
        json: {
          node_run_id: "66666666-6666-4666-8666-666666666666",
          status: "queued",
          repair_option: "rerun_video",
          repair_id: repairId,
          step_ordinal: 1,
          next_action: "wait",
        },
      });
      return;
    }
    if (path.endsWith("/close")) {
      repair = { ...repair, closed_reason: "completed", next_action: "closed" };
      await route.fulfill({ json: repair });
      return;
    }
    await route.fallback();
  });

  await page.goto(`/projects/${PROJECT_ID}/review`);
  await page.getByTestId("review-open-repair").click();
  await expect(page.getByTestId("repair-active")).toHaveAttribute(
    "data-next-action",
    "execute_step",
  );
  await page.getByTestId("repair-preview-step").click();
  await expect(page.getByTestId("repair-step-preview")).toContainText("生成视频候选");
  await page.getByRole("checkbox", { name: /我已核对本步实际模型/ }).check();
  await page.getByTestId("repair-execute-step").click();
  await expect(page.getByTestId("repair-ready-to-close")).toBeVisible();
  await page.getByTestId("repair-complete").click();
  await expect(page.getByTestId("repair-history")).toContainText("历史修复（1）");

  expect(writes.map((write) => write.path)).toEqual([
    `${base}/repairs/${repairId}/step-plan`,
    `${base}/repairs/${repairId}/steps`,
    `${base}/repairs/${repairId}/close`,
  ]);
  expect(writes[1]?.body).toMatchObject({
    expected_step_ordinal: 1,
    expected_plan_fingerprint: "b".repeat(64),
    accept_approximations: false,
  });
  expect(writes[2]?.body).toEqual({ reason: "completed" });
});
