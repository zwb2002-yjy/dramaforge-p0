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
  };
  const plugin = {
    provider_type: "fixture",
    protocol_profile: "fixture-v1",
    display_name: "Fixture Provider",
    default_base_url: "https://fixture.invalid",
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

test("supplier configuration stays read-only, distinguishes partial/failed evidence, and keeps the exact return context", async ({
  page,
}) => {
  const { writes } = await setupProviders(page);
  const origin = `/projects/${PROJECT_ID}/scenes/${SCENE_ID}?shotId=${SHOT_ID}`;
  await page.goto(`/settings/models?returnTo=${encodeURIComponent(origin)}`);
  const summary = page.getByTestId("project-model-source-summary");
  await expect(summary).toBeVisible();
  await expect(summary.getByTestId("model-source-visual.keyframe")).toContainText(
    "fixture/exact-image-v2",
  );
  await expect(summary.getByTestId("model-source-visual.keyframe")).toContainText(
    "工作空间默认方案",
  );
  await expect(summary.getByTestId("model-source-video.shot")).toContainText("未确认");
  await page.getByTestId("provider-diagnostics-disclosure").locator("summary").click();
  await expect(page.getByRole("combobox", { name: "项目 Provider 绑定" })).toHaveValue(PROJECT_ID);
  await expect(page.getByText(/能力证据读取失败/)).toBeVisible();
  await expect(page.getByText("暂无能力证据。")).toHaveCount(0);
  await page.getByLabel("探测能力").selectOption("image_t2i");
  await expect(page.getByRole("button", { name: "付费探测暂不可用" })).toBeDisabled();
  await page.getByLabel("供应商服务地址").fill("");
  await expect(page.getByLabel("供应商服务地址")).toHaveValue("");
  await expect(page.getByRole("button", { name: "保存连接地址" })).toBeDisabled();
  await page.getByRole("button", { name: "放弃连接草稿" }).click();
  await page.getByTestId("project-models-disclosure").locator("summary").click();
  await page.getByRole("link", { name: "配置项目模型", exact: true }).click();
  await expect(page.getByTestId("project-settings-page")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("returnTo")).toBe(origin);
  // Project model details return to their settings parent, which owns the
  // final return to creation. Preserve the exact origin through both links.
  await page
    .getByRole("navigation", { name: "页面返回" })
    .getByRole("link", { name: "返回模型连接", exact: true })
    .click();
  await expect(page.getByTestId("model-settings-page")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("returnTo")).toBe(origin);
  const returnToCreation = page
    .getByRole("navigation", { name: "页面返回" })
    .getByRole("link", { name: "返回创作", exact: true });
  await expect(returnToCreation).toHaveAttribute("href", origin);
  await returnToCreation.click();
  await expect(page).toHaveURL(origin);
  expect(writes).toEqual([]);
});

test("selecting a catalog model is only a draft and persists the exact identity on explicit Add", async ({
  page,
}) => {
  const { writes, model, connection } = await setupProviders(page);
  const saved: Array<Record<string, unknown>> = [];
  const bindings: Record<string, unknown>[] = [];
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
          account_verified: false,
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
  await page.getByTestId("provider-diagnostics-disclosure").locator("summary").click();
  await page.getByLabel("关键帧模型", { exact: true }).selectOption(model.model_id);
  expect(saved).toEqual([]);
  expect(writes).toEqual([]);
  await page.getByRole("button", { name: "添加关键帧模型绑定" }).click();
  await expect(page.getByTestId("provider-config-message")).toContainText(
    `模型绑定已创建：${model.model_id}`,
  );
  expect(saved).toEqual([
    { model_id: model.model_id, media_type: "image", purpose: "keyframe", enabled: true },
  ]);
  await expect(page.getByRole("button", { name: "绑定所选项目" })).toBeDisabled();
  expect(writes.filter((path) => path.includes("/probes"))).toEqual([]);
});
