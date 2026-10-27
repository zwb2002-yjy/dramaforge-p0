import { expect, test } from "@playwright/test";
import { installProfessionalMock, WORKSPACE_ID } from "./professional-mocks";
import { selectValue } from "./selectValue";

test("two configured no-key Images services share one contract and switch existing image slots", async ({
  page,
}) => {
  await installProfessionalMock(page);
  const contract = {
    catalog_entry_id: "generic-images",
    capability_manifest_hash: "h".repeat(64),
    model_id: "@contract/images-fixture",
    model_revision: "v1",
    media_type: "image",
    display_name: "单张方图",
    lifecycle: "active",
    implementation_status: "contract_tested",
    catalog_source: "protocol_contract",
    new_create_blocker: null,
    capability_summary: { accepts_text_only: true, product_text_only: true },
  };
  const connections: Record<string, unknown>[] = [];
  const bindings: Record<string, unknown>[] = [];
  const probes = new Map<string, unknown[]>();
  const creates: Record<string, unknown>[] = [];
  const slots = ["visual.character", "visual.storyboard", "visual.keyframe"];
  const originalText = { model_id: "litellm/existing/text", native_options: { temperature: 0.2 } };
  const originalVideo = {
    model_id: "binding:existing-video",
    native_options: { duration: 8 },
    enabled: false,
  };
  let profile = {
    id: "profile",
    is_default: true,
    version: 1,
    bindings: { "planning.script": originalText, "video.shot": originalVideo } as Record<
      string,
      unknown
    >,
  };
  const activations: unknown[] = [];
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route("**/api/v1/provider-plugins", (route) =>
    route.fulfill({
      json: [
        {
          provider_type: "openai_compatible_media",
          protocol_profile: "openai_images_v2",
          kind: "media",
          display_name: "同步 Images",
          implemented: true,
          default_base_url: "",
          model_list_path: "/models",
          auth_modes: ["bearer", "none"],
          manual_model_ids: true,
          models: [contract],
          capabilities: ["auth_models"],
          paid_capabilities: [],
        },
      ],
    }),
  );
  await page.route(`**/workspaces/${WORKSPACE_ID}/provider-connections`, async (route) => {
    if (route.request().method() === "POST") {
      const input = route.request().postDataJSON();
      creates.push(input);
      const label = input.display_name;
      const row = {
        ...input,
        id: `connection-${label}`,
        workspace_id: WORKSPACE_ID,
        credential_configured: false,
        credential_key_version: null,
        enabled: true,
        verification_status: "unverified",
        verified_at: null,
        connection_revision_id: `revision-${label}`,
      };
      connections.push(row);
      await route.fulfill({ status: 201, json: row });
    } else await route.fulfill({ json: connections });
  });
  await page.route("**/provider-connections/*/probes", async (route) => {
    const id = route.request().url().split("/").at(-2)!;
    const current = connections.find((item) => item.id === id)!;
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toEqual({ capability: "auth_models" });
      current.verification_status = "verified";
      const reply = {
        probe_id: `probe-${id}`,
        capability: "auth_models",
        status: "passed",
        http_status: 200,
        connection_revision_id: current.connection_revision_id,
        discovered_model_ids: [`model-${current.display_name}`],
        tested_at: "2026-10-28T00:00:00Z",
      };
      probes.set(id, [reply]);
      await route.fulfill({ json: reply });
    } else await route.fulfill({ json: probes.get(id) ?? [] });
  });
  await page.route("**/provider-connections/*/model-bindings", async (route) => {
    const id = route.request().url().split("/").at(-2)!;
    if (route.request().method() === "POST") {
      const input = route.request().postDataJSON();
      const current = connections.find((item) => item.id === id)!;
      const row = {
        ...input,
        id: `binding-${current.display_name}`,
        connection_id: id,
        documented: true,
        contract_tested: true,
        account_verified: true,
        quality_gated: false,
        catalog_entry_id: input.capability_contract_id,
        capability_manifest_hash: contract.capability_manifest_hash,
        generation_evidence: {
          connection_revision_id: current.connection_revision_id,
          verified: false,
        },
      };
      bindings.push(row);
      await route.fulfill({ status: 201, json: row });
    } else await route.fulfill({ json: bindings.filter((item) => item.connection_id === id) });
  });
  await page.route("**/api/v1/models*", (route) =>
    route.fulfill({
      json: bindings.map((item) => ({
        id: `binding:${item.id}`,
        display_name: item.model_id,
        source: "workspace",
        available: true,
        capabilities: ["image.generate"],
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
    activations.push(input);
    profile = {
      ...profile,
      version: profile.version + 1,
      bindings: {
        ...profile.bindings,
        ...Object.fromEntries(
          slots.map((slot) => [
            slot,
            { model_id: input.image_model_id, native_options: {}, enabled: true },
          ]),
        ),
      },
    };
    await route.fulfill({ json: profile });
  });
  await page.goto("/settings/models");
  for (const label of ["alpha", "beta"]) {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByTestId("add-provider").click();
    const dialog = page.getByTestId("add-provider-dialog");
    await dialog.getByLabel("连接名称").fill(label);
    await dialog.getByLabel("服务地址").fill(`https://${label}.example.test/v1`);
    await selectValue(dialog.getByLabel("认证方式"), "none");
    await expect(dialog.getByLabel("API Key", { exact: true })).toHaveCount(0);
    await dialog.getByLabel("服务地址").press("Enter");
    const picker = page.getByTestId("provider-model-picker");
    await selectValue(picker.getByLabel(`model-${label} 调用方式`), "generic-images");
    await picker.getByRole("checkbox", { name: `使用 model-${label}` }).check();
    await expect(dialog).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await dialog.getByRole("button", { name: "添加 1 个模型" }).click();
    await expect(dialog).not.toBeVisible();
    await expect(
      page.getByRole("button", { name: `启用 model-${label}`, exact: true }),
    ).toBeEnabled();
    await page.getByRole("button", { name: `启用 model-${label}`, exact: true }).click();
    await expect(
      page.getByRole("button", { name: `已启用 model-${label}`, exact: true }),
    ).toBeDisabled();
    await expect(page.getByText("真实生成待验证", { exact: true })).toBeVisible();
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("button", { name: "管理 alpha", exact: true }).click();
  await page.getByRole("button", { name: "启用 model-alpha", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "管理 alpha", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "已启用 model-alpha", exact: true }),
  ).toBeDisabled();
  expect(creates).toHaveLength(2);
  expect(creates.every((item) => item.auth_mode === "none" && !("api_key" in item))).toBe(true);
  expect(new Set(creates.map((item) => item.base_url)).size).toBe(2);
  expect(bindings.every((item) => item.catalog_entry_id === "generic-images")).toBe(true);
  expect(activations).toHaveLength(3);
  expect(profile.bindings["planning.script"]).toEqual(originalText);
  expect(profile.bindings["video.shot"]).toEqual(originalVideo);
  expect(pageErrors).toEqual([]);
});
