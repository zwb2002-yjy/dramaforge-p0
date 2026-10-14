import { expect, test } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID, SCENE_ID, SHOT_ID } from "./professional-mocks";

test("Prompt @Assets persist, rename and delete through the existing binding and Save gates", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  const assetId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  const artifactId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  const bindingId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
  const bindings: Array<Record<string, unknown>> = [];
  const base = `/api/v1/projects/${PROJECT_ID}`;
  const plans: Array<Record<string, unknown>> = [];
  let writes = 0;
  await page.route(
    (url) => url.pathname === `${base}/assets`,
    (route) =>
      route.fulfill({
        json: [
          {
            id: assetId,
            project_id: PROJECT_ID,
            name: "林墨",
            kind: "character",
            status: "active",
            description: "雨夜主角",
            version: 1,
          },
        ],
      }),
  );
  await page.route(
    (url) =>
      url.pathname.startsWith(`${base}/references/`) ||
      url.pathname === `${base}/shots/${SHOT_ID}/references` ||
      url.pathname === `${base}/shots/${SHOT_ID}/references/resolve`,
    (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      const body = request.postDataJSON() ?? {};
      if (path.endsWith("/resolve"))
        return route.fulfill({
          json: bindings.map((row) => ({
            binding_id: row.id,
            stage: row.stage,
            label: row.label,
            purpose: row.purpose,
            role: "reference_image",
            asset_id: assetId,
            asset_version_id: "version-1",
            artifact_id: artifactId,
            mime_type: "image/png",
            fingerprint: "b".repeat(64),
            source: "current_formal",
          })),
        });
      if (request.method() === "GET") return route.fulfill({ json: bindings });
      writes += 1;
      if (request.method() === "POST") {
        bindings.push({
          ...body,
          id: bindingId,
          project_id: PROJECT_ID,
          shot_id: SHOT_ID,
          version: 1,
        });
        return route.fulfill({ json: bindings[0], status: 201 });
      }
      if (request.method() === "PATCH") {
        expect(body.expected_version).toBe(bindings[0].version);
        Object.assign(bindings[0], body, { version: Number(bindings[0].version) + 1 });
        return route.fulfill({ json: bindings[0] });
      }
      bindings.splice(0);
      return route.fulfill({ status: 204 });
    },
  );
  await page.route(
    (url) => url.pathname === `${base}/shots/${SHOT_ID}/execution-plan`,
    (route) => {
      const body = route.request().postDataJSON();
      plans.push(body);
      expect(body.prompt).toBe(state.imagePrompt.trim() || state.visual.trim());
      expect(body.expected_shot_version).toBe(state.shotVersion);
      const label = String(bindings[0]?.label ?? "");
      return route.fulfill({
        json: {
          plan_fingerprint: "a".repeat(64),
          plan: {
            prompt: label ? String(body.prompt).replace(label, "参考图片1") : body.prompt,
            resolved_model: { resolved_model_id: "provider/model-b" },
            planned_references: body.references,
            capability_gaps: [],
            semantic_intent: {
              prompt_reference_map: label
                ? [{ label, notation: "参考图片1", binding_id: bindingId, artifact_id: artifactId }]
                : [],
            },
          },
        },
      });
    },
  );
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  const inspector = page.getByTestId("shot-inspector");
  await inspector.getByTestId("shot-design-prompts").locator(":scope > summary").click();
  const prompt = inspector.getByRole("textbox", { name: "图片提示词", exact: true });
  await prompt.fill("@林");
  await expect(prompt.locator("..").locator("..").getByRole("listbox")).toBeVisible();
  await prompt.press("Enter");
  await expect(prompt).toHaveValue("@林墨 ");
  await expect(inspector.getByTestId("mention-unresolved")).toHaveCount(0);
  expect(bindings[0]).toMatchObject({
    asset_id: assetId,
    label: "@林墨",
    stage: "image",
    resolution_mode: "current_formal",
    sort_order: 0,
  });
  await inspector.getByTestId("shot-primary-save").click();
  await expect(inspector.getByTestId("shot-design-message")).toHaveText("已保存。");
  await inspector.getByTestId("inspect-shot-plan").click();
  await expect(inspector.getByTestId("shot-prompt-reference-map")).toContainText(
    "@林墨 → 参考图片1",
  );
  await expect(inspector.getByTestId("shot-execution-plan-prompt")).toContainText("参考图片1");
  expect(plans[0].references).toEqual([
    {
      binding_id: bindingId,
      purpose: "identity",
      asset_version_id: "version-1",
      artifact_id: artifactId,
      resolution_mode: "current_formal",
      mime_type: "image/png",
      fingerprint: "b".repeat(64),
    },
  ]);
  expect(
    state.editing.requests.filter((request) => request.path.endsWith("/executions")),
  ).toHaveLength(0);

  await inspector.getByRole("button", { name: "编辑引用 @林墨" }).click();
  await inspector.getByLabel(`引用标签 ${bindingId}`).fill("@林墨_正面");
  await inspector.getByLabel(`引用顺序 ${bindingId}`).fill("3");
  await inspector.getByRole("button", { name: `保存引用 ${bindingId}` }).click();
  await expect(prompt).toHaveValue("@林墨_正面 ");
  await expect(inspector.getByTestId("shot-primary-save")).toBeVisible();
  await inspector.getByTestId("shot-primary-save").click();
  await expect(inspector.getByTestId("shot-design-message")).toHaveText("已保存。");
  await inspector.getByTestId("inspect-shot-plan").click();
  await expect(inspector.getByTestId("shot-prompt-reference-map")).toContainText(
    "@林墨_正面 → 参考图片1",
  );
  expect(bindings[0]).toMatchObject({ asset_id: assetId, sort_order: 3, version: 2 });

  await inspector.getByRole("button", { name: "删除提示词引用 @林墨_正面" }).click();
  await expect(prompt).toHaveValue(" ");
  await inspector.getByTestId("shot-primary-save").click();
  await expect(inspector.getByTestId("shot-design-message")).toHaveText("已保存。");
  await inspector.getByTestId("inspect-shot-plan").click();
  await expect.poll(() => plans.length).toBe(3);
  expect(plans[2].references).toEqual([]);
  expect(bindings).toEqual([]);
  expect(writes).toBe(3);
  expect(
    state.editing.requests.filter((request) =>
      /\/(executions|formal-keyframe|formal-video)$/.test(request.path),
    ),
  ).toHaveLength(0);
});
