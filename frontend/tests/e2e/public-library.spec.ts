import { expect, test } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID } from "./professional-mocks";

test("项目导航进入公共资产，预览、固定引用、解除与重新引用", async ({ page }) => {
  await installProfessionalMock(page);
  const base = `/api/v1/projects/${PROJECT_ID}/public-asset-links`;
  const asset = {
    id: "fixture-public",
    safe_name: "灯会画面",
    safe_description: "合成画面",
    kind: "image",
    status: "available",
    usable: true,
    items: [{ id: "image", media_kind: "image", preview_available: true }],
  };
  await page.route(
    (url) => url.pathname === "/api/v1/public-assets",
    (route) =>
      route.fulfill({
        json: {
          items: [
            asset,
            { ...asset, id: "blocked", safe_name: "撤权素材", usable: false, status: "restricted" },
          ],
          total: 2,
          next_offset: null,
        },
      }),
  );
  await page.route("**/public-assets/fixture-public/items/image/content*", (route) =>
    route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><circle cx="4" cy="4" r="3"/></svg>',
    }),
  );
  let link: {
    id: string;
    publication_id: string;
    version: number;
    detached_at: string | null;
  } | null = null;
  const writes: string[] = [];
  await page.route(
    (url) => url.pathname === base || url.pathname === base + "/fixed",
    async (route) => {
      const method = route.request().method();
      if (method === "GET")
        return route.fulfill({
          json: { items: link ? [link] : [], total: Number(Boolean(link)), next_offset: null },
        });
      const data = route.request().postDataJSON();
      if (method === "POST") {
        expect(data.publication_id).toBe(asset.id);
        link = { id: "fixed", publication_id: asset.id, version: 1, detached_at: null };
      } else {
        expect(data.expected_version).toBe(link?.version);
        if (!link) throw Error("missing library link");
        link = {
          ...link,
          version: link.version + 1,
          detached_at: data.attached ? null : "2026-11-23",
        };
      }
      writes.push(method);
      return route.fulfill({ json: link });
    },
  );
  await page.goto(`/projects/${PROJECT_ID}`);
  await page.getByRole("link", { name: "公共资产", exact: true }).click();
  const library = page.getByRole("region", { name: "公共资产" });
  const card = library.getByRole("listitem").filter({ hasText: "灯会画面" });
  const blocked = library.getByRole("listitem").filter({ hasText: "撤权素材" });
  await expect(blocked.getByRole("button", { name: "引用到当前项目" })).toBeDisabled();
  await expect(blocked.getByRole("button", { name: "预览素材" })).toHaveCount(0);
  await card.getByRole("button", { name: "预览素材" }).click();
  await expect(card.getByRole("img", { name: asset.safe_name })).toBeVisible();
  expect(writes).toEqual([]);
  await card.getByRole("button", { name: "引用到当前项目" }).click();
  await expect(card.getByText("当前项目已引用")).toBeVisible();
  await page.reload();
  await card.getByRole("button", { name: "解除项目引用" }).click();
  await card.getByRole("button", { name: "重新引用到项目" }).click();
  await expect(card.getByText("当前项目已引用")).toBeVisible();
  expect(writes).toEqual(["POST", "PATCH", "PATCH"]);
});
