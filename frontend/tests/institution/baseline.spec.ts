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
  const upload = await request.post(files, {
    headers: { ...headers, "Content-Type": "application/octet-stream" },
    params: { filename: "synthetic.txt", request_key: suffix },
    data: Buffer.from(sourceText, "utf8"),
  });
  expect(upload.status()).toBe(201);
  const file = await upload.json();
  await expect
    .poll(
      async () => {
        const response = await request.get(files, { headers });
        expect(response.ok()).toBeTruthy();
        const rows = await response.json();
        return rows.find((row: { id: string }) => row.id === file.id)?.status;
      },
      { timeout: 30_000, intervals: [500, 1000, 2000] },
    )
    .toBe("parsed");
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
  await page.goto("/");
  await page.getByRole("combobox", { name: "工作空间筛选" }).click();
  await page.getByRole("option", { name: workspace.name, exact: true }).click();
  await expect(page.getByText(name, { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText(name, { exact: true })).toBeVisible();

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
