import { expect, test, type Page } from "@playwright/test";
import {
  installProfessionalMock,
  PROJECT_ID,
  WORKSPACE_ID,
  SCENE_ID,
  SHOT_ID,
} from "./professional-mocks";

async function setupProviders(page: Page) {
  await installProfessionalMock(page);
  const writes: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (
      path.startsWith("/api/") &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method()) &&
      !path.endsWith("/workspace-state")
    )
      writes.push(path);
  });
  const model = {
    catalog_entry_id: "catalog-fixture",
    capability_manifest_hash: "hash-fixture",
    model_id: "fixture-image-v2",
    display_name: "Fixture Image",
    media_type: "image",
    model_revision: "v2",
    lifecycle: "active",
    catalog_source: "official_static",
    capabilities: ["image.generate"],
    option_schema: {},
    capability_summary: {
      media_kind: "image",
      accepts_text_only: true,
      product_text_only: true,
      accepts: { reference_image: true },
      product_open: { reference_image: true },
      limits: { reference_image: 1 },
    },
  };
  const plugin = {
    provider_type: "fixture",
    protocol_profile: "fixture-v1",
    display_name: "Fixture Provider",
    default_base_url: "https://fixture.invalid",
    kind: "media",
    implemented: true,
    paid_capabilities: ["image_t2i"],
    capabilities: ["auth_models", "image_t2i"],
    model_list_path: "/models",
    models: [model],
  };
  const connection = {
    id: "connection-fixture",
    workspace_id: WORKSPACE_ID,
    provider_type: plugin.provider_type,
    display_name: plugin.display_name,
    base_url: "https://saved.invalid",
    protocol_profile: plugin.protocol_profile,
    enabled: true,
    credential_configured: true,
    credential_key_version: "v1",
    verification_status: "verified",
    verified_at: null,
    connection_revision_id: "fixture-revision",
  };
  await page.route("**/api/v1/provider-plugins", (route) => route.fulfill({ json: [plugin] }));
  await page.route(`**/api/v1/workspaces/${WORKSPACE_ID}/projects`, (route) =>
    route.fulfill({
      json: [
        {
          id: PROJECT_ID,
          workspace_id: WORKSPACE_ID,
          name: "供应商回归作品",
          stage: "production",
          aspect_ratio: "9:16",
        },
      ],
    }),
  );
  await page.route(`**/api/v1/workspaces/${WORKSPACE_ID}/provider-connections`, (route) =>
    route.fulfill({ json: [connection] }),
  );
  await page.route(
    `**/api/v1/workspaces/${WORKSPACE_ID}/provider-connections/connection-fixture/probes`,
    (route) => route.fulfill({ status: 503, json: { detail: "mock evidence read unavailable" } }),
  );
  await page.route(
    `**/api/v1/workspaces/${WORKSPACE_ID}/provider-connections/connection-fixture/model-bindings`,
    (route) => route.fulfill({ json: [] }),
  );
  await page.route("**/api/v1/model-slots", (route) =>
    route.fulfill({
      json: [
        {
          id: "visual.keyframe",
          display_name: "镜头关键帧",
          capabilities: ["image.generate"],
          description: "",
          p0_scope: true,
        },
        {
          id: "video.shot",
          display_name: "镜头视频",
          capabilities: ["video.image_to_video"],
          description: "",
          p0_scope: true,
        },
      ],
    }),
  );
  await page.route(`**/api/v1/projects/${PROJECT_ID}/model-bindings/effective`, (route) =>
    route.fulfill({
      json: [
        {
          slot: "visual.keyframe",
          capability: "image.generate",
          model_id: "fixture/exact-image-v2",
          source: "workspace_profile",
          profile_id: "profile-fixture",
          profile_version: 3,
          native_options: {},
        },
      ],
    }),
  );
  await page.route(`**/api/v1/projects/${PROJECT_ID}/provider-bindings`, (route) =>
    route.fulfill({ json: [] }),
  );
  return { writes, model, connection };
}

