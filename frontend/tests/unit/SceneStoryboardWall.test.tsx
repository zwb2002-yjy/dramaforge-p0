import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SceneStoryboardWall } from "../../src/features/scenes/SceneStoryboardWall";

vi.mock("@tanstack/react-router", () => ({
  Link: ({
    to,
    params,
    children,
  }: {
    to: string;
    params: { projectId: string };
    children: ReactNode;
  }) => <a href={to.replace("$projectId", params.projectId)}>{children}</a>,
}));

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function mockBackend() {
  const calls: Array<{ method: string; url: string }> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ method, url });
    if (url.endsWith("/scenes") && method === "GET") {
      return json([
        {
          id: "scene-1",
          project_id: "project-1",
          episode_id: "episode-1",
          episode_number: 1,
          scene_number: 1,
          location_name: "Studio",
          time_of_day: "day",
          synopsis: "intro",
          version: 1,
          shot_count: 2,
          formal_keyframe_count: 1,
          formal_video_count: 0,
          risk_count: 1,
          representative_artifact: null,
        },
        {
          id: "scene-2",
          project_id: "project-1",
          episode_id: "episode-1",
          episode_number: 1,
          scene_number: 2,
          location_name: "Street",
          time_of_day: "night",
          synopsis: "",
          version: 1,
          shot_count: 1,
          formal_keyframe_count: 0,
          formal_video_count: 0,
          risk_count: 0,
          representative_artifact: null,
        },
      ]);
    }
    if (url.endsWith("/workspace") && method === "GET") {
      const count = url.includes("scene-1") ? 2 : 1;
      return json({
        shots: Array.from({ length: count }, (_, index) => ({
          id: "shot-" + index,
          shot_number: index + 1,
          shot_type: "wide",
          visual_description: "Test shot",
          dialogue: "",
          duration_seconds: "3",
          formal_keyframe_artifact_id: url.includes("scene-1") && index === 0 ? "frame-1" : null,
          formal_video_artifact_id: null,
        })),
      });
    }
    if (url.includes("/copy") && method === "POST") {
      return json({ id: "scene-3" }, 201);
    }
    return json({});
  });
  return calls;
}

describe("SceneStoryboardWall", () => {
  it("renders scene cards with counts and status", async () => {
    mockBackend();
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <SceneStoryboardWall projectId="project-1" />
      </QueryClientProvider>,
    );
    const cards = await screen.findAllByTestId("scene-card");
    expect(cards).toHaveLength(2);
    expect(screen.getByText("Studio")).toBeInTheDocument();
    expect(screen.getByText(/1.1 · 白天/)).toBeInTheDocument();
    expect(screen.getByText("2 镜头")).toBeInTheDocument();
    expect(screen.getByText(/1 风险/)).toBeInTheDocument();
  });

  it("does not show an empty state while scenes are still loading", async () => {
    let resolveFetch: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <SceneStoryboardWall projectId="project-1" />
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("scene-wall-loading")).toHaveTextContent("正在读取场景");
    expect(screen.queryByText("先写下你的故事")).not.toBeInTheDocument();

    resolveFetch?.(await json([]));
    expect(await screen.findByText("先写下你的故事")).toBeInTheDocument();
    expect(screen.queryByTestId("scene-wall-loading")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "去写剧本" })).toHaveAttribute(
      "href",
      "/projects/project-1/script",
    );
  });

  it("copies a scene on demand", async () => {
    const calls = mockBackend();
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <SceneStoryboardWall projectId="project-1" />
      </QueryClientProvider>,
    );
    await screen.findAllByTestId("scene-card");
    fireEvent.click(screen.getAllByRole("button", { name: "复制场景" })[0]);
    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.url.includes("/copy"))).toBe(true);
    });
  });
});

afterEach(() => vi.restoreAllMocks());
