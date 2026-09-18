import { expect, test } from "@playwright/test";
import { PROJECT_ID, SHOT_ID, installProfessionalMock } from "./professional-mocks";

test("review workspace persists time and image-region annotations without changing production", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  state.formalKeyframeArtifactId = "artifact-keyframe";
  state.formalVideoArtifactId = "artifact-video";
  const version = state.shotVersion;
  await page.route(`**/shots/${SHOT_ID}/workbench`, (route) =>
    route.fulfill({
      json: {
        shot: {
          id: SHOT_ID,
          version,
          formal_keyframe_artifact_id: state.formalKeyframeArtifactId,
          formal_video_artifact_id: state.formalVideoArtifactId,
          duration_seconds: "5",
        },
        candidates: [],
      },
    }),
  );
  await page.goto(`/projects/${PROJECT_ID}/review`);
  await expect(page.getByTestId("review-workspace")).toBeVisible();
  // Supply deterministic media metadata, not a remote provider or real video.
  const player = page.getByLabel("正式视频审片播放器");
  await player.evaluate((element) => {
    element.removeAttribute("src");
    Object.defineProperty(element, "duration", { configurable: true, value: 5 });
    element.dispatchEvent(new Event("loadedmetadata"));
  });
  await page.getByLabel("批注说明").fill("转头时人物身份漂移");
  await page.getByLabel("批注类型").selectOption("range");
  await page.getByLabel("批注开始时间").fill("1.2");
  await page.getByLabel("批注结束时间").fill("2.5");
  expect(state.annotations).toHaveLength(0);
  await page.getByRole("button", { name: "保存视频批注" }).click();
  await expect.poll(() => state.annotations.length).toBe(1);
  expect(state.annotations[0]).toMatchObject({
    target_kind: "video_time",
    time_start: "1.2",
    time_end: "2.5",
  });
  await expect(page.getByLabel("批注说明")).toHaveValue("");
  await page.getByLabel("批注说明").fill("右手区域曝光过曝");
  await page.getByRole("img", { name: "review target" }).evaluate((element) => {
    const svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450"><rect width="800" height="450" fill="gray"/></svg>';
    (element as HTMLImageElement).src = `data:image/svg+xml,${encodeURIComponent(svg)}`;
  });
  await expect
    .poll(() =>
      page
        .getByRole("img", { name: "review target" })
        .evaluate((element) => (element as HTMLImageElement).naturalWidth),
    )
    .toBe(800);
  const canvas = page.getByTestId("media-review-canvas");
  await canvas.scrollIntoViewIfNeeded();
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.6);
  await page.mouse.up();
  await expect.poll(() => state.annotations.length).toBe(2);
  expect(state.annotations[1].target_kind).toBe("image_region");
  expect(Number(state.annotations[1].width)).toBeCloseTo(0.3, 1);
  await expect(page.getByTestId("review-annotation-list")).toContainText("右手区域曝光过曝");
  expect(state.shotVersion).toBe(version);
});
