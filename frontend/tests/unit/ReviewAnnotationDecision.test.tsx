import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReviewWorkspace } from "../../src/features/review/ReviewWorkspace";

const shot = {
  id: "s1",
  project_id: "p1",
  scene_id: "scene-1",
  shot_number: 1,
  duration_seconds: "5",
  version: 4,
  visual_description: "Shot s1",
  formal_video_artifact_id: null,
  formal_keyframe_artifact_id: null,
};

const annotation = (status: string) => ({
  id: "note-1",
  shot_id: "s1",
  artifact_id: null,
  target_kind: "shot",
  time_start: null,
  time_end: null,
  x: null,
  y: null,
  width: null,
  height: null,
  note: "检查人物一致性",
  severity: "warning",
  status,
  created_by: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  resolved_at: null,
});

const json = (body: unknown, status = 200) =>
  Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );

afterEach(() => vi.restoreAllMocks());

function renderWorkspace() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const root = createRootRoute({
    component: () => (
      <QueryClientProvider client={client}>
        <ReviewWorkspace projectId="p1" />
      </QueryClientProvider>
    ),
  });
  const router = createRouter({
    routeTree: root,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  render(<RouterProvider router={router} />);
}

describe("Review annotation decisions", () => {
  it("resolves and reopens an annotation through the decision endpoint", async () => {
    const decisions: Array<{ url: string; body: unknown }> = [];
    let status = "open";
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
      if (url.endsWith("/shots")) return json([shot]);
      if (url.endsWith("/workbench")) return json({ shot });
      if (url.includes("/annotations/") && url.endsWith("/decision") && method === "POST") {
        const body = JSON.parse(String(init?.body));
        decisions.push({ url, body });
        status = body.status;
        return json(annotation(status));
      }
      if (url.endsWith("/annotations")) return json([annotation(status)]);
      return json({}, 404);
    });

    renderWorkspace();

    const row = await screen.findByTestId("review-annotation-row");
    expect(row).toHaveTextContent("检查人物一致性");
    expect(row).toHaveTextContent("待处理");

    fireEvent.click(screen.getByTestId("review-annotation-decision"));
    await waitFor(() =>
      expect(decisions).toEqual([
        {
          url: "/api/v1/projects/p1/shots/s1/annotations/note-1/decision",
          body: { status: "resolved" },
        },
      ]),
    );
    await waitFor(() =>
      expect(screen.getByTestId("review-annotation-row")).toHaveTextContent("已解决"),
    );

    fireEvent.click(screen.getByTestId("review-annotation-decision"));
    await waitFor(() => expect(decisions[1]?.body).toEqual({ status: "open" }));
  });
});
