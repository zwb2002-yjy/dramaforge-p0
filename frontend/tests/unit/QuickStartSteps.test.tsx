import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterContextProvider,
} from "@tanstack/react-router";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { QuickStartSteps } from "../../src/features/project/QuickStartSteps";
import type { ModelRead, ProjectRead } from "../../src/lib/api";

function model(
  id: string,
  capabilities: string[],
  source: "workspace" | "installed" = "workspace",
) {
  return {
    id,
    provider_id: "p",
    display_name: id,
    enabled: true,
    configured: true,
    available: true,
    capabilities,
    source,
  } satisfies ModelRead;
}

const PROJECT = {
  id: "project-1",
  workspace_id: "ws",
  name: "雨夜来信",
  aspect_ratio: "9:16",
  stage: "production",
} as unknown as ProjectRead;

function renderSteps(
  models: ModelRead[],
  recentProject: ProjectRead | null,
  handlers = { onCreateProject: vi.fn(), onOpenProject: vi.fn() },
) {
  vi.spyOn(globalThis, "fetch").mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify(models), { headers: { "Content-Type": "application/json" } }),
    ),
  );
  const router = createRouter({
    routeTree: createRootRoute(),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <RouterContextProvider router={router}>
      <QueryClientProvider client={client}>
        <QuickStartSteps
          recentProject={recentProject}
          hasProjects={Boolean(recentProject)}
          {...handlers}
        />
      </QueryClientProvider>
    </RouterContextProvider>,
  );
  return handlers;
}

describe("QuickStartSteps", () => {
  afterEach(() => vi.restoreAllMocks());

  it("starts with connecting models when the workspace has none", async () => {
    const handlers = renderSteps([model("litellm/script", ["text.generate"], "installed")], null);
    const first = screen.getByTestId("quick-start-step-1");
    expect(await within(first).findByText("还没有可用的模型")).toBeVisible();
    expect(first).toHaveClass("current");
    expect(within(first).getByRole("link", { name: "去连接模型" })).toHaveAttribute(
      "href",
      "/settings/models",
    );
    const second = screen.getByTestId("quick-start-step-2");
    fireEvent.click(within(second).getByRole("button", { name: "新建项目" }));
    expect(handlers.onCreateProject).toHaveBeenCalledTimes(1);
    expect(
      within(screen.getByTestId("quick-start-step-3")).getByRole("button", {
        name: "进入分镜与生成",
      }),
    ).toBeDisabled();
  });

  it("names the missing model kinds", async () => {
    renderSteps([model("text", ["text.generate"])], null);
    expect(await screen.findByText("还缺图片、视频模型")).toBeVisible();
  });

  it("leads to the storyboard once models and a project exist", async () => {
    const handlers = renderSteps(
      [
        model("text", ["text.generate"]),
        model("binding:image", ["image.generate"]),
        model("binding:video", ["video.image_to_video"]),
      ],
      PROJECT,
    );
    const first = screen.getByTestId("quick-start-step-1");
    expect(await within(first).findByText("文本、图片、视频模型已就绪")).toBeVisible();
    expect(first).toHaveClass("done");
    const third = screen.getByTestId("quick-start-step-3");
    expect(third).toHaveClass("current");
    expect(within(third).getByRole("link", { name: "进入分镜与生成" })).toHaveAttribute(
      "href",
      "/projects/project-1/scenes",
    );
    fireEvent.click(screen.getByRole("button", { name: "继续创作" }));
    expect(handlers.onOpenProject).toHaveBeenCalledWith("project-1");
  });
});