test("text service owns its URL and key and its discovered model can be activated for the workspace", async ({
  page,
}) => {
  const { connection } = await setupProviders(page);
  const textConnection = {
    ...connection,
    id: "text-connection",
    display_name: "文本服务",
    provider_type: "litellm",
    protocol_profile: "openai_chat_v1",
    base_url: "https://my-text.invalid/v1",
  };
  const modelId = `litellm/${textConnection.id}/my-chat`;
  const creates: Record<string, unknown>[] = [];
  const saves: Record<string, unknown>[] = [];
  let connected = false;
  let discovered = false;
  await page.route("**/api/v1/provider-plugins", (route) =>
    route.fulfill({
      json: [
        {
          provider_type: "litellm",
          protocol_profile: "openai_chat_v1",
          display_name: "LiteLLM",
          default_base_url: "http://litellm:4000",
          implemented: true,
          kind: "text",
          models: [],
          paid_capabilities: [],
          capabilities: ["auth_models"],
        },
      ],
    }),
  );
  await page.route(`**/api/v1/workspaces/${WORKSPACE_ID}/provider-connections`, async (route) => {
    if (route.request().method() === "POST") {
      creates.push(route.request().postDataJSON());
      connected = true;
      await route.fulfill({ status: 201, json: textConnection });
    } else await route.fulfill({ json: connected ? [connection, textConnection] : [connection] });
  });
  const catalog = {
    probe_id: "text-probe",
    capability: "auth_models",
    status: "passed",
    discovered_model_ids: ["my-chat"],
    connection_revision_id: "fixture-revision",
  };
  await page.route(`**/provider-connections/text-connection/probes`, async (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toEqual({ capability: "auth_models" });
      discovered = true;
      await route.fulfill({ json: catalog });
    } else await route.fulfill({ json: discovered ? [catalog] : [] });
  });
  await page.route("**/api/v1/models", (route) =>
    route.fulfill({
      json: discovered
        ? [
            {
              id: modelId,
              display_name: "my-chat · 文本服务",
              source: "workspace",
              capabilities: ["text.generate"],
              available: true,
            },
          ]
        : [],
    }),
  );
  let profile: Record<string, unknown> | null = null;
  await page.route(`**/workspaces/${WORKSPACE_ID}/model-profiles`, async (route) => {
    if (route.request().method() === "POST") {
      profile = { id: "text-profile", name: "默认", is_default: true, version: 1, bindings: {} };
      await route.fulfill({ status: 201, json: profile });
    } else await route.fulfill({ json: profile ? [profile] : [] });
  });
  await page.route(`**/model-profiles/text-profile`, (route) => route.fulfill({ json: profile }));
  await page.route(`**/model-profiles/text-profile/simple-mode`, async (route) => {
    saves.push(route.request().postDataJSON());
    profile = {
      ...profile,
      version: 2,
      bindings: Object.fromEntries(
        ["planning.brief", "planning.script", "planning.storyboard"].map((slot) => [
          slot,
          { model_id: modelId },
        ]),
      ),
    };
    await route.fulfill({ json: profile });
  });
  await page.goto("/settings/models");
  await page.getByRole("button", { name: "选择 文本服务", exact: true }).click();
  const panel = page.getByRole("region", { name: "配置 文本服务", exact: true });
  await expect(panel.getByLabel("服务地址")).toHaveValue("");
  await panel.getByLabel("服务地址").fill(textConnection.base_url);
  await panel.getByLabel("API Key", { exact: true }).fill("text-only-fixture-key");
  await panel.getByRole("button", { name: "连接并读取模型" }).click();
  await expect(panel.getByText("my-chat", { exact: true })).toBeVisible();
  await panel.getByRole("button", { name: "完成", exact: true }).click();
  await panel.getByRole("button", { name: "启用 my-chat", exact: true }).click();
  await expect(panel.getByRole("button", { name: "已启用 my-chat", exact: true })).toBeDisabled();
  expect(creates).toEqual([
    {
      provider_type: "litellm",
      protocol_profile: "openai_chat_v1",
      display_name: "文本服务",
      base_url: textConnection.base_url,
      api_key: "text-only-fixture-key",
      enabled: true,
    },
  ]);
  expect(saves).toEqual([{ llm_model_id: modelId, expected_version: 1 }]);
  await expect(page.getByLabel("文本模型", { exact: true })).toHaveCount(0);
});

