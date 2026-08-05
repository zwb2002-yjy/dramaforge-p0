import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const doneStatuses = new Set(["completed", "cached", "completed_after_cancel"]);
const requiredNodeKeys = new Set([
  "prompt",
  "keyframe",
  "face_review",
  "video",
  "video_drift_review",
  "voice",
  "subtitle",
  "composite",
  "continuity_review",
]);

type CreationState = {
  brief: { id: string; status: string; source: string } | null;
  plan: {
    id: string;
    status: string;
    source: string;
    materialized: boolean;
    plan: { shots?: unknown[] };
  } | null;
};

type ProjectSnapshot = {
  node_runs: Array<{
    id: string;
    status: string;
    result_artifact_id: string | null;
    input_snapshot: { shot_id?: unknown; node_key?: unknown };
  }>;
  artifacts: Array<{
    id: string;
    object_key: string;
    produced_by_run_id: string | null;
  }>;
};

type Shot = { id: string; status: string };

type ExportResult = {
  export_id: string;
  timeline_hash: string;
  source_artifact_ids: string[];
  source_node_run_ids: string[];
  export_item_count: number;
};

function cleanSourceCommit(): string {
  const dirty = execFileSync("git", ["-C", repoRoot, "status", "--porcelain=v1"], {
    encoding: "utf8",
  }).trim();
  if (dirty) throw new Error("P0 real UI proof requires a clean worktree");
  return execFileSync("git", ["-C", repoRoot, "rev-parse", "HEAD"], {
    encoding: "utf8",
  }).trim();
}

async function browserGet<T>(page: Page, url: string): Promise<T> {
  return page.evaluate(async (requestUrl) => {
    const workspaceId = window.sessionStorage.getItem("dramaforge.selected-workspace-id");
    const response = await fetch(requestUrl, {
      credentials: "include",
      headers: workspaceId ? { "X-Workspace-Id": workspaceId } : {},
    });
    if (!response.ok) throw new Error(`${requestUrl} returned ${response.status}`);
    return response.json();
  }, url) as Promise<T>;
}

function runsForShot(snapshot: ProjectSnapshot, shotId: string) {
  return snapshot.node_runs.filter((run) => String(run.input_snapshot.shot_id ?? "") === shotId);
}

function assertCompleteShotLineage(snapshot: ProjectSnapshot, shotIds: string[]) {
  const artifactsById = new Map(snapshot.artifacts.map((artifact) => [artifact.id, artifact]));
  const formalRuns = snapshot.node_runs.filter((run) =>
    requiredNodeKeys.has(String(run.input_snapshot.node_key ?? "")),
  );
  const resultArtifactIds = formalRuns.map((run) => run.result_artifact_id);

  expect(formalRuns).toHaveLength(90);
  expect(new Set(resultArtifactIds).size).toBe(90);

  for (const shotId of shotIds) {
    const shotRuns = runsForShot(snapshot, shotId);
    expect(shotRuns).toHaveLength(9);
    expect(new Set(shotRuns.map((run) => String(run.input_snapshot.node_key)))).toEqual(
      requiredNodeKeys,
    );

    for (const run of shotRuns) {
      expect(doneStatuses.has(run.status)).toBe(true);
      expect(run.result_artifact_id).not.toBeNull();
      const artifact = artifactsById.get(run.result_artifact_id!);
      expect(artifact).toBeDefined();
      expect(artifact?.produced_by_run_id).toBe(run.id);
      expect(artifact?.object_key).toBeTruthy();
    }
  }
}

