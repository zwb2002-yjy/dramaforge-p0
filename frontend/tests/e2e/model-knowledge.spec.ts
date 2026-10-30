import { expect, test } from "@playwright/test";
import { installProfessionalMock, WORKSPACE_ID } from "./professional-mocks";
import { fixtureKnowledgeModel, fixtureKnowledgePlugin } from "../fixtures/model-knowledge";

test("knowledge browsing explains blockers and stays read-only with a verified account", async ({
  page,
}) => {
  await installProfessionalMock(page);
  const writes: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (
      path.startsWith("/api/") &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method()) &&
      !path.endsWith("/workspace-state")
    )
      writes.push(path);
  });
  const connection = {
    id: "connection-knowledge",
    workspace_id: WORKSPACE_ID,
    provider_type: "fixture",
    protocol_profile: "fixture_v1",
    display_name: "Fixture Provider",
    base_url: "https://example.invalid",
    enabled: true,
    credential_configured: true,
    credential_key_version: "v1",
    verification_status: "verified",
    verified_at: null,
    connection_revision_id: "revision-knowledge",
  };
  const binding = {
    id: "binding-knowledge",
    connection_id: connection.id,
    media_type: "video",
    model_id: fixtureKnowledgeModel.model_id,
    purpose: "video",
    enabled: true,
    documented: true,
    contract_tested: true,
    account_verified: true,
    quality_gated: false,
    catalog_entry_id: fixtureKnowledgeModel.catalog_entry_id,
    capability_manifest_hash: fixtureKnowledgeModel.capability_manifest_hash,
    remote_resource_kind: "model",
    remote_resource_id: fixtureKnowledgeModel.model_id,
    invoke_model_value: fixtureKnowledgeModel.model_id,
  };
  await page.route("**/api/v1/provider-plugins", (route) =>
    route.fulfill({ json: [fixtureKnowledgePlugin] }),
  );
  await page.route(`**/api/v1/workspaces/${WORKSPACE_ID}/provider-connections`, (route) =>
    route.fulfill({ json: [connection] }),
  );
  await page.route(`**/provider-connections/${connection.id}/model-bindings`, (route) =>
    route.fulfill({ json: [binding] }),
  );
  await page.route(`**/provider-connections/${connection.id}/probes`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/workspaces/${WORKSPACE_ID}/model-profiles`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/v1/models", (route) =>
    route.fulfill({
      json: [
        {
          id: `binding:${binding.id}`,
          provider_id: "fixture",
          display_name: fixtureKnowledgeModel.model_id,
          source: "workspace",
          enabled: true,
          configured: true,
          available: false,
          availability_reason: "MODEL_OFFICIAL_EVIDENCE_GAP",
          capabilities: ["video.image_to_video"],
        },
      ],
    }),
  );
  await page.goto("/settings/models");
  await page.getByRole("button", { name: "管理 Fixture Provider" }).click();
  const detail = page.getByTestId("provider-detail");
  const row = detail.getByTestId(`provider-model-${binding.id}`);
  await expect(row).toContainText("官方证据尚未覆盖当前合同的全部执行字段");
  await expect(
    row.getByRole("button", { name: `启用 ${binding.model_id}`, exact: true }),
  ).toBeDisabled();
  const panel = detail.getByTestId("provider-model-knowledge");
  await panel.getByText("模型能力说明", { exact: true }).click();
  await panel.getByText(binding.model_id, { exact: true }).click();
  await expect(
    panel.getByText("候选修订未实现；产品未开放；该修订账号尚未实测。", { exact: true }),
  ).toBeVisible();
  await expect(panel.getByText(/现有绑定：目录已验证/)).toBeVisible();
  await expect(panel.getByText(/未知不代表无上限/)).toBeVisible();
  await panel.getByText("视频生成", { exact: true }).click();
  await expect(panel.getByText(/参考音频合计时长：最多 15 秒/)).toBeVisible();
  await expect(panel.getByText(/分辨率仅允许480p/)).toBeVisible();
  await expect(panel.getByText("来源存在冲突", { exact: true })).toBeVisible();
  await panel.getByText("视频延长", { exact: true }).click();
  await expect(panel.getByText(/尚未接入执行/).first()).toBeVisible();
  await panel.getByText("来源与修订", { exact: true }).click();
  await expect(panel.getByRole("link", { name: "官方资料" })).toHaveAttribute(
    "href",
    "https://example.invalid/model-doc",
  );
  await expect(panel.locator("input, select, textarea, button")).toHaveCount(0);
  await expect(panel).not.toContainText("input_contract");
  await expect(panel).not.toContainText("first_frame");
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
});