test("supplier settings stay read-only while browsing, show failed evidence, and keep the return context", async ({
  page,
}) => {
  const { writes } = await setupProviders(page);
  const origin = `/projects/${PROJECT_ID}/scenes/${SCENE_ID}?shotId=${SHOT_ID}`;
  await page.goto(`/settings/models?returnTo=${encodeURIComponent(origin)}`);
  const card = page.getByTestId("provider-connection-connection-fixture");
  await expect(card).toContainText("Fixture Provider");
  await expect(card).toContainText("已连接");
  await card.click();
  const dialog = page.getByTestId("provider-detail");
  await expect(dialog).toBeVisible();
  const sidebarBox = await page.getByRole("navigation", { name: "已连接的供应商" }).boundingBox();
  const detailBox = await dialog.boundingBox();
  expect(sidebarBox).not.toBeNull();
  expect(detailBox).not.toBeNull();
  expect(sidebarBox!.x + sidebarBox!.width).toBeLessThanOrEqual(detailBox!.x + 1);
  expect(detailBox!.width).toBeGreaterThan(sidebarBox!.width);
  await dialog.getByTestId("provider-diagnostics-disclosure").locator("summary").click();
  await expect(dialog.getByText("检查记录读取失败。")).toBeVisible();
  await expect(dialog.getByText("暂无检查记录。")).toHaveCount(0);
  await expect(dialog.getByLabel("诊断模型")).toHaveCount(0);
  await expect(dialog.getByText("NodeRun ID")).toHaveCount(0);
  await dialog.getByLabel("服务地址").fill("");
  await expect(dialog.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
  await dialog.getByRole("button", { name: "放弃修改" }).click();
  await expect(dialog.getByLabel("服务地址")).toHaveValue("https://saved.invalid");

  await expect(page.getByTestId("project-models-disclosure")).toHaveCount(0);
  await page.goto(`/settings/projects/${PROJECT_ID}?returnTo=${encodeURIComponent(origin)}`);
  await expect(page.getByTestId("project-settings-page")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("returnTo")).toBe(origin);
  await page.getByTestId("project-model-source-disclosure").locator("summary").click();
  const summary = page.getByTestId("project-model-source-summary");
  await expect(summary.getByTestId("model-source-visual.keyframe")).toContainText(
    "fixture/exact-image-v2",
  );
  await expect(summary.getByTestId("model-source-visual.keyframe")).toContainText(
    "工作空间默认方案",
  );
  await expect(summary.getByTestId("model-source-video.shot")).toContainText("未确认");
  // Project model details return to their settings parent, which owns the
  // final return to creation. Preserve the exact origin through both links.
  await page
    .getByRole("navigation", { name: "页面返回" })
    .getByRole("link", { name: "返回模型设置", exact: true })
    .click();
  await expect(page.getByTestId("model-settings-page")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("returnTo")).toBe(origin);
  const returnToCreation = page
    .getByRole("navigation", { name: "页面返回" })
    .getByRole("link", { name: "返回工作台", exact: true });
  await expect(returnToCreation).toHaveAttribute("href", origin);
  await returnToCreation.click();
  await expect(page).toHaveURL(origin);
  expect(writes).toEqual([]);
});

test("adding models reads the free catalog, then binds only the ticked exact identity", async ({
  page,
}) => {
  const { writes, model, connection } = await setupProviders(page);
  const saved: Array<Record<string, unknown>> = [];
  const probes: Array<Record<string, unknown>> = [];
  const bindings: Record<string, unknown>[] = [];
  await page.route(
    `**/api/v1/workspaces/${WORKSPACE_ID}/provider-connections/connection-fixture/probes`,
    async (route) => {
      if (route.request().method() === "POST") {
        probes.push(route.request().postDataJSON());
        await route.fulfill({
          json: {
            probe_id: "probe-fixture",
            capability: "auth_models",
            status: "passed",
            evidence_level: "account_verified",
            http_status: 200,
            provider_request_id: null,
            reference_artifact_id: null,
            model_binding_id: null,
            remote_query_kind: null,
            request_fingerprint: "f".repeat(64),
            tested_at: "2026-10-07T00:00:00Z",
            error_code: null,
            discovered_model_ids: [model.model_id, "unknown-remote-model"],
            connection_revision_id: "fixture-revision",
          },
        });
      } else await route.fulfill({ json: [] });
    },
  );
  await page.route(
    `**/api/v1/workspaces/${WORKSPACE_ID}/provider-connections/connection-fixture/model-bindings`,
    async (route) => {
      if (route.request().method() === "POST") {
        const input = route.request().postDataJSON();
        saved.push(input);
        const result = {
          ...input,
          id: "binding-fixture",
          connection_id: connection.id,
          catalog_entry_id: model.catalog_entry_id,
          capability_manifest_hash: model.capability_manifest_hash,
          enabled: true,
          documented: true,
          contract_tested: true,
          account_verified: true,
          quality_gated: false,
          remote_resource_kind: "model",
          remote_resource_id: model.model_id,
          invoke_model_value: model.model_id,
        };
        bindings.push(result);
        await route.fulfill({ json: result });
      } else await route.fulfill({ json: bindings });
    },
  );
  await page.goto(
    `/settings/models?returnTo=${encodeURIComponent(`/projects/${PROJECT_ID}/production`)}`,
  );
  await page.getByRole("button", { name: "管理 Fixture Provider" }).click();
  const dialog = page.getByTestId("provider-detail");
  await dialog.getByRole("button", { name: "添加模型", exact: true }).click();
  const picker = dialog.getByTestId("provider-model-picker");
  await expect(picker.getByText("已发现 · 暂未支持执行 1")).toBeVisible();
  await picker.getByRole("checkbox", { name: model.model_id }).check();
  expect(saved).toEqual([]);
  await dialog.getByRole("button", { name: "添加 1 个模型" }).click();
  await expect(dialog.getByText("已添加 1 个模型。")).toBeVisible();
  expect(probes).toEqual([{ capability: "auth_models" }]);
  expect(saved).toEqual([
    {
      model_id: model.model_id,
      media_type: "image",
      purpose: "keyframe",
      enabled: true,
      capability_contract_id: model.catalog_entry_id,
    },
  ]);
  await expect(dialog.getByTestId("provider-model-binding-fixture")).toContainText("可用");
  expect(writes.filter((path) => !/\/(probes|model-bindings)$/.test(path))).toEqual([]);
});
