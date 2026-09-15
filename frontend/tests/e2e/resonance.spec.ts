import { expect, test } from "@playwright/test";
import {
  PROJECT_ID,
  SCENE_ID,
  SHOT_ID,
  SECOND_SHOT_ID,
  installProfessionalMock,
} from "./professional-mocks";

test("spatial focus and group intent preserve the canonical write gates", async ({ page }) => {
  const state = await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await page.getByRole("button", { name: "展开镜头关系图" }).click();
  await page.getByRole("button", { name: "聚焦镜头 2", exact: true }).click();
  await expect(page.getByTestId("cinematic-canvas")).toHaveAttribute(
    "data-shot-id",
    SECOND_SHOT_ID,
  );
  await page.getByRole("button", { name: "展开镜头关系图" }).click();
  await page.getByRole("button", { name: "共同关注", exact: true }).click();
  await page.getByRole("button", { name: "共同关注镜头 1", exact: true }).click();
  await page.getByRole("button", { name: "共同关注镜头 2", exact: true }).click();
  await page.getByRole("textbox", { name: "此刻的创作意图" }).fill("让沉默更有力量");
  await page.getByRole("button", { name: "与导演讨论这个意图" }).click();
  await expect(page.getByRole("textbox", { name: "导演要求", exact: true })).toHaveValue(
    "参考本场景镜头 1、2，为当前镜头 2 提出建议：让沉默更有力量",
  );
  expect(
    state.editing.requests.filter(
      (request) =>
        ["POST", "PATCH", "DELETE"].includes(request.method) &&
        !request.path.endsWith("/workspace-state"),
    ),
  ).toEqual([]);
});

test("tether produces an editable intention without leaving the world", async ({ page }) => {
  await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await page.getByRole("button", { name: "展开镜头关系图" }).click();
  const first = await page.locator(`[data-world-shot="${SHOT_ID}"]`).boundingBox();
  const second = await page.locator(`[data-world-shot="${SECOND_SHOT_ID}"]`).boundingBox();
  expect(first).not.toBeNull();
  expect(second).not.toBeNull();
  await page.mouse.move(first!.x + first!.width / 2, first!.y + first!.height / 2);
  await page.mouse.down();
  await page.mouse.move(second!.x + second!.width / 2, second!.y + second!.height / 2, {
    steps: 10,
  });
  await page.mouse.up();
  await expect(page.getByRole("textbox", { name: "此刻的创作意图" })).toHaveValue(
    "让镜头 1 与镜头 2 的情绪和动作自然衔接。",
  );
  await expect(page.getByTestId("resonance-world")).toBeVisible();
  await page.getByRole("button", { name: "清除共同关注" }).click();
  await expect(page.locator(".rs-attention")).toHaveCount(0);
});

test("touch-size controls, keyboard focus and reduced motion at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await expect(page.getByTestId("resonance-intent")).toBeVisible();
  await page.getByRole("button", { name: "展开镜头关系图" }).focus();
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "聚焦镜头 2", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("cinematic-canvas")).toHaveAttribute(
    "data-shot-id",
    SECOND_SHOT_ID,
  );
  const layout = await page.evaluate(() => ({
    width: innerWidth,
    scroll: document.documentElement.scrollWidth,
    form: document.querySelector(".rs-intent")!.getBoundingClientRect().toJSON(),
    stage: document.querySelector(".rs-stage")!.getBoundingClientRect().toJSON(),
  }));
  expect(layout.scroll).toBeLessThanOrEqual(layout.width);
  expect(layout.form.bottom).toBeLessThanOrEqual(layout.stage.bottom);
  expect(layout.form.right).toBeLessThanOrEqual(layout.width);
  const send = await page.getByRole("button", { name: "与导演讨论这个意图" }).boundingBox();
  expect(send!.width).toBeGreaterThanOrEqual(44);
  expect(send!.height).toBeGreaterThanOrEqual(44);
});

test("portrait footage leaves the intention within the mobile first screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = await installProfessionalMock(page);
  state.formalKeyframeArtifactId = "portrait";
  await page.route("**/artifacts/portrait/content?**", (route) =>
    route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1600"><rect width="900" height="1600" fill="#28333c"/></svg>',
    }),
  );
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await expect(page.getByTestId("shot-keyframe")).toBeVisible();
  await expect
    .poll(() =>
      page
        .getByTestId("shot-keyframe")
        .evaluate((node) => (node as HTMLImageElement).naturalHeight),
    )
    .toBe(1600);
  const layout = await page.evaluate(() => ({
    viewport: innerHeight,
    image: document.querySelector('[data-testid="shot-keyframe"]')!.getBoundingClientRect().height,
    input: document.querySelector('[data-testid="resonance-intent"]')!.getBoundingClientRect()
      .bottom,
  }));
  expect(layout.image).toBeLessThanOrEqual(layout.viewport * 0.38 + 1);
  expect(layout.input).toBeLessThanOrEqual(layout.viewport);
});

