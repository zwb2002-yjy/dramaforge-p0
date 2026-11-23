import { readFile } from "node:fs/promises";
import type { Page } from "@playwright/test";

export async function servePlaybackFixture(page: Page, path: string) {
  const bytes = await readFile(new URL("../../../fixtures/playback/red-tone.mp4", import.meta.url));
  await page.route(path, (route) => {
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
