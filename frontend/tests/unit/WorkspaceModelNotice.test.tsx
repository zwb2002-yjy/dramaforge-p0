import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterContextProvider,
} from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkspaceModelNotice } from "../../src/features/project/WorkspaceModelNotice";
import type { ModelRead } from "../../src/lib/api";
import { WORKSPACE_MODEL_ROLES } from "../../src/lib/workspaceModelRoles";

const models: ModelRead[] = WORKSPACE_MODEL_ROLES.map((role) => ({
  id: role.id,
  provider_id: "provider",
  display_name: role.label,
  enabled: true,
  configured: true,
  available: true,
  source: "workspace",
  capabilities: [...role.capabilities],
}));
const bindings: Record<string, { model_id: string; enabled?: boolean }> = Object.fromEntries(
  WORKSPACE_MODEL_ROLES.flatMap((role) => role.slots.map((slot) => [slot, { model_id: role.id }])),
);

function mount({
  catalog = models,
  defaults = true,
  failed = false,
  failedRead = "all",
  saved = bindings,
} = {}) {
  let readFailed = failed;
  const reads: string[] = [];
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const path = String(input);
    reads.push(path);
    expect(new Headers(init?.headers).get("X-Workspace-Id")).toBe("ws");
    const body = path.endsWith("/models")
      ? catalog
      : path.endsWith("/model-profiles")
        ? defaults
          ? [{ id: "default", is_default: true }]
          : []
        : { id: "default", bindings: saved };
    const fail = readFailed && (failedRead === "all" || path.endsWith(failedRead));
    return Promise.resolve(
      new Response(JSON.stringify(fail ? { detail: "failed" } : body), {
        status: fail ? 500 : 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  const router = createRouter({
    routeTree: createRootRoute(),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <RouterContextProvider router={router}>
      <QueryClientProvider client={client}>
        <WorkspaceModelNotice workspaceId="ws" returnTo="/?panel=recent" />
      </QueryClientProvider>
    </RouterContextProvider>,
  );
  return {
    fetch,
    reads,
    recover: () => {
      readFailed = false;
    },
  };
}

afterEach(() => vi.restoreAllMocks());
describe("workspace model configuration notice", () => {
  it("hides only after all mainchain slots have available workspace models", async () => {
    const { reads } = mount();
    expect(screen.getByText("正在读取模型配置…")).toBeVisible();
    await waitFor(() => expect(reads).toHaveLength(3));
    await waitFor(() =>
      expect(screen.queryByTestId("workspace-model-notice")).not.toBeInTheDocument(),
    );
  });
  it("distinguishes unconfigured defaults from an empty catalog", async () => {
    mount({ defaults: false });
    expect(await screen.findByText("尚未配置默认模型（文本／图片／视频）")).toBeVisible();
    expect(screen.queryByText(/缺少可用/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "配置模型" })).toHaveAttribute(
      "href",
      expect.stringContaining("returnTo="),
    );
  });
  it("excludes installed aliases, unavailable bindings and unrelated capabilities", async () => {
    mount({
      catalog: [
        { ...models[0], source: "installed" },
        { ...models[1], available: false },
        { ...models[2], capabilities: ["audio.tts"] },
      ],
    });
    expect(await screen.findByText("缺少可用的文本／图片／视频模型")).toBeVisible();
  });
  it.each([
    "video.text_to_video",
    "video.image_to_video",
    "video.last_frame_to_video",
    "video.first_last_frame",
    "video.reference_to_video",
  ])("accepts a saved video model supporting %s", async (capability) => {
    const { reads } = mount({
      catalog: [...models.slice(0, 2), { ...models[2], capabilities: [capability] }],
    });
    await waitFor(() => expect(reads).toHaveLength(3));
    await waitFor(() =>
      expect(screen.queryByTestId("workspace-model-notice")).not.toBeInTheDocument(),
    );
  });
  it("does not accept a saved unavailable identity when another model is available", async () => {
    mount({ saved: { ...bindings, "video.shot": { model_id: "missing" } } });
    expect(await screen.findByText("缺少可用的视频模型")).toBeVisible();
  });
  it.each(["all", "/models", "/model-profiles", "/model-profiles/default"])(
    "reports failed %s reads and retries existing reads only",
    async (failedRead) => {
      const state = mount({ failed: true, failedRead });
      expect(await screen.findByText("无法读取模型配置")).toBeVisible();
      expect(screen.queryByText(/缺少可用|尚未配置/)).not.toBeInTheDocument();
      state.recover();
      fireEvent.click(screen.getByRole("button", { name: "重试" }));
      await waitFor(() =>
        expect(screen.queryByTestId("workspace-model-notice")).not.toBeInTheDocument(),
      );
      expect(
        state.fetch.mock.calls.every(([, init]) => !init?.method || init.method === "GET"),
      ).toBe(true);
    },
  );
  it("requires enabled default bindings instead of accepting disabled slots", async () => {
    mount({ saved: { ...bindings, "planning.script": { model_id: "llm", enabled: false } } });
    expect(await screen.findByText("尚未配置默认模型（文本）")).toBeVisible();
  });
  it.each(WORKSPACE_MODEL_ROLES)("reports only the missing $label role", async (role) => {
    mount({ catalog: models.filter((model) => model.id !== role.id) });
    expect(await screen.findByText(`缺少可用的${role.label}`)).toBeVisible();
    expect(screen.queryByText(/尚未配置/)).not.toBeInTheDocument();
  });
});
