import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterContextProvider,
} from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BatchFillActions } from "../../src/features/production/BatchFillActions";

const PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SCENE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

type Item = {
  shot_id: string;
  scene_id: string;
  shot_number: number;
  disposition: "ready" | "skipped" | "blocked";
  reason: string | null;
};

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function item(n: number, disposition: Item["disposition"], reason: string | null = null): Item {
  return {
    shot_id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    scene_id: SCENE_ID,
    shot_number: n,
    disposition,
    reason,
  };
}

function preview(stage: string, items: Item[], fingerprint = "a".repeat(64)) {
  return {
    project_id: PROJECT_ID,
    scene_id: SCENE_ID,
    stage,
    fingerprint,
    ready_count: items.filter((entry) => entry.disposition === "ready").length,
    skipped_count: items.filter((entry) => entry.disposition === "skipped").length,
    blocked_count: items.filter((entry) => entry.disposition === "blocked").length,
    items,
  };
}

function renderActions() {
  const router = createRouter({
    routeTree: createRootRoute(),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <RouterContextProvider router={router}>
      <QueryClientProvider client={client}>
        <BatchFillActions projectId={PROJECT_ID} sceneId={SCENE_ID} />
      </QueryClientProvider>
    </RouterContextProvider>,
  );
}

describe("BatchFillActions", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows fill counts and authorizes exactly the ready operations without money fields", async () => {
    const writes: Record<string, unknown>[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.includes("/batch-production/preview")) {
        const stage = new URL(url, "http://localhost").searchParams.get("stage")!;
        return json(
          stage === "image_keyframe"
            ? preview(stage, [
                item(1, "ready"),
                item(2, "ready"),
                item(3, "skipped", "ALREADY_FORMAL"),
                item(4, "skipped", "STAGE_ALREADY_ACTIVE"),
                item(5, "blocked", "MODEL_BINDING_MISSING"),
              ])
            : preview(stage, [item(1, "skipped", "ALREADY_FORMAL")]),
        );
      }
      if (url.endsWith(`/projects/${PROJECT_ID}/batch-production`)) {
        writes.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return json({
          preview_fingerprint: "a".repeat(64),
          accepted_count: 2,
          node_run_ids: [],
          statuses: ["queued", "queued"],
        });
      }
      return json({});
    });
    renderActions();

    const fill = await screen.findByRole("button", { name: "补齐画面 · 2" });
    expect(await screen.findByRole("button", { name: "视频已齐" })).toBeDisabled();
    fireEvent.click(fill);

    const dialog = await screen.findByRole("dialog", { name: "补齐画面" });
    expect(within(dialog).getByText("已有正式版本")).toBeVisible();
    expect(within(dialog).getByText("正在生成")).toBeVisible();
    expect(within(dialog).getByText("未选择模型")).toBeVisible();
    expect(within(dialog).getByRole("link", { name: "镜头 5" })).toBeVisible();
    expect(within(dialog).getByRole("link", { name: "去设置模型" })).toBeVisible();
    expect(within(dialog).queryByText(/预算|¥|CNY/)).toBeNull();

    fireEvent.click(within(dialog).getByRole("button", { name: "确认生成 2 个" }));
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]).toEqual({
      stage: "image_keyframe",
      scene_id: SCENE_ID,
      preview_fingerprint: "a".repeat(64),
      batch_key: `${SCENE_ID}:image_keyframe:${"a".repeat(24)}`,
      max_provider_calls: 2,
      owner_authorized: true,
    });
    expect(await screen.findByText("已创建 2 个任务")).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps the dialog open and refreshes when the preview went stale", async () => {
    let previewReads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.includes("/batch-production/preview")) {
        const stage = new URL(url, "http://localhost").searchParams.get("stage")!;
        if (stage === "image_keyframe") previewReads += 1;
        return json(preview(stage, [item(1, "ready")]));
      }
      if (url.endsWith(`/projects/${PROJECT_ID}/batch-production`)) {
        return json(
          { code: "CONFLICT", message: "stale", details: { code: "BATCH_PREVIEW_STALE" } },
          409,
        );
      }
      return json({});
    });
    renderActions();

    fireEvent.click(await screen.findByRole("button", { name: "补齐画面 · 1" }));
    const dialog = await screen.findByRole("dialog", { name: "补齐画面" });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认生成 1 个" }));
    expect(await within(dialog).findByText(/镜头状态已变化/)).toBeVisible();
    await waitFor(() => expect(previewReads).toBeGreaterThan(1));
  });
});
