import { servePlaybackFixture } from "./playback-fixture";
import { expect, test } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID } from "./professional-mocks";

for (const video of [false, true]) {
  test(`公共资产固定引用与导演附件（${video ? "视频" : "图片"}）`, async ({ page }) => {
    await installProfessionalMock(page);
    const base = `/api/v1/projects/${PROJECT_ID}/public-asset-links`;
    const asset = {
      id: "fixture-public",
      safe_name: "灯会画面",
      safe_description: "合成画面",
      kind: "image",
      status: "available",
      usable: true,
      items: [
        {
          id: "image",
          media_kind: video ? "video" : "image",
          mime_type: video ? "video/mp4" : "image/png",
          preview_available: true,
        },
      ],
    };
    await page.route(
      (url) => url.pathname === "/api/v1/public-assets",
      (route) =>
        route.fulfill({
          json: {
            items: [
              asset,
              {
                ...asset,
                id: "blocked",
                safe_name: "撤权素材",
                usable: false,
                status: "restricted",
              },
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
    if (video) {
      await servePlaybackFixture(page, "**/public-assets/fixture-public/items/image/content*");
    }
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
            json: {
              items: link ? [{ ...link, availability: "available" }] : [],
              total: Number(Boolean(link)),
              next_offset: null,
            },
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
    const hash = "a".repeat(64);
    const publicPart = {
      kind: "public_asset",
      public_asset_link_id: "fixed",
      publication_item_id: "image",
      expected_content_hash: hash,
      transform: { max_edge: 1024, frame_time_ms: video ? 600 : null },
    };
    let messages = 0;
    await page.route(
      (url) => url.pathname === base + "/fixed/items/image/content",
      (route) => {
        expect(route.request().method()).toBe("HEAD");
        return route.fulfill({ status: 200, headers: { ETag: '"' + hash + '"' } });
      },
    );
    await page.route(
      (url) => url.pathname === base + "/fixed/items/image/vision-preview",
      (route) => {
        expect(new URL(route.request().url()).searchParams.get("expected_content_hash")).toBe(hash);
        return route.fulfill({
          contentType: "image/svg+xml",
          body: '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><circle cx="4" cy="4" r="3"/></svg>',
        });
      },
    );
    await page.route("**/director/threads**", (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path.endsWith("/messages") && request.method() === "POST") {
        expect(request.postDataJSON().media_parts).toEqual([publicPart]);
        expect(request.postDataJSON().ui_context).toBeUndefined();
        messages++;
        return route.fulfill({
          status: 202,
          json: { thread_id: "thread", turn_id: "turn", status: "queued" },
        });
      }
      if (path.endsWith("/requests"))
        return route.fulfill({ json: { turn: { status: "completed" } } });
      return route.fulfill({
        json: {
          id: "thread",
          scope_type: "project",
          scope_entity_id: PROJECT_ID,
          messages: messages
            ? [
                {
                  id: "message",
                  turn_id: "turn",
                  role: "user",
                  content: "画面中有什么？",
                  media_parts: [publicPart],
                },
              ]
            : [],
        },
      });
    });
    await page.goto(`/projects/${PROJECT_ID}`);
    await page.getByRole("link", { name: "公共资产", exact: true }).click();
    const library = page.getByRole("region", { name: "公共资产" });
    const card = library.getByRole("listitem").filter({ hasText: "灯会画面" });
    const blocked = library.getByRole("listitem").filter({ hasText: "撤权素材" });
    await expect(blocked.getByRole("button", { name: "引用到当前项目" })).toBeDisabled();
    await expect(blocked.getByRole("button", { name: "预览素材" })).toHaveCount(0);
    await card.getByRole("button", { name: "预览素材" }).click();
    if (video) {
      await card.locator("video").evaluate(async (el: HTMLVideoElement) => {
        if (!el.readyState)
          await new Promise<void>((r) =>
            el.addEventListener("loadedmetadata", () => r(), { once: true }),
          );
        await new Promise<void>((r) => {
          el.addEventListener("seeked", () => r(), { once: true });
          el.currentTime = 0.6;
        });
      });
      expect(
        await card.locator("video").evaluate((el: HTMLVideoElement) => el.currentTime),
      ).toBeCloseTo(0.6, 3);
    } else await expect(card.getByRole("img", { name: asset.safe_name })).toBeVisible();
    expect(writes).toEqual([]);
    await card.getByRole("button", { name: "引用到当前项目" }).click();
    await expect(card.getByText("当前项目已引用")).toBeVisible();
    await card.getByRole("button", { name: video ? "将当前帧附给导演" : "将图片附给导演" }).click();
    await expect(page.getByRole("img", { name: "将随消息发送的公共画面" })).toBeVisible();
    expect(messages).toBe(0);
    await page.getByRole("textbox", { name: "给导演的想法" }).fill("画面中有什么？");
    await page.getByRole("button", { name: "发送给导演" }).click();
    await expect(page.getByRole("img", { name: "发送给导演的画面" })).toBeVisible();
    expect(messages).toBe(1);
    await page.reload();
    await card.getByRole("button", { name: "解除项目引用" }).click();
    await card.getByRole("button", { name: "重新引用到项目" }).click();
    await expect(card.getByText("当前项目已引用")).toBeVisible();
    expect(writes).toEqual(["POST", "PATCH", "PATCH"]);
  });
}
