import { expect, test, type Page } from "@playwright/test";

import { PROJECT_ID, SCENE_ID } from "./professional-mocks";
import { installShotJourneyMock, JOURNEY_SHOT_IDS } from "./shot-journey-mocks";

type Journey = Awaited<ReturnType<typeof installShotJourneyMock>>;
const sceneUrl = `/projects/${PROJECT_ID}/scenes/${SCENE_ID}`;
const productionWrites = (state: Journey) =>
  state.requests.filter((item) =>
    /\/(executions|formal-keyframe|formal-video|review-decisions)$/.test(item.path),
  );

async function reviewCandidate(
  page: Page,
  state: Journey,
  index: number,
  stage: "image_keyframe" | "video",
) {
  const artifact = `journey-${index + 1}-${stage}`;
  const kind = stage === "video" ? "video_drift" : "identity";
  const candidate = page.getByTestId(`shot-candidate-${artifact}`);
  const before = productionWrites(state).length;
  await candidate.getByTestId(`shot-candidate-select-${artifact}`).click();
  await expect(page.getByTestId(`shot-candidate-preview-${artifact}`)).toBeVisible();
  expect(productionWrites(state)).toHaveLength(before);
  await expect(candidate.getByTestId(`shot-candidate-confirm-${artifact}`)).toHaveCount(0);
  await candidate.getByRole("button", { name: "就地审查", exact: true }).click();
  await expect(page.getByTestId("shot-inline-review")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/scenes/${SCENE_ID}`));
  await page.getByTestId(`review-request-evidence-${kind}`).click();
  const reason = page.getByLabel(
    `${stage === "video" ? "视频漂移审查" : "关键帧身份审查"}判断理由`,
  );
  await reason.fill(`镜头 ${index + 1} ${stage} 确认可用`);
  await expect(page.getByTestId(`review-approve-${kind}`)).toBeEnabled();
  await page.getByTestId(`review-approve-${kind}`).click();
  await expect(page.getByTestId("review-current-decision")).toHaveText("已通过");
  // Human approval is a separate fact; no Formal pointer changes yet.
  expect(
    stage === "video"
      ? state.shots[index].formal_video_artifact_id
      : state.shots[index].formal_keyframe_artifact_id,
  ).toBeNull();
  expect(
    productionWrites(state)
      .slice(before)
      .map((item) => item.path.split("/").at(-1)),
  ).toEqual(["review-decisions"]);
  await page.getByRole("button", { name: "返回候选", exact: true }).click();
  await expect(page.getByTestId("shot-strip")).toHaveAttribute(
    "data-selected-shot-id",
    JOURNEY_SHOT_IDS[index],
  );
  if ((await page.getByTestId("shot-candidate-tray").getAttribute("data-expanded")) === "false")
    await page.getByTestId("shot-candidate-tray").click();
  await page.getByTestId(`shot-candidate-confirm-${artifact}`).click();
  await expect(page.getByTestId("shot-candidate-success")).toContainText(
    stage === "video" ? "已设为正式视频" : "已设为正式画面",
  );
}

test("three Shots retain saved drafts through preflight, candidate, human review and explicit Formal", async ({
  page,
}) => {
  const state = await installShotJourneyMock(page);
  test.setTimeout(90_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`/projects/${PROJECT_ID}/scenes`);
  await page.getByRole("link", { name: "编辑镜头 1", exact: true }).click();
  await expect(page.getByTestId("shot-inspector")).toBeVisible({ timeout: 15_000 });
  for (let index = 0; index < 3; index += 1) {
    const shotId = JOURNEY_SHOT_IDS[index];
    if (index) await page.getByTestId(`shot-strip-card-${shotId}`).click();
    const inspector = page.getByTestId("shot-inspector");
    const writesBeforeEdit = productionWrites(state).length;
    await expect(inspector.getByTestId("shot-design-panel")).toHaveAttribute(
      "data-shot-id",
      shotId,
    );
    await inspector.getByLabel("画面描述").fill(`镜头 ${index + 1} 保存画面`);
    await inspector.getByTestId("shot-design-prompts").locator(":scope > summary").click();
    await inspector.getByLabel("图片提示词").fill(`saved frame ${index + 1}`);
    await inspector.getByLabel("视频提示词").fill(`saved motion ${index + 1}`);
    await page.getByTestId(`shot-strip-card-${JOURNEY_SHOT_IDS[(index + 1) % 3]}`).click();
    await expect(page.getByTestId("unsaved-changes-guard")).toBeVisible();
    await page.getByRole("button", { name: "返回保存" }).click();
    await expect(inspector.getByLabel("画面描述")).toHaveValue(`镜头 ${index + 1} 保存画面`);
    expect(productionWrites(state)).toHaveLength(writesBeforeEdit);
    await inspector.getByTestId("shot-primary-save").click();
    await expect(inspector.getByTestId("shot-design-message")).toHaveText("已保存。");
    expect(state.shots[index].version).toBe(3); // Canvas then design, each with its own optimistic version.
    await inspector.getByTestId("generate-keyframe").click();
    await expect(
      page.getByTestId(`shot-candidate-journey-${index + 1}-image_keyframe`),
    ).toBeVisible();
    await reviewCandidate(page, state, index, "image_keyframe");
    await page.getByTestId("generate-video").click();
    await expect(page.getByTestId(`shot-candidate-journey-${index + 1}-video`)).toBeVisible();
    await reviewCandidate(page, state, index, "video");
    expect(state.shots[index].version).toBe(5);
    await page.reload();
    await expect(page.getByTestId("shot-strip")).toHaveAttribute("data-selected-shot-id", shotId);
    await expect(inspector.getByLabel("画面描述")).toHaveValue(`镜头 ${index + 1} 保存画面`);
    await expect(page.getByTestId("shot-formal-output")).toBeVisible();
    expect(productionWrites(state)).toHaveLength((index + 1) * 6);
  }
  for (const [index, shot] of state.shots.entries()) {
    const writes = state.requests.filter((request) => request.path.includes(`/shots/${shot.id}/`));
    expect(
      writes
        .filter((item) => item.method === "PATCH")
        .map((item) => [item.path.split("/").at(-1), item.body.expected_version]),
    ).toEqual([
      ["canvas", 1],
      ["design", 2],
    ]);
    expect(
      writes
        .filter((item) => item.path.endsWith("/executions"))
        .map((item) => [item.body.stage, item.body.expected_shot_version]),
    ).toEqual([
      ["image_keyframe", 3],
      ["video", 4],
    ]);
    const plans = [...state.plans.values()].filter((plan) => plan.shotId === shot.id);
    expect(plans.map((plan) => plan.prompt)).toEqual([
      `saved frame ${index + 1}`,
      `saved motion ${index + 1}`,
    ]);
    expect(plans[1].firstFrame).toBe(`journey-${index + 1}-image_keyframe`);
  }
  expect(
    new Set(
      state.requests.filter((item) => item.path.endsWith("/executions")).map((item) => item.key),
    ).size,
  ).toBe(6);
  await page.getByRole("link", { name: "返回全片分镜总览" }).click();
  await expect(page.getByText("正式视频 3 / 3")).toBeVisible();
  await page.reload();
  await expect(page.getByText("正式视频 3 / 3")).toBeVisible();
  expect(productionWrites(state)).toHaveLength(18);
  expect(errors).toEqual([]);
});

test("a refused save retains the Shot draft and blocks implicit generation and switching", async ({
  page,
}) => {
  const state = await installShotJourneyMock(page);
  await page.goto(sceneUrl);
  state.failNextSave = true;
  await page.getByLabel("画面描述").fill("版本冲突也保留的草稿");
  await page.getByTestId("shot-primary-save").click();
  await expect(page.getByTestId("shot-design-message")).toContainText("保存失败");
  await expect(page.getByLabel("画面描述")).toHaveValue("版本冲突也保留的草稿");
  await expect(page.getByTestId("shot-primary-save")).toBeVisible();
  await page.getByTestId(`shot-strip-card-${JOURNEY_SHOT_IDS[1]}`).click();
  await expect(page.getByTestId("unsaved-changes-guard")).toBeVisible();
  await page.getByRole("button", { name: "返回保存" }).click();
  await expect(page.getByTestId("shot-strip")).toHaveAttribute(
    "data-selected-shot-id",
    JOURNEY_SHOT_IDS[0],
  );
  expect(state.shots[0].visual_description).toBe("镜头 1 原始画面");
  expect(productionWrites(state)).toEqual([]);
});

test("offline writes fail in place and reconnect never flushes a Save or generation", async ({
  page,
  context,
}) => {
  const state = await installShotJourneyMock(page);
  await page.goto(sceneUrl);
  let offline = false;
  await expect(page.getByTestId("generate-keyframe")).toBeEnabled();
  await page.route("**/api/**", (route) =>
    offline ? route.abort("internetdisconnected") : route.fallback(),
  );
  offline = true;
  await context.setOffline(true);
  await page.getByTestId("generate-keyframe").click();
  await expect(page.getByTestId("generate-keyframe")).toBeEnabled();
  await page.getByLabel("画面描述").fill("断网失败后保留，联网仍需显式保存");
  await page.getByTestId("shot-primary-save").click();
  await expect(page.getByTestId("shot-design-message")).toContainText("保存失败");
  await expect(page.getByLabel("画面描述")).toHaveValue("断网失败后保留，联网仍需显式保存");
  offline = false;
  await context.setOffline(false);
  await expect(page.getByTestId("shot-primary-save")).toBeEnabled();
  await expect(page.getByLabel("画面描述")).toHaveValue("断网失败后保留，联网仍需显式保存");
  expect(state.shots[0].version).toBe(1);
  expect(productionWrites(state)).toEqual([]);
  expect(state.requests.filter((item) => item.method === "PATCH")).toEqual([]);
  await page.getByTestId("shot-primary-save").click();
  await expect(page.getByTestId("shot-design-message")).toHaveText("已保存。");
  expect(state.shots[0].version).toBe(2);
  expect(productionWrites(state)).toEqual([]);
});

test("approval survives a refused Formal selection and recovery never regenerates the candidate", async ({
  page,
}) => {
  const state = await installShotJourneyMock(page);
  await page.goto(sceneUrl);
  await page.getByTestId("generate-keyframe").click();
  await page
    .getByTestId("shot-candidate-journey-1-image_keyframe")
    .getByRole("link", { name: "审查", exact: true })
    .click();
  await page.getByTestId("review-request-evidence-identity").click();
  await page.getByLabel("关键帧身份审查判断理由").fill("确认此候选身份正确");
  await expect(page.getByTestId("review-approve-and-formal-identity")).toBeEnabled();
  state.failNextFormal = true;
  await page.getByTestId("review-approve-and-formal-identity").click();
  await expect(page.getByTestId("review-decision-feedback")).toContainText("通过并设为正式失败");
  expect(state.candidates[JOURNEY_SHOT_IDS[0]][0].review_allowed).toBe(true);
  expect(state.shots[0].formal_keyframe_artifact_id).toBeNull();
  await page.reload();
  await expect(page.getByTestId("review-current-decision")).toHaveText("已通过");
  await page.getByTestId("review-approve-and-formal-identity").click();
  await expect(page.getByTestId("review-decision-feedback")).toContainText("已通过并设为正式");
  expect(state.shots[0].formal_keyframe_artifact_id).toBe("journey-1-image_keyframe");
  expect(state.requests.filter((item) => item.path.endsWith("/executions"))).toHaveLength(1);
  expect(state.requests.filter((item) => item.path.endsWith("/review-decisions"))).toHaveLength(1);
  expect(state.requests.filter((item) => item.path.endsWith("/formal-keyframe"))).toHaveLength(2);
});
