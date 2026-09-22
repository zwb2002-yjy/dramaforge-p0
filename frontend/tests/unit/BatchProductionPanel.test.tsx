import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BatchProductionPanel } from "../../src/features/production/BatchProductionPanel";

const PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("BatchProductionPanel", () => {
  afterEach(() => vi.restoreAllMocks());

  it("requires a positive per-operation budget and sends bounded Owner authorization", async () => {
    const writes: Record<string, unknown>[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.includes("/batch-production/preview")) {
        const stage = new URL(url, "http://localhost").searchParams.get("stage");
        return json({
          project_id: PROJECT_ID,
          scene_id: null,
          stage,
          fingerprint: "a".repeat(64),
          estimated_provider_calls: stage === "image_keyframe" ? 1 : 0,
          blocked_count: 0,
          currently_queued: 2,
          estimated_queue_seconds: 120,
          items: [],
        });
      }
      if (url.endsWith(`/projects/${PROJECT_ID}/batch-production`)) {
        writes.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return json({
          preview_fingerprint: "a".repeat(64),
          accepted_count: 1,
          node_run_ids: ["11111111-1111-4111-8111-111111111111"],
          statuses: ["queued"],
        });
      }
      return json({});
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <BatchProductionPanel projectId={PROJECT_ID} />
      </QueryClientProvider>,
    );

    const card = await screen.findByTestId("batch-production-image_keyframe");
    const submit = await within(card).findByRole("button", { name: "确认并入队 1 个镜头" });
    const authorization = within(card).getByRole("checkbox");
    expect(submit).toBeDisabled();
    expect(authorization).toBeDisabled();
    expect(
      within(card).getByText("先输入大于 0 的单次预算上限，再勾选 Owner 逐次授权。"),
    ).toBeVisible();
    fireEvent.change(within(card).getByLabelText("单次 Provider 调用预算上限（人民币）"), {
      target: { value: "2.50" },
    });
    expect(authorization).toBeEnabled();
    fireEvent.click(authorization);
    fireEvent.click(submit);

    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]).toMatchObject({
      max_provider_calls: 1,
      max_cost_per_call: "2.50",
      currency: "CNY",
      owner_authorized: true,
    });
  });

  it("lets the Owner open every blocked shot to inspect, edit, and generate", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/batch-production/preview")) {
        const stage = new URL(url, "http://localhost").searchParams.get("stage");
        return json({
          project_id: PROJECT_ID,
          scene_id: null,
          stage,
          fingerprint: stage === "image_keyframe" ? "a".repeat(64) : "b".repeat(64),
          estimated_provider_calls: 0,
          blocked_count: stage === "video" ? 2 : 0,
          currently_queued: 0,
          estimated_queue_seconds: 0,
          items:
            stage === "video"
              ? [
                  {
                    shot_id: "11111111-1111-4111-8111-111111111111",
                    scene_id: "22222222-2222-4222-8222-222222222222",
                    shot_number: 1,
                    ready: false,
                    blocker: "NO_FORMAL_KEYFRAME",
                  },
                  {
                    shot_id: "33333333-3333-4333-8333-333333333333",
                    scene_id: "22222222-2222-4222-8222-222222222222",
                    shot_number: 3,
                    ready: false,
                    blocker: "NO_FORMAL_KEYFRAME",
                  },
                ]
              : [],
        });
      }
      return json({});
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <BatchProductionPanel projectId={PROJECT_ID} />
      </QueryClientProvider>,
    );

    const card = await screen.findByTestId("batch-production-video");
    fireEvent.click(await within(card).findByText("查看 2 个阻塞镜头"));

    const first = within(card).getByRole("link", {
      name: "打开镜头 1：查看、编辑与生成",
    });
    expect(first).toBeVisible();
    expect(first).toHaveAttribute(
      "href",
      `/projects/${PROJECT_ID}/scenes/22222222-2222-4222-8222-222222222222?shotId=11111111-1111-4111-8111-111111111111&tool=generate`,
    );
    expect(within(card).getAllByText(/请先审查并设置正式关键帧/)).toHaveLength(2);
    expect(within(card).getByRole("link", { name: "打开镜头 3：查看、编辑与生成" })).toBeVisible();
  });
});