test.describe("P0 real 10 Shot browser proof", () => {
  test.skip(
    process.env.P0_REAL_UI !== "1",
    "Set P0_REAL_UI=1 only after authorizing the live Provider run.",
  );

  test("runs Agent Brief through review-gated export without request interception", async ({
    page,
  }) => {
    test.setTimeout(2_700_000);
    const sourceCommit = cleanSourceCommit();
    const sourceDir = path.join(repoRoot, "tmp", "p0-evidence", sourceCommit, "playwright");
    mkdirSync(sourceDir, { recursive: true });
    const requestCounts = { agentBrief: 0, agentPlan: 0, canonical: 0, shotStarts: 0 };
    const browserErrors: string[] = [];
    let projectId = "";

    page.on("pageerror", (error) => browserErrors.push(String(error)));
    page.on("request", (request) => {
      const pathname = new URL(request.url()).pathname;
      if (pathname.endsWith("/brief/generate")) requestCounts.agentBrief += 1;
      if (pathname.endsWith("/plans/generate")) requestCounts.agentPlan += 1;
      if (pathname.endsWith("/characters/lead")) requestCounts.canonical += 1;
      if (pathname.includes("/shots/") && pathname.endsWith("/start"))
        requestCounts.shotStarts += 1;
    });

    try {
      await page.goto("/");
      const health = await browserGet<{ source_commit?: string; db?: string; status?: string }>(
        page,
        "/health",
      );
      expect(health.status).toBe("ok");
      expect(health.db).toBe("up");
      expect(health.source_commit).toBe(sourceCommit);

      await expect(page.getByText("API 就绪", { exact: true })).toBeVisible({ timeout: 30_000 });
      const suffix = `${Date.now()}-${Math.floor(Math.random() * 10000)}`;
      const email = `p0-browser-${suffix}@example.com`;
      const workspaceName = `P0 Browser Workspace ${suffix}`;
      await page.getByLabel("邮箱").fill(email);
      await page.getByLabel("密码").fill("password123");
      await page.getByLabel("显示名").fill("P0 Browser Proof");
      await page.getByRole("button", { name: "创建账号", exact: true }).click();
      await expect(
        page.getByRole("heading", { name: "P0 Browser Proof", exact: true }),
      ).toBeVisible({
        timeout: 60_000,
      });

      await page.getByLabel("新空间名").fill(workspaceName);
      await page.getByRole("button", { name: "创建空间", exact: true }).click();
      await expect(page.getByRole("button", { name: workspaceName, exact: true })).toBeVisible({
        timeout: 60_000,
      });
      await page.getByLabel("项目名").fill(`P0 Real Browser ${suffix}`);
      await page
        .getByLabel("创意想法")
        .fill("A reporter follows an encrypted message through an old city before dawn.");
      await page.getByRole("button", { name: "创建项目", exact: true }).click();
      await expect(page.getByTestId("quick-mode")).toBeVisible({ timeout: 60_000 });
      const match = page.url().match(/projects\/([^/]+)\/quick/);
      if (!match) throw new Error(`project route missing from ${page.url()}`);
      projectId = match[1];
      await page.screenshot({
        path: path.join(sourceDir, "01-project-created.png"),
        fullPage: true,
      });

      await page.getByTestId("agent-brief").click();
      await expect(page.getByTestId("agent-brief-summary")).toBeVisible({ timeout: 360_000 });
      await page.screenshot({ path: path.join(sourceDir, "02-agent-brief.png"), fullPage: true });
      await page.getByTestId("confirm-brief").click();
      await expect
        .poll(() => browserGet<CreationState>(page, `/api/v1/projects/${projectId}/creation-state`))
        .toMatchObject({ brief: { status: "confirmed", source: "agent" } });

      await page.getByTestId("agent-plan").click();
      await expect(page.getByTestId("agent-plan-shots").locator("article")).toHaveCount(10, {
        timeout: 360_000,
      });
      const stateWithPlan = await browserGet<CreationState>(
        page,
        `/api/v1/projects/${projectId}/creation-state`,
      );
      expect(stateWithPlan.plan).toMatchObject({ source: "agent", status: "draft" });
      expect(stateWithPlan.plan?.plan.shots).toHaveLength(10);
      await page.screenshot({ path: path.join(sourceDir, "03-agent-plan.png"), fullPage: true });
      expect(requestCounts.agentBrief).toBe(1);
      expect(requestCounts.agentPlan).toBe(1);

      const [canonicalResponse] = await Promise.all([
        page.waitForResponse(
          (response) =>
            response.request().method() === "POST" &&
            response.url().endsWith(`/api/v1/projects/${projectId}/characters/lead`),
          { timeout: 360_000 },
        ),
        page.getByTestId("register-lead").click(),
      ]);
      expect(canonicalResponse.status()).toBe(200);
      expect(requestCounts.canonical).toBe(1);

      await page.getByTestId("produce-keyframe").click();
      await expect
        .poll(
          async () => {
            const state = await browserGet<CreationState>(
              page,
              `/api/v1/projects/${projectId}/creation-state`,
            );
            const snapshot = await browserGet<ProjectSnapshot>(
              page,
              `/api/v1/projects/${projectId}/snapshot`,
            );
            return {
              materialized: state.plan?.materialized,
              keyframes: snapshot.node_runs.filter(
                (run) => String(run.input_snapshot.node_key ?? "") === "keyframe",
              ).length,
            };
          },
          { timeout: 90_000 },
        )
        .toEqual({ materialized: true, keyframes: 10 });
      await page.screenshot({ path: path.join(sourceDir, "04-keyframes.png"), fullPage: true });

      await page.goto(`/projects/${projectId}/production`);
      await expect(page.getByTestId("production-mode")).toBeVisible({ timeout: 60_000 });
      await expect(page.getByTestId("shot-timeline").locator("button")).toHaveCount(10, {
        timeout: 60_000,
      });
      const shots = await browserGet<Shot[]>(page, `/api/v1/projects/${projectId}/shots`);
      expect(shots).toHaveLength(10);

      for (let index = 0; index < 10; index += 1) {
        const shotId = shots[index].id;
        await page.getByTestId("shot-timeline").locator("button").nth(index).click();
        const [startResponse] = await Promise.all([
          page.waitForResponse(
            (response) =>
              response.request().method() === "POST" &&
              response.url().endsWith(`/api/v1/projects/${projectId}/shots/${shotId}/start`),
            { timeout: 60_000 },
          ),
          page.getByTestId("shot-start").click(),
        ]);
        expect(startResponse.status()).toBe(200);
      }
      expect(requestCounts.shotStarts).toBe(10);

      await expect
        .poll(
          async () => {
            const snapshot = await browserGet<ProjectSnapshot>(
              page,
              `/api/v1/projects/${projectId}/snapshot`,
            );
            const formalRuns = snapshot.node_runs.filter((run) =>
              requiredNodeKeys.has(String(run.input_snapshot.node_key ?? "")),
            );
            return (
              formalRuns.length === 90 && formalRuns.every((run) => doneStatuses.has(run.status))
            );
          },
          { timeout: 2_100_000, intervals: [5_000, 10_000, 20_000] },
        )
        .toBe(true);
      await page.screenshot({
        path: path.join(sourceDir, "05-ten-shot-complete.png"),
        fullPage: true,
      });

      await page.reload();
      await expect(page.getByTestId("production-mode")).toBeVisible({ timeout: 60_000 });
      await expect(page.getByTestId("shot-timeline").locator("button")).toHaveCount(10);
      const refreshedSnapshot = await browserGet<ProjectSnapshot>(
        page,
        `/api/v1/projects/${projectId}/snapshot`,
      );
      assertCompleteShotLineage(
        refreshedSnapshot,
        shots.map((shot) => shot.id),
      );

      for (let index = 0; index < 10; index += 1) {
        const shotId = shots[index].id;
        await page.getByTestId("shot-timeline").locator("button").nth(index).click();
        const [approveResponse] = await Promise.all([
          page.waitForResponse(
            (response) =>
              response.request().method() === "POST" &&
              response.url().endsWith(`/api/v1/projects/${projectId}/shots/${shotId}/approve`),
            { timeout: 60_000 },
          ),
          page.getByTestId("shot-approve").click(),
        ]);
        expect(approveResponse.status()).toBe(200);
        await expect
          .poll(() => browserGet<Shot[]>(page, `/api/v1/projects/${projectId}/shots`))
          .toEqual(
            expect.arrayContaining([
              expect.objectContaining({ id: shotId, status: "review_passed" }),
            ]),
          );
      }

      const reviewedShots = await browserGet<Shot[]>(page, `/api/v1/projects/${projectId}/shots`);
      expect(reviewedShots.filter((shot) => shot.status === "review_passed")).toHaveLength(10);
      const [exportResponse] = await Promise.all([
        page.waitForResponse(
          (response) =>
            response.request().method() === "POST" &&
            response.url().endsWith(`/api/v1/projects/${projectId}/exports`),
          { timeout: 180_000 },
        ),
        page.getByTestId("export-project").click(),
      ]);
      expect(exportResponse.status()).toBe(200);
      const exportResult = (await exportResponse.json()) as ExportResult;
      expect(exportResult.export_id).toBeTruthy();
      expect(exportResult.timeline_hash).toBeTruthy();
      expect(exportResult.export_item_count).toBeGreaterThan(0);
      expect(exportResult.source_artifact_ids).not.toHaveLength(0);
      expect(exportResult.source_node_run_ids).not.toHaveLength(0);
      await page.screenshot({
        path: path.join(sourceDir, "06-export-complete.png"),
        fullPage: true,
      });
    } finally {
      const report = {
        source_commit: sourceCommit,
        project_id: projectId || null,
        no_request_interception: true,
        request_counts: requestCounts,
        browser_errors: browserErrors,
      };
      writeFileSync(
        path.join(sourceDir, "real_ten_shot_browser.json"),
        `${JSON.stringify(report, null, 2)}\n`,
        "utf8",
      );
    }
  });
});
