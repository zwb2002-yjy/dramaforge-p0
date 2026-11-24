import { randomUUID } from "node:crypto";
import { test, expect } from "@playwright/test";
import { selectValue } from "../e2e/selectValue";

test("跨工作区检索并固定知识，重开项目仍读原版本，撤回后阻止重连", async ({ page }) => {
  const api = page.request;
  expect(
    (
      await api.post("/api/v1/auth/register", {
        data: {
          email: `library-${randomUUID()}@example.com`,
          password: "Synthetic-knowledge-2026",
          display_name: "知识试用",
        },
      })
    ).status(),
  ).toBe(201);
  const source = (await (await api.get("/api/v1/workspaces")).json())[0].id;
  async function headers(workspace: string) {
    return {
      "X-Workspace-Id": workspace,
      "X-CSRF-Token": (await (await api.get("/api/v1/auth/csrf")).json()).csrf_token,
    };
  }
  const space = await api.post("/api/v1/workspaces", {
    headers: await headers(source),
    data: { name: "作品工作区" },
  });
  expect(space.status()).toBe(201);
  const consumer = (await space.json()).id;
  const project = await api.post("/api/v1/projects", {
    headers: await headers(consumer),
    data: {
      workspace_id: consumer,
      name: "桥梁宣传",
      aspect_ratio: "16:9",
      work_type: "animation_promo",
    },
  });
  expect(project.status()).toBe(201);
  const pid = (await project.json()).id;
  const snapshot = {
    kind: "summary",
    title: "镇志里的桥",
    body: { text: "原刊记载有三座桥" },
    allowed_uses: ["research", "creation"],
  };
  const published = await api.post("/api/v1/knowledge/entries", {
    headers: await headers(source),
    data: { ...snapshot, operation: "publish", workspace_id: source, request_key: randomUUID() },
  });
  expect(published.status()).toBe(201);
  const receipt = await published.json();
  await page.addInitScript(
    (id) => sessionStorage.setItem("dramaforge.selected-workspace-id", id),
    consumer,
  );
  await page.goto("/knowledge");
  const keyword = page.getByRole("textbox", { name: "知识关键词" });
  await keyword.fill("没有匹配的合成条目");
  await page.getByRole("button", { name: "检索知识" }).click();
  await expect(page.getByText("未找到匹配的知识", { exact: true })).toBeVisible();
  await keyword.fill("三座桥");
  await keyword.press("Enter");
  await expect(page.getByRole("heading", { name: snapshot.title, exact: true })).toBeVisible();
  await page.goto(`/projects/${pid}/research`);
  const open = () => page.getByText("知识库引用", { exact: true }).click();
  await open();
  await page.getByRole("textbox", { name: "已发布知识关键词" }).fill("三座桥");
  await page.getByRole("button", { name: "检索已发布知识" }).click();
  await page.getByRole("button", { name: snapshot.title, exact: true }).click();
  const preview = page.getByRole("region", { name: "待引用知识" });
  await expect(preview).toContainText(snapshot.body.text);
  await selectValue(preview.getByRole("combobox", { name: "引用用途" }), "creation");
  const refPath = `/api/v1/projects/${pid}/knowledge-references`;
  expect(
    (await (await api.get(refPath, { headers: { "X-Workspace-Id": consumer } })).json()).total,
  ).toBe(0);
  await preview.getByRole("button", { name: "固定引用到项目" }).click();
  const refs = page.getByRole("list", { name: "本项目固定引用" });
  await expect(refs).toContainText("作品创作");
  await expect(refs).toContainText(snapshot.title);
  const newer = await api.post(`/api/v1/knowledge/entries/${receipt.entry_id}/revisions`, {
    headers: await headers(source),
    data: {
      title: "第二版桥志",
      body: { text: "后续补记五座桥" },
      allowed_uses: snapshot.allowed_uses,
      request_key: randomUUID(),
      expected_version: receipt.result_entry_version,
      operation: "publish",
    },
  });
  expect(newer.status()).toBe(201);
  await page.reload();
  await open();
  await expect(refs).toContainText(snapshot.title);
  await refs.getByText("查看固定内容").click();
  await expect(refs).toContainText(snapshot.body.text);
  await expect(refs).not.toContainText("五座桥");
  await refs.getByRole("button", { name: "解除引用" }).click();
  await expect(refs).toContainText("已解除");
  const reattached=page.waitForResponse(r=>new URL(r.url()).pathname.startsWith(refPath+"/") && r.request().method()==="PATCH");
  await refs.getByRole("button", { name: "重新引用" }).click();
  const reconnected=await reattached;
  expect(reconnected.status(),await reconnected.text()).toBe(200);
  await expect(refs).toContainText("可使用");
  const live = (await (await api.get(refPath, { headers: { "X-Workspace-Id": consumer } })).json())
    .items;
  expect(live).toHaveLength(1);
  expect(live[0].knowledge_revision_id).toBe(receipt.revision_id);
  expect(live[0].version).toBe(3);
  const withdraw = await api.post(`/api/v1/knowledge/entries/${receipt.entry_id}/withdraw`, {
    headers: await headers(source),
    data: {
      expected_version: (await newer.json()).result_entry_version,
      request_key: randomUUID(),
    },
  });
  expect(withdraw.status()).toBe(201);
  await page.reload();
  await open();
  await expect(refs).toContainText("知识已撤回");
  await refs.getByRole("button", { name: "解除引用" }).click();
  await expect(refs.getByRole("button", { name: "重新引用" })).toBeDisabled();
  expect(await (await api.get("http://institution-upstream-quality:9000/events")).json()).toEqual(
    [],
  );
});
