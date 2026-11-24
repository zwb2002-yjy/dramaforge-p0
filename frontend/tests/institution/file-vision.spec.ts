import { randomUUID, createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

test("owner previews a parsed file fragment and explicitly authorizes its use", async ({
  page,
}) => {
  test.setTimeout(90000);
  const r = await page.request.post("/api/v1/auth/register", {
    data: {
      email: `fragment-${randomUUID()}@example.com`,
      password: "Synthetic-vision-2026",
      display_name: "资料试用",
    },
  });
  expect(r.status()).toBe(201);
  const w = (await (await page.request.get("/api/v1/workspaces")).json())[0].id;
  const csrf = (await (await page.request.get("/api/v1/auth/csrf")).json()).csrf_token;
  const headers = { "X-Workspace-Id": w, "X-CSRF-Token": csrf };
  const project = await page.request.post("/api/v1/projects", {
    headers,
    data: { name: "资料画面", workspace_id: w, work_type: "animation_promo", aspect_ratio: "16:9" },
  });
  expect(project.status()).toBe(201);
  const p = (await project.json()).id;
  await page.addInitScript(
    (workspace) => sessionStorage.setItem("dramaforge.selected-workspace-id", workspace),
    w,
  );
  await page.goto(`/projects/${p}/files`);
  const bytes = await readFile(
    new URL("../../../fixtures/playback/blue-frame.png", import.meta.url),
  );
  const created = page.waitForResponse(
    (r) => r.request().method() === "POST" && new URL(r.url()).pathname.endsWith("/files"),
  );
  await page
    .locator('input[type="file"]')
    .setInputFiles({ name: "色卡.png", mimeType: "image/png", buffer: bytes });
  const upload = await created;
  expect(upload.status()).toBe(201);
  const revision = (await upload.json()).revision_id;
  const usePath = `/api/v1/projects/${p}/file-revisions/${revision}/source-use`;
  const readUse = async () => (await page.request.get(usePath, { headers })).json();
  const attach = page.getByRole("button", { name: "附到导演对话" }).first();
  await expect(attach).toBeVisible({ timeout: 45000 });
  const previewed = page.waitForResponse((r) =>
    new URL(r.url()).pathname.endsWith("/vision-preview"),
  );
  await attach.click();
  const preview = await previewed;
  expect(preview.status()).toBe(200);
  const url = new URL(preview.url());
  const fragment = url.pathname.split("/").at(-2);
  expect(url.searchParams.get("expected_content_hash")).toBe(
    createHash("sha256").update(bytes).digest("hex"),
  );
  await page
    .getByAltText("将随消息发送的资料片段")
    .evaluate((img: HTMLImageElement) => img.decode());
  expect((await readUse()).state).toBe("unreviewed");
  await page.getByText("来源与使用许可", { exact: true }).click();
  await page.getByRole("checkbox", { name: "外部模型处理" }).check();
  await page
    .getByRole("textbox", { name: "来源及授权依据" })
    .fill("自制色卡，允许外部模型读取所选画面");
  expect((await readUse()).state).toBe("unreviewed");
  await page.getByRole("button", { name: "保存使用许可" }).click();
  await expect.poll(async () => (await readUse()).allowed_uses).toEqual(["external_processing"]);
  await page.getByRole("textbox", { name: "给导演的想法" }).fill("这块色卡是什么颜色？");
  const submitted = page.waitForResponse(
    (r) => r.request().method() === "POST" && new URL(r.url()).pathname.endsWith("/messages"),
  );
  await page.getByRole("button", { name: "发送给导演" }).click();
  const response = await submitted;
  expect(response.request().postDataJSON().media_parts).toEqual([
    {
      kind: "file",
      file_revision_id: revision,
      source_fragment_id: fragment,
      expected_content_hash: url.searchParams.get("expected_content_hash"),
    },
  ]);
  expect(response.status()).toBe(422);
  expect((await response.json()).details.request_accepted).toBe(false);
  const events = await page.request.get("http://institution-upstream-quality:9000/events");
  expect(await events.json()).toEqual([]);
  await page.getByRole("button", { name: "移除附件" }).click();
  await expect(page.getByAltText("将随消息发送的资料片段")).toHaveCount(0);
});
