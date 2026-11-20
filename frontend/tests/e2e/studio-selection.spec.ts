import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID, SHOT_ID } from "./professional-mocks";

for (const mode of ["reference", "image", "video"] as const) {
  const attach = mode !== "reference";
  const video = mode === "video";
  const candidateLabel = video ? "预览第 2 个视频" : "预览第 2 个关键帧";
  test(`project chat keeps the selected candidate across reload (${mode})`, async ({ page }) => {
    await installProfessionalMock(page);
    const first = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
      second = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2";
    const thread = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      turn = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
    const context = {
      selected_refs: [
        { kind: "shot", id: SHOT_ID },
        { kind: "artifact", id: second },
      ],
    };
    let requestKey = "",
      submissions = 0,
      complete = false;
    await page.route(`**/shots/${SHOT_ID}/workbench`, (route) =>
      route.fulfill({
        json: {
          shot: { id: SHOT_ID },
          candidates: [first, second].map((id) => ({
            stage: video ? "video" : "image_keyframe",
            artifact_id: id,
            artifact_type: video ? "video" : "image",
            content_hash: "a".repeat(64),
            status: "completed",
            storage_state: "available",
          })),
        },
      }),
    );
    const parts = [
      {
        kind: "artifact",
        artifact_id: second,
        expected_content_hash: "a".repeat(64),
        transform: { max_edge: 1024, frame_time_ms: video ? 600 : null },
      },
    ];
    await page.route("**/vision-preview?**", (route) =>
      route.fulfill({
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5xkAAAAASUVORK5CYII=",
          "base64",
        ),
      }),
    );
    await page.route("**/director/threads**", async (route) => {
      const r = route.request(),
        path = new URL(r.url()).pathname;
      if (path.endsWith("/messages") && r.method() === "POST") {
        const input = r.postDataJSON();
        expect(input.ui_context).toEqual(context);
        expect(input.media_parts).toEqual(attach ? parts : undefined);
        expect(input.content).toBe("让第二个画面更明亮");
        requestKey = input.request_key;
        submissions++;
        return route.fulfill({
          status: 202,
          json: { thread_id: thread, turn_id: turn, request_key: requestKey, status: "queued" },
        });
      }
      if (path.endsWith("/threads"))
        return route.fulfill({
          json: { id: thread, scope_type: "project", scope_entity_id: PROJECT_ID },
        });
      if (path.endsWith("/requests"))
        return route.fulfill({
          json: {
            acceptance: { thread_id: thread, turn_id: turn },
            turn: { thread_id: thread, turn_id: turn, status: complete ? "completed" : "thinking" },
          },
        });
      return route.fulfill({
        json: {
          id: thread,
          scope_type: "project",
          scope_entity_id: PROJECT_ID,
          messages: submissions
            ? [
                {
                  id: "user-message",
                  role: "user",
                  media_parts: attach ? parts : [],
                  content: "让第二个画面更明亮",
                  turn_id: turn,
                  context,
                },
              ]
            : [],
        },
      });
    });
    if (video) {
      const bytes = await readFile(
        new URL("../../../fixtures/playback/red-tone.mp4", import.meta.url),
      );
      await page.route("**/artifacts/*/content**", (route) => {
        const range = /^bytes=(\d+)-(\d*)$/.exec(route.request().headers().range ?? "");
        if (!range)
          return route.fulfill({
            contentType: "video/mp4",
            body: bytes,
            headers: { "Accept-Ranges": "bytes" },
          });
        const start = Number(range[1]),
          end = range[2] ? Math.min(bytes.length - 1, Number(range[2])) : bytes.length - 1;
        return route.fulfill({
          status: 206,
          contentType: "video/mp4",
          body: bytes.subarray(start, end + 1),
          headers: {
            "Accept-Ranges": "bytes",
            "Content-Range": `bytes ${start}-${end}/${bytes.length}`,
          },
        });
      });
    }
    await page.goto(`/projects/${PROJECT_ID}`);
    await page.getByRole("button", { name: candidateLabel }).click();
    expect(submissions).toBe(0);
    if (video) {
      const main = page.getByLabel("作品预览", { exact: true });
      await expect(main).toHaveAttribute("src", new RegExp(second));
      await main.evaluate(async (el: HTMLVideoElement) => {
        if (!el.readyState)
          await new Promise<void>((r) =>
            el.addEventListener("loadedmetadata", () => r(), { once: true }),
          );
        await new Promise<void>((r) => {
          el.addEventListener("seeked", () => r(), { once: true });
          el.currentTime = 0.6;
        });
      });
    }
    if (video)
      expect(
        await page
          .getByLabel("作品预览", { exact: true })
          .evaluate((el: HTMLVideoElement) => el.currentTime),
      ).toBeCloseTo(0.6, 3);
    if (attach)
      await page.getByRole("button", { name: video ? "附上当前视频帧" : "附上这张图片" }).click();
    await page.getByRole("textbox", { name: "给导演的想法" }).fill("让第二个画面更明亮");
    await page.getByRole("button", { name: "发送给导演" }).click();
    await expect.poll(() => submissions).toBe(1);
    await page.reload();
    await expect(page.getByRole("link", { name: "查看本条讨论的画面" })).toBeVisible();
    expect(submissions).toBe(1);
    if (attach) await expect(page.getByRole("img", { name: "发送给导演的画面" })).toBeVisible();
    complete = true;
    await page.getByRole("link", { name: "查看本条讨论的画面" }).click();
    await expect(page.getByRole("button", { name: candidateLabel })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByRole("textbox", { name: "给导演的想法" })).toBeVisible();
    expect(submissions).toBe(1);
  });
}
