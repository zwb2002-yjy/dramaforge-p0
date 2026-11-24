import { randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import { selectValue } from "../e2e/selectValue";

async function register(page: Page) {
  const response = await page.request.post("/api/v1/auth/register", {
    data: {
      email: `intent-${randomUUID()}@example.com`,
      password: "Synthetic-project-password-2026",
      display_name: "机构项目测试",
    },
  });
  expect(response.status()).toBe(201);
  const workspaces = await page.request.get("/api/v1/workspaces");
  expect(workspaces.ok()).toBeTruthy();
  return (await workspaces.json())[0].id as string;
}

async function noModelCalls(page: Page) {
  const result = await page.request.get("http://institution-upstream-quality:9000/events");
  expect(result.ok()).toBeTruthy();
  expect(await result.json()).toEqual([]);
}

for (const [kind, label, episodes] of [
  ["animation_promo", "动画宣传片", null],
  ["single_comic", "单集漫剧", 1],
  ["serial_comic", "多集连续漫剧", 3],
] as const) {
  test(`${label}: create, preview, confirm and reload real project intent`, async ({ page }) => {
    await register(page);
    const name = `${label}-${randomUUID().slice(0, 8)}`;
    await page.goto("/?create=true");
    await expect(page.getByRole("textbox", { name: "项目名", exact: true })).toBeEnabled();
    await page.getByRole("textbox", { name: "项目名", exact: true }).fill(name);
    await selectValue(page.getByRole("combobox", { name: "作品类型", exact: true }), kind);
    await page.getByRole("button", { name: "创作目标与计划（可选）" }).click();
    await page.getByRole("textbox", { name: "想做什么" }).fill("介绍地方节庆文化");
    await page.getByRole("textbox", { name: "给谁看" }).fill("社区居民");
    await page.getByRole("textbox", { name: "目标总时长", exact: true }).fill("60");
    if (episodes !== null)
      await page.getByRole("textbox", { name: "计划集数" }).fill(String(episodes));
    const creating = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/v1/projects" &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "创建并进入工作台" }).click();
    const response = await creating;
    expect(response.status()).toBe(201);
    const created = await response.json();
    expect(created.work_type).toBe(kind);
    expect(created.creative_goal).toBe("介绍地方节庆文化");
    expect(created.audience).toBe("社区居民");
    expect(typeof created.planned_duration_seconds).toBe("string");
    expect(Number(created.planned_duration_seconds)).toBe(60);
    expect(created.planned_episode_count).toBe(episodes);
    await expect(page).toHaveURL(new RegExp(`/projects/${created.id}/?$`));
    await expect(page.getByRole("region", { name: "项目概览" })).toContainText("介绍地方节庆文化");
    await expect(page.getByRole("textbox", { name: "给导演的想法" })).toBeVisible();
    // An empty project already has a direction; the first script remains a proposal until Apply.
    await page.getByRole("button", { name: "创作方向", exact: true }).click();
    const direction = "用祖孙两代讲述元宵灯会，只取可核对的地方习俗。";
    await page.getByRole("textbox", { name: "创作方向", exact: true }).fill(direction);
    await page.getByRole("button", { name: "保存创作方向" }).click();
    await expect(page.getByText("创作方向已保存。")).toBeVisible();
    await page
      .getByRole("navigation", { name: "创作导航" })
      .getByRole("link", { name: "内容", exact: true })
      .click();
    await expect(page.getByRole("textbox", { name: "给导演的想法" })).toBeVisible();
    const formal = async () => {
      const result = await page.request.get(`/api/v1/projects/${created.id}/script`, {
        headers: { "X-Workspace-Id": created.workspace_id },
      });
      expect(result.ok()).toBeTruthy();
      return result.json();
    };
    let firstEpisode: unknown;
    for (const episode of kind === "serial_comic" ? [1, 2] : [1]) {
      const title = episode === 1 ? "点灯" : "送灯";
      const draft = `# 第 ${episode} 集 — ${title}
## 场景 1 — 河岸 / 夜间
祖孙走向河岸。
### 镜头 1 — 中景
画面：孙女提起彩灯
对白：这盏灯是谁做的？`;
      await page.getByLabel("故事方向").fill("从古城灯会开始讲述。");
      await page.getByLabel("剧本文本").fill(draft);
      await page.getByTestId("story-proposal-create").click();
      await expect(page.getByTestId("story-proposal-preview")).toBeVisible();
      expect((await formal()).episodes).toHaveLength(episode - 1);
      await page.getByTestId("story-proposal-apply-all").click();
      await expect.poll(async () => (await formal()).episodes.length).toBe(episode);
      await page.reload();
      await expect(page.getByTestId("project-script-page")).toBeVisible();
      const saved = await formal();
      expect(saved.episodes[episode - 1].episode_number).toBe(episode);
      const scene = saved.episodes[episode - 1].scenes[0];
      expect(scene.shot_count).toBe(1);
      expect(saved.episodes[0].title).toBe("点灯");
      if (episode === 1) firstEpisode = saved.episodes[0];
      else expect(saved.episodes[0]).toEqual(firstEpisode);
      if (kind !== "serial_comic" || episode === 2) {
        await page.getByRole("button", { name: `打开第 ${episode} 集第 1 场分镜` }).click();
        await expect(page).toHaveURL(new RegExp(`/projects/${created.id}/scenes/${scene.id}`));
        await expect(page.getByTestId("scene-workspace")).toBeVisible();
        await page.goto(`/projects/${created.id}/edit`);
        if (kind === "serial_comic") {
          await expect(page.getByTestId("create-edit-session")).toBeDisabled();
          await page.getByRole("combobox", { name: "剪辑范围" }).click();
          await page.getByRole("option", { name: "第 2 集 · 送灯" }).click();
        }
        const creatingEdit = page.waitForResponse(
          (response) =>
            response.request().method() === "POST" &&
            new URL(response.url()).pathname === `/api/v1/projects/${created.id}/edit-sessions`,
        );
        await page.getByTestId("create-edit-session").click();
        const editResponse = await creatingEdit;
        expect(editResponse.status()).toBe(201);
        const edit = await editResponse.json();
        expect(edit.episode_id).toBe(
          kind === "animation_promo" ? null : saved.episodes[episode - 1].id,
        );
        await expect(page.getByTestId("edit-session-editor")).toBeVisible();
        await expect(page.getByTestId("export-final-film")).toBeDisabled();
        await page.reload();
        await expect(page.getByTestId("editing-workspace")).toHaveAttribute(
          "data-session-id",
          edit.id,
        );
      }
    }
    await page.goto("/");
    const card = page.getByRole("article", { name, exact: true });
    await expect(card).toContainText(label);
    await card.getByRole("button", { name: `更多操作 ${name}` }).click();
    await page.getByRole("menuitem", { name: "编辑项目", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: `编辑项目「${name}」` });
    await expect(dialog.getByRole("textbox", { name: "想做什么" })).toHaveValue("介绍地方节庆文化");
    const patches: string[] = [];
    page.on("request", (request) => {
      if (
        request.method() === "PATCH" &&
        new URL(request.url()).pathname === `/api/v1/projects/${created.id}`
      )
        patches.push(request.url());
    });
    await dialog.getByRole("textbox", { name: "想做什么" }).fill("介绍节庆文化与传统技艺");
    await dialog.getByRole("button", { name: "预览修改" }).click();
    await expect(dialog.getByRole("region", { name: "项目修改预览" })).toBeVisible();
    expect(patches).toHaveLength(0);
    await dialog.getByRole("button", { name: "确认保存" }).click();
    await expect(dialog).toHaveCount(0);
    expect(patches).toHaveLength(1);
    const saved = await page.request.get(`/api/v1/projects/${created.id}`, {
      headers: { "X-Workspace-Id": created.workspace_id },
    });
    expect(saved.ok()).toBeTruthy();
    expect(await saved.json()).toMatchObject({
      version: 2,
      work_type: kind,
      creative_goal: "介绍节庆文化与传统技艺",
    });
    await page.reload();
    await expect(page.getByRole("article", { name, exact: true })).toContainText(label);
    await noModelCalls(page);
  });
}

test("real two-episode content blocks single-comic conversion before save", async ({ page }) => {
  const workspace = await register(page);
  const csrf = await page.request.get("/api/v1/auth/csrf");
  const headers = { "X-Workspace-Id": workspace, "X-CSRF-Token": (await csrf.json()).csrf_token };
  const createdResponse = await page.request.post("/api/v1/projects", {
    headers,
    data: {
      workspace_id: workspace,
      name: `分集保护-${randomUUID().slice(0, 8)}`,
      aspect_ratio: "16:9",
      work_type: "serial_comic",
      planned_episode_count: 2,
    },
  });
  expect(createdResponse.status()).toBe(201);
  const created = await createdResponse.json();
  for (const number of [1, 2]) {
    const imported = await page.request.post(`/api/v1/projects/${created.id}/scripts/import`, {
      headers,
      data: {
        filename: `episode-${number}.md`,
        text: `# Episode ${number} — Synthetic\n## Scene 1 — Square / day\nSynthetic\n### Shot 1 — medium\nvisual: Local scene\ndialogue: Hello\n`,
      },
    });
    expect(imported.ok()).toBeTruthy();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: `更多操作 ${created.name}` }).click();
  await page.getByRole("menuitem", { name: "编辑项目", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: `编辑项目「${created.name}」` });
  await expect(dialog.getByRole("combobox", { name: "作品类型" })).toBeEnabled();
  await selectValue(dialog.getByRole("combobox", { name: "作品类型" }), "single_comic");
  await dialog.getByRole("textbox", { name: "计划集数" }).fill("1");
  await dialog.getByRole("button", { name: "预览修改" }).click();
  await expect(dialog.getByRole("alert")).toContainText("现有分集超过新的作品计划");
  await expect(dialog.getByRole("button", { name: "确认保存" })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const current = await page.request.get(`/api/v1/projects/${created.id}`, { headers });
  expect(await current.json()).toMatchObject({
    version: 1,
    work_type: "serial_comic",
    planned_episode_count: 2,
  });
  await noModelCalls(page);
});