test("contextual intent reaches the existing director endpoint once and errors stay truthful", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  const requests: Record<string, unknown>[] = [];
  await page.route(`**/director/shots/${SHOT_ID}/suggestion`, async (route) => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "导演暂时离线" }),
    });
  });
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await page.getByRole("textbox", { name: "此刻的创作意图" }).fill("先让她犹豫，再抬起头");
  await page.getByRole("button", { name: "与导演讨论这个意图" }).click();
  await page.getByTestId("request-shot-director-suggestion").click();
  await expect(page.getByTestId("shot-director-suggestion-panel")).toContainText("建议生成失败");
  await expect(page.locator(".rs-presence")).toHaveAttribute("data-status", "failed");
  expect(requests).toHaveLength(1);
  expect(requests[0]).toMatchObject({
    scene_id: SCENE_ID,
    shot_id: SHOT_ID,
    expected_shot_version: 1,
    user_instruction: "先让她犹豫，再抬起头",
  });
  expect(state.candidates).toHaveLength(0);
  expect(state.shotVersion).toBe(1);
  await page.getByTestId("director-sheet-close").click();
  await expect(page.getByTestId("director-companion")).toHaveAttribute("data-state", "failed");
});

test("enclosure selects spatial targets and Escape cancels a pending gesture", async ({ page }) => {
  await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await page.getByRole("button", { name: "展开镜头关系图" }).click();
  const map = await page.locator(".rs-map").boundingBox();
  const start = { x: map!.x + 2, y: map!.y + 5 };
  const end = { x: map!.x + map!.width * 0.68, y: map!.y + 145 };
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y, { steps: 8 });
  await page.mouse.up();
  await expect(page.locator(".rs-attention")).toHaveText("共同关注 · 镜 1 / 镜 2");
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y, { steps: 8 });
  await page.keyboard.press("Escape");
  await page.mouse.up();
  await expect(page.locator(".rs-enclosure")).toHaveCount(0);
  await expect(page.locator(".rs-attention")).toHaveCount(0);
  await expect(page.getByTestId("resonance-world")).toBeVisible();
});

test("keyboard can connect two moments without dragging or writing", async ({ page }) => {
  const state = await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await page.getByRole("button", { name: "展开镜头关系图" }).press("Enter");
  await page.getByRole("button", { name: "共同关注", exact: true }).press("Enter");
  await page.getByRole("button", { name: "共同关注镜头 2", exact: true }).press("Space");
  await page.getByRole("button", { name: "共同关注镜头 1", exact: true }).press("Space");
  await page.getByRole("button", { name: "衔接这两刻" }).press("Enter");
  await expect(page.getByRole("textbox", { name: "此刻的创作意图" })).toHaveValue(
    "让镜头 2 与镜头 1 的情绪和动作自然衔接。",
  );
  await expect(page.getByRole("textbox", { name: "此刻的创作意图" })).toBeFocused();
  expect(
    state.editing.requests.filter(
      (request) =>
        ["POST", "PATCH", "DELETE"].includes(request.method) &&
        !request.path.endsWith("/workspace-state"),
    ),
  ).toEqual([]);
});

test("director reveals the manual editor on demand and preserves its draft", async ({ page }) => {
  await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await page.getByTestId("director-companion").click();
  await expect(page.getByRole("textbox", { name: "导演要求", exact: true })).toBeVisible();
  await expect(page.getByLabel("图片提示词")).not.toBeVisible();
  await page.getByText("亲自调整这一刻", { exact: true }).click();
  await page.getByLabel("图片提示词").fill("保留她的沉默");
  await page.getByTestId("director-sheet-close").click();
  await page.getByTestId("director-companion").click();
  await expect(page.getByLabel("图片提示词")).toBeVisible();
  await expect(page.getByLabel("图片提示词")).toHaveValue("保留她的沉默");
  await expect(page.getByRole("button", { name: "保存设计", exact: true })).toBeEnabled();
});

