import { expect, test } from "@playwright/test";
import { installProfessionalMock, WORKSPACE_ID } from "./professional-mocks";

test("saved LLM connections switch explicitly and survive reload without rewriting credentials or media", async ({
  page,
}) => {
  await installProfessionalMock(page);
  const firstId = "litellm/connection-a/chat",
    secondId = "litellm/connection-b/chat";
  const connections = ["a", "b"].map((id) => ({
    id: `connection-${id}`,
    workspace_id: WORKSPACE_ID,
    provider_type: "litellm",
    protocol_profile: "openai_chat_v1",
    display_name: `LLM ${id.toUpperCase()}`,
    base_url: `https://${id}.example.test/v1`,
    enabled: true,
    credential_configured: true,
    credential_key_version: "v1",
    verification_status: "verified",
    connection_revision_id: `revision-${id}`,
  }));
  const slots = ["planning.brief", "planning.script", "planning.storyboard"];
  const media = { model_id: "binding:video", native_options: { duration: 8 }, enabled: false };
  let profile = {
    id: "profile",
    name: "默认",
    is_default: true,
    version: 3,
    bindings: {
      ...Object.fromEntries(slots.map((slot) => [slot, { model_id: firstId }])),
      "video.shot": media,
    },
  };
  const writes: Array<{ url: string; body: unknown }> = [];
  page.on("request", (request) => {
    const url = new URL(request.url()).pathname;
    if (url.startsWith("/api/") && request.method() !== "GET" && !url.endsWith("/workspace-state"))
      writes.push({ url, body: request.postDataJSON() });
  });
  await page.route("**/api/v1/provider-plugins", (route) =>
    route.fulfill({
      json: [
        {
          provider_type: "litellm",
          protocol_profile: "openai_chat_v1",
          kind: "text",
          display_name: "文本服务",
          implemented: true,
          models: [],
          capabilities: ["auth_models"],
          paid_capabilities: [],
        },
      ],
    }),
  );
  await page.route(`**/workspaces/${WORKSPACE_ID}/provider-connections`, (route) =>
    route.fulfill({ json: connections }),
  );
  for (const id of ["a", "b"]) {
    await page.route(`**/provider-connections/connection-${id}/probes`, (route) =>
      route.fulfill({
        json: [
          {
            probe_id: `probe-${id}`,
            status: "passed",
            capability: "auth_models",
            discovered_model_ids: ["chat"],
            connection_revision_id: `revision-${id}`,
            tested_at: "2026-10-08T00:00:00Z",
          },
        ],
      }),
    );
  }
  await page.route("**/api/v1/models", (route) =>
    route.fulfill({
      json: [firstId, secondId].map((id) => ({
        id,
        display_name: id,
        source: "workspace",
        available: true,
        capabilities: ["text.generate"],
      })),
    }),
  );
  await page.route(`**/workspaces/${WORKSPACE_ID}/model-profiles`, (route) =>
    route.fulfill({ json: [profile] }),
  );
  await page.route("**/model-profiles/profile", (route) => route.fulfill({ json: profile }));
  await page.route("**/model-profiles/profile/simple-mode", async (route) => {
    const input = route.request().postDataJSON();
    expect(input.expected_version).toBe(profile.version);
    profile = {
      ...profile,
      version: profile.version + 1,
      bindings: {
        ...profile.bindings,
        ...Object.fromEntries(slots.map((slot) => [slot, { model_id: input.llm_model_id }])),
      },
    };
    await route.fulfill({ json: profile });
  });
  await page.goto("/settings/models");
  await expect(page.getByRole("button", { name: "已启用 chat", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "管理 LLM B", exact: true }).click();
  await expect(page.getByLabel("服务地址")).toHaveValue("https://b.example.test/v1");
  await page.getByRole("button", { name: "启用 chat", exact: true }).click();
  await expect(page.getByRole("button", { name: "已启用 chat", exact: true })).toBeDisabled();
  await page.reload();
  await page.getByRole("button", { name: "管理 LLM B", exact: true }).click();
  await expect(page.getByRole("button", { name: "已启用 chat", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "管理 LLM A", exact: true }).click();
  await expect(page.getByLabel("服务地址")).toHaveValue("https://a.example.test/v1");
  await page.getByRole("button", { name: "启用 chat", exact: true }).click();
  await expect(page.getByRole("button", { name: "已启用 chat", exact: true })).toBeDisabled();
  expect(writes).toEqual([
    {
      url: `/api/v1/workspaces/${WORKSPACE_ID}/model-profiles/profile/simple-mode`,
      body: { llm_model_id: secondId, expected_version: 3 },
    },
    {
      url: `/api/v1/workspaces/${WORKSPACE_ID}/model-profiles/profile/simple-mode`,
      body: { llm_model_id: firstId, expected_version: 4 },
    },
  ]);
  expect(profile.bindings["video.shot"]).toEqual(media);
  await page.getByRole("button", { name: "添加 LLM 配置", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "添加 LLM 配置" });
  await expect(dialog.getByLabel("连接名称")).toHaveValue("");
  await expect(dialog.getByLabel("服务地址")).toHaveValue("");
  await expect(dialog.getByLabel("API Key", { exact: true })).toHaveValue("");
  await expect(dialog.getByRole("navigation")).toHaveCount(0);
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "已启用 chat", exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
    ),
  ).toBe(true);
});
