import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

import { PROJECT_ID, SCENE_ID } from "./professional-mocks";
import { installShotJourneyMock } from "./shot-journey-mocks";

for (const count of [1, 30, 100]) {
  test(`${count} Shots / ${count * 3} candidates have bounded initial media and responsive cached selection`, async ({
    page,
  }, info) => {
    const state = await installShotJourneyMock(page);
    const prototype = state.shots[0];
    state.shots.splice(
      0,
      state.shots.length,
      ...Array.from({ length: count }, (_, index) => ({
        ...prototype,
        id:
          index === 0
            ? prototype.id
            : `10000000-0000-4000-8000-${index.toString(16).padStart(12, "0")}`,
        shot_number: index + 1,
        sort_order: index + 1,
        visual_description: `资源镜头 ${index + 1}`,
      })),
    );
    for (const shot of state.shots)
      state.candidates[shot.id] = Array.from({ length: 3 }, (_, index) => ({
        artifact_id: `resource-${shot.shot_number}-${index}`,
        node_run_id: `resource-run-${shot.shot_number}-${index}`,
        node_key: index === 2 ? "video" : "keyframe",
        stage: index === 2 ? "video" : "image_keyframe",
        status: "completed",
        artifact_type: index === 2 ? "video" : "image",
        mime_type: index === 2 ? "video/mp4" : "image/png",
        review_allowed: false,
        review_decision: null,
        review_node_run_id: null,
        review_artifact_id: null,
      }));
    const errors: string[] = [];
    let requests = 0,
      media = 0;
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (path.startsWith("/api/")) requests += 1;
      if (/\/artifacts\/[^/]+\/content$/.test(path)) media += 1;
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    const started = Date.now();
    await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
    await expect(page.getByTestId("shot-design-panel")).toHaveAttribute(
      "data-shot-id",
      state.shots[0].id,
    );
    const firstScreenMs = Date.now() - started;
    const initial = { requests, media };
    expect(initial.media).toBeLessThanOrEqual(5);
    expect(await page.locator("video").count()).toBeLessThanOrEqual(1);
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Performance.enable");
    const initialMetrics = await cdp.send("Performance.getMetrics");
    const targets = [state.shots[0], state.shots[state.shots.length - 1]];
    for (const target of targets) {
      await page.getByTestId(`shot-strip-card-${target.id}`).click();
      await expect(page.getByTestId("shot-design-panel")).toHaveAttribute(
        "data-shot-id",
        target.id,
      );
    }
    const durations: number[] = [];
    for (let index = 0; index < 30; index += 1) {
      const target = targets[index % targets.length];
      const elapsed = await page.evaluate(
        ({ id, single, open }) =>
          new Promise<number>((resolve, reject) => {
            const started = performance.now();
            const ready = () =>
              single
                ? Boolean(document.querySelector('[data-testid="shot-details-sheet"]')) === open
                : document
                    .querySelector('[data-testid="shot-design-panel"]')
                    ?.getAttribute("data-shot-id") === id;
            const finish = () => {
              if (!ready()) return;
              observer.disconnect();
              clearTimeout(timeout);
              requestAnimationFrame(() => resolve(performance.now() - started));
            };
            const observer = new MutationObserver(finish);
            observer.observe(document.body, { childList: true, attributes: true, subtree: true });
            const timeout = setTimeout(() => {
              observer.disconnect();
              reject(new Error("selection did not settle"));
            }, 3000);
            const selector = single
              ? '[data-testid="shot-inspector-details"] [role="button"]'
              : `[data-testid="shot-strip-card-${id}"]`;
            const button = document.querySelector<HTMLButtonElement>(selector);
            if (!button) throw new Error("selection control missing");
            button.click();
            finish();
          }),
        { id: target.id, single: count === 1, open: index % 2 === 0 },
      );
      durations.push(elapsed);
    }
    const metrics = await cdp.send("Performance.getMetrics");
    const metric = (values: typeof metrics, name: string) =>
      values.metrics.find((item) => item.name === name)?.value ?? null;
    const p95 = [...durations].sort((a, b) => a - b)[Math.ceil(durations.length * 0.95) - 1];
    const evidence = {
      shots: count,
      candidates: count * 3,
      viewport: "1440x900",
      firstScreenMs,
      initial,
      requests,
      media,
      interactionCount: durations.length,
      p95Ms: p95,
      durations,
      measurement:
        count === 1
          ? "cached details DOM mount to next animation frame"
          : "DOM click to current Shot inspector next animation frame",
      initialHeap: metric(initialMetrics, "JSHeapUsedSize"),
      finalHeap: metric(metrics, "JSHeapUsedSize"),
      domNodes: metric(metrics, "Nodes"),
      browser: page.context().browser()?.version(),
      cpu: await readFile("/sys/fs/cgroup/cpu.max", "utf8"),
      memory: await readFile("/sys/fs/cgroup/memory.max", "utf8"),
      fixture: "controlled API, no backend latency or Provider qualification claim",
    };
    await info.attach("workbench-resource", {
      body: JSON.stringify(evidence, null, 2),
      contentType: "application/json",
    });
    console.log(JSON.stringify(evidence));
    expect(p95).toBeLessThanOrEqual(200);
    expect(errors).toEqual([]);
    expect(
      state.requests.filter((item) =>
        /\/(executions|formal-keyframe|formal-video)$/.test(item.path),
      ),
    ).toEqual([]);
  });
}