test("changing shots isolates both the intention and Director entry", async ({ page }) => {
  await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await page.getByRole("textbox", { name: "此刻的创作意图" }).fill("只用于第一个镜头");
  await page.getByRole("button", { name: "与导演讨论这个意图" }).click();
  await expect(page.getByRole("textbox", { name: "导演要求", exact: true })).toHaveValue(
    "只用于第一个镜头",
  );
  await page.getByTestId("director-sheet-close").click();
  await page.getByRole("button", { name: "展开镜头关系图" }).click();
  await page.getByRole("button", { name: "聚焦镜头 2", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "此刻的创作意图" })).toHaveValue("");
  await page.getByTestId("director-companion").click();
  await expect(page.getByTestId("director-sidebar")).toHaveAttribute(
    "data-shot-id",
    SECOND_SHOT_ID,
  );
  await expect(page.getByRole("textbox", { name: "导演要求", exact: true })).toHaveValue("");
});

test("collaboration history is disclosed on demand without changing the current turn", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  await page.route("**/director/turns?**", async (route) =>
    route.fulfill({
      json: [
        {
          id: "turn-current",
          status: "thinking",
          intent_snapshot: { user_instruction: "保留当前构图" },
          request_summary: {},
          output_snapshot: {},
          response_summary: {},
          step_count: 1,
          revision: 1,
        },
        {
          id: "turn-earlier",
          status: "completed",
          intent_snapshot: { user_instruction: "上一轮的表演调整" },
          request_summary: {},
          output_snapshot: { change_summary: "让人物先看向窗外" },
          response_summary: {},
          step_count: 2,
          revision: 3,
        },
      ],
    }),
  );
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await page.getByTestId("director-companion").click();
  await expect(page.getByTestId("director-current-understanding")).toHaveText("保留当前构图");
  await expect(page.getByText("上一轮的表演调整", { exact: true })).not.toBeVisible();
  await page.getByText("此前的协作 · 1", { exact: true }).click();
  await expect(page.getByText("上一轮的表演调整", { exact: true })).toBeVisible();
  await expect(page.getByText("让人物先看向窗外", { exact: true })).toBeVisible();
  await expect(page.getByTestId("director-current-turn")).toHaveAttribute(
    "data-turn-id",
    "turn-current",
  );
  expect(
    state.editing.requests.filter(
      (request) =>
        ["POST", "PATCH", "DELETE"].includes(request.method) &&
        !request.path.endsWith("/workspace-state"),
    ),
  ).toEqual([]);
});

test("floating sheets leave the context controls reachable", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await page.getByTestId("context-dock-generate").click();
  const geometry = await page.evaluate(() => {
    return [".qc-scene-stage", ".rs-stage", ".qc-context-dock", ".qc-director-context-sheet"].map(
      (selector) => {
        const element = document.querySelector(selector)!;
        const style = getComputedStyle(element);
        return {
          selector,
          rect: element.getBoundingClientRect().toJSON(),
          display: style.display,
          position: style.position,
          gridRow: style.gridRow,
          rows: style.gridTemplateRows,
          bottom: style.bottom,
        };
      },
    );
  });
  await test.info().attach("sheet-layout", {
    body: JSON.stringify(geometry, null, 2),
    contentType: "application/json",
  });
  expect(geometry[3].rect.bottom).toBeLessThanOrEqual(geometry[1].rect.bottom);
  await page.getByTestId("context-dock-details").click();
  await expect(page.getByTestId("shot-details-sheet")).toBeVisible();
});

test.describe("touch and silent feedback", () => {
  test.use({ hasTouch: true, viewport: { width: 390, height: 844 } });
  test("tap equivalents select attention and status remains legible without animation or sound", async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await installProfessionalMock(page);
    await page.route("**/director/turns?**", async (route) =>
      route.fulfill({
        json: [
          {
            id: "turn-current",
            status: "thinking",
            intent_snapshot: { user_instruction: "让她先倾听" },
            request_summary: {},
            output_snapshot: {},
            response_summary: {},
            step_count: 1,
            revision: 1,
          },
        ],
      }),
    );
    await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
    await page.getByRole("button", { name: "展开镜头关系图" }).tap();
    await page.getByRole("button", { name: "共同关注", exact: true }).tap();
    await page.getByRole("button", { name: "共同关注镜头 1", exact: true }).tap();
    await expect(page.locator(".rs-attention")).toHaveText("共同关注 · 镜 1");
    await page.getByTestId("context-dock-director").tap();
    await expect(page.locator(".rs-presence")).toHaveAttribute("data-status", "thinking");
    expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(
      true,
    );
    await expect(page.getByRole("button", { name: "开启状态声音" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(
      await page
        .locator(".rs-presence-orbit")
        .evaluate((node) => getComputedStyle(node).animationName),
    ).toBe("none");
    await page.getByRole("button", { name: "开启状态声音" }).tap();
    await expect(page.getByRole("button", { name: "关闭状态声音" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
