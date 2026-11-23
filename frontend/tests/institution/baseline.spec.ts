import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

// No route.fulfill or API mocks: persist through the application role, then
// let the resident dispatcher parse a synthetic source from real MinIO.
test("real project/source persistence, browser readback and owner isolation", async ({
  page,
  playwright,
}) => {
  const request = page.request;
  const suffix = randomUUID();
  const registration = await request.post("/api/v1/auth/register", {
    data: {
      email: `institution-${suffix}@example.com`,
      password: "Synthetic-quality-password-2026",
      display_name: "机构测试用户",
    },
  });
  expect(registration.status()).toBe(201);
  const csrf = await request.get("/api/v1/auth/csrf");
  expect(csrf.ok()).toBeTruthy();
  const { csrf_token: token } = await csrf.json();
  const workspaceResponse = await request.post("/api/v1/workspaces", {
    headers: { "X-CSRF-Token": token },
    data: { name: `机构测试空间 ${suffix}` },
  });
  expect(workspaceResponse.status()).toBe(201);
  const workspace = await workspaceResponse.json();
  const headers = { "X-CSRF-Token": token, "X-Workspace-Id": workspace.id };
  const name = `机构基线 ${suffix}`;
  const projectResponse = await request.post("/api/v1/projects", {
    headers,
    data: { workspace_id: workspace.id, name, aspect_ratio: "16:9", work_type: "animation_promo" },
  });
  expect(projectResponse.status()).toBe(201);
  const project = await projectResponse.json();
  const files = `/api/v1/projects/${project.id}/files`;
  const sourceText = "合成资料：示例古城的灯会每年举行。本段不含真实机构资料。";
  await page.goto("/");
  await page.getByRole("combobox", { name: "工作空间筛选" }).click();
  await page.getByRole("option", { name: workspace.name, exact: true }).click();
  await expect(page.getByText(name, { exact: true })).toBeVisible();
  await page.goto(`/projects/${project.id}/files`);
  const accepted = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === files && response.request().method() === "POST",
  );
  await page.locator('input[type="file"]').setInputFiles({
    name: "synthetic.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(sourceText),
  });
  const upload = await accepted;
  expect(upload.status()).toBe(201);
  const file = await upload.json();
  await expect(page.getByTestId("source-fragment").first()).toContainText(sourceText, {
    timeout: 45000,
  });
  const revisionRead = await request.get(
    `/api/v1/projects/${project.id}/file-revisions/${file.revision_id}`,
    { headers },
  );
  expect(revisionRead.ok()).toBeTruthy();
  const extracted = await revisionRead.json();
  expect(extracted.source.revision_id).toBe(file.revision_id);
  expect(extracted.extraction.extraction_schema_version).toBe(2);
  expect(extracted.extraction.coverage.complete).toBe(true);
  const fragmentsResponse = await request.get(
    `/api/v1/projects/${project.id}/extractions/${extracted.extraction.id}/fragments`,
    { headers },
  );
  expect(fragmentsResponse.ok()).toBeTruthy();
  const fragments = await fragmentsResponse.json();
  expect(fragments.items.map((item: { text_content: string }) => item.text_content)).toEqual([
    sourceText,
  ]);
  expect(fragments.items[0].locator.paragraph_start).toBe(0);
  await page.getByRole("link", { name: "引用此段进行研究" }).first().click();
  await expect(page.getByLabel("待引用原文")).toHaveText(sourceText);
  const note = "灯会是当地每年举行的活动。";
  await page.getByRole("textbox", { name: "内容", exact: true }).fill(note);
  await page.getByRole("button", { name: "保存研究条目" }).click();
  await expect(page.getByRole("heading", { name: note })).toBeVisible();
  await expect(page.getByLabel("引用来源")).toContainText(sourceText);
  const revised = "合成资料记载，古城每年都举办灯会。";
  await page.getByLabel("修正内容").fill(revised);
  await page.getByRole("button", { name: "保存修正为新版本" }).click();
  await expect(page.getByRole("heading", { name: revised })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: revised })).toBeVisible();
  await expect(page.getByLabel("引用来源")).toContainText(sourceText);
  await expect(page.getByRole("button", { name: "分析预览" })).toBeEnabled();
  await page.getByRole("button", { name: "查看版本 1", exact: true }).click();
  await expect(page.getByLabel("历史版本对照")).toContainText(note);
  await expect(page.getByLabel("历史版本对照")).toContainText(revised);
  await expect(page.getByLabel("历史版本对照").getByLabel("引用来源")).toHaveCount(2);
  await page.getByRole("button", { name: "恢复此版本为新版本" }).click();
  await expect(page.getByRole("heading", { name: note })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("引用来源")).toContainText(sourceText);
  await expect(page.getByText("版本 3", { exact: false }).first()).toBeVisible();

  const publications: unknown[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/v1/knowledge/entries" && r.method() === "POST")
      publications.push(r.postDataJSON());
  });
  await page.getByRole("button", { name: "预览发布为知识" }).click();
  const preview = page.getByRole("dialog", { name: "知识发布预览" });
  await expect(preview).toContainText("所有工作区");
  await expect(preview).toContainText(note);
  await expect(preview).not.toContainText(sourceText);
  await preview.getByRole("button", { name: "取消" }).click();
  expect(publications).toHaveLength(0);
  const grant = await request.put(
    `/api/v1/projects/${project.id}/file-revisions/${file.revision_id}/source-use`,
    {
      headers: {
        ...headers,
        "X-CSRF-Token": (await (await request.get("/api/v1/auth/csrf")).json()).csrf_token,
      },
      data: {
        expected_version: 0,
        request_key: randomUUID(),
        state: "declared",
        allowed_uses: ["research"],
        statement: "合成资料用于研究",
      },
    },
  );
  expect(grant.status(), await grant.text()).toBe(200);
  await page.getByRole("button", { name: "预览发布为知识" }).click();
  await preview.getByRole("checkbox", { name: "导出交付" }).check();
  const posted = () =>
    page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/api/v1/knowledge/entries" &&
        r.request().method() === "POST",
    );
  const rejected = posted();
  await preview.getByRole("button", { name: "确认发布" }).click();
  expect((await rejected).status()).toBe(422);
  await expect(preview).toContainText("研究来源未允许本次用途");
  await preview.getByRole("checkbox", { name: "导出交付" }).uncheck();
  const acceptedKnowledge = posted();
  await preview.getByRole("button", { name: "确认发布" }).click();
  const published = await acceptedKnowledge;
  expect(published.status()).toBe(201);
  await expect(preview).toBeHidden();
  expect(publications).toHaveLength(2);
  const knowledge = await published.json();
  await page.goto("/knowledge");
  await expect(page.getByRole("heading", { name: note, exact: true })).toBeVisible();
  const versions = await request.get(`/api/v1/knowledge/entries/${knowledge.entry_id}/revisions`, {
    headers,
  });
  expect(versions.ok()).toBeTruthy();
  const [view] = (await versions.json()).items;
  expect(view.body.text).toEqual(note);
  expect(view.allowed_uses).toEqual(["research"]);
  expect(view.shared_content_state).toEqual("complete");
  expect(JSON.stringify(view)).not.toContain(file.revision_id);

  const other = await playwright.request.newContext({ baseURL: "http://127.0.0.1:4173" });
  try {
    const response = await other.post("/api/v1/auth/register", {
      data: {
        email: `other-${suffix}@example.com`,
        password: "Other-synthetic-password-2026",
        display_name: "另一个用户",
      },
    });
    expect(response.status()).toBe(201);
    const denied = await other.get(files, { headers: { "X-Workspace-Id": workspace.id } });
    expect(denied.status()).toBe(404);
    // A valid workspace owned by the attacker must not unlock foreign project
    // records, source text or stored originals by supplying their identifiers.
    const otherWorkspacesResponse = await other.get("/api/v1/workspaces");
    expect(otherWorkspacesResponse.ok()).toBeTruthy();
    const [otherWorkspace] = await otherWorkspacesResponse.json();
    expect(otherWorkspace.id).toBeTruthy();
    for (const path of [
      files,
      `/api/v1/projects/${project.id}/file-revisions/${file.revision_id}`,
      `/api/v1/projects/${project.id}/file-revisions/${file.revision_id}/original`,
    ]) {
      const inaccessible = await other.get(path, {
        headers: { "X-Workspace-Id": otherWorkspace.id },
      });
      expect(inaccessible.status()).toBe(404);
      expect(await inaccessible.text()).not.toContain(sourceText);
    }
  } finally {
    await other.dispose();
  }
  const upstream = await request.get("http://institution-upstream-quality:9000/events");
  expect(upstream.ok()).toBeTruthy();
  expect(await upstream.json()).toEqual([]);
});
