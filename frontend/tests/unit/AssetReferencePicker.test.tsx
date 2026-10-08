import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssetReferencePicker } from "../../src/components/assets/AssetReferencePicker";

const PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SHOT_ID = "11111111-1111-4111-8111-111111111111";
const ACTIVE_ASSET = "22222222-2222-4222-8222-222222222222";
const RECYCLED_ASSET = "33333333-3333-4333-8333-333333333333";
const BINDING_ID = "44444444-4444-4444-8444-444444444444";

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const ASSETS = [
  {
    id: ACTIVE_ASSET,
    project_id: PROJECT_ID,
    kind: "character",
    name: "林墨",
    description: "",
    status: "active",
    tags: [],
    version: 1,
  },
  {
    id: RECYCLED_ASSET,
    project_id: PROJECT_ID,
    kind: "character",
    name: "废弃角色",
    description: "",
    status: "recycled",
    tags: [],
    version: 1,
  },
];

const BINDING = {
  id: BINDING_ID,
  shot_id: SHOT_ID,
  purpose: "identity",
  asset_id: ACTIVE_ASSET,
  asset_version_id: null,
  artifact_id: null,
  resolution_mode: "current_formal",
  label: "@林墨",
  stage: "both",
  version: 1,
  created_at: "2026-09-18T00:00:00Z",
  updated_at: "2026-09-18T00:00:00Z",
};

function mockApi(resolved: unknown[]) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
    if (url.endsWith(`/projects/${PROJECT_ID}/assets`)) return json(ASSETS);
    if (url.includes("/references/resolve")) return json(resolved);
    if (url.endsWith(`/shots/${SHOT_ID}/references`) && init?.method !== "POST") {
      return json([BINDING]);
    }
    return json([]);
  });
}

function renderPicker() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AssetReferencePicker projectId={PROJECT_ID} shotId={SHOT_ID} />
    </QueryClientProvider>,
  );
}

describe("AssetReferencePicker recycled assets and empty resolution", () => {
  afterEach(() => vi.restoreAllMocks());

  it("offers only production assets and never the recycled one", async () => {
    mockApi([]);
    renderPicker();

    await waitFor(() => expect(screen.getByTestId("asset-reference-picker")).toBeInTheDocument());
    fireEvent.click(await screen.findByRole("button", { name: "添加" }));
    const options = await screen.findByLabelText("选择资产");
    const values = Array.from(options.querySelectorAll("option")).map(
      (option) => (option as HTMLOptionElement).value,
    );
    expect(values).toContain(ACTIVE_ASSET);
    expect(values).not.toContain(RECYCLED_ASSET);
    expect(await screen.findByText(/@林墨/)).toBeInTheDocument();
  });

  it("marks a binding that resolves to nothing and explains what to do", async () => {
    mockApi([]);
    renderPicker();

    const invalid = await screen.findByTestId(`reference-binding-invalid-${BINDING_ID}`);
    expect(invalid).toHaveTextContent("已失效：解析不到素材");
    expect(screen.getByTestId("reference-binding-invalid-hint")).toHaveTextContent(
      "已失效的引用不会进入生成",
    );
    expect(screen.getByTestId("resolved-references")).toHaveTextContent(
      "已绑定的参考当前解析不到内容",
    );
  });

  it("keeps a binding valid while it still resolves to concrete material", async () => {
    mockApi([
      {
        purpose: "identity",
        role: "identity",
        artifact_id: "55555555-5555-4555-8555-555555555555",
        label: "@林墨",
        source: "current_formal",
        asset_id: ACTIVE_ASSET,
        asset_version_id: null,
      },
    ]);
    renderPicker();

    await waitFor(() =>
      expect(screen.getByTestId("resolved-references")).toHaveTextContent(
        "本次生成将使用的参考素材",
      ),
    );
    expect(screen.queryByTestId(`reference-binding-invalid-${BINDING_ID}`)).not.toBeInTheDocument();
    expect(screen.queryByTestId("reference-binding-invalid-hint")).not.toBeInTheDocument();
  });
});

it("persists a new binding after existing reference slots instead of reusing sort_order zero", async () => {
  const calls: Array<{ method: string; url: string; body?: Record<string, unknown> }> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({
      method,
      url,
      body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined,
    });
    if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
    if (url.endsWith(`/projects/${PROJECT_ID}/assets`)) return json(ASSETS);
    if (url.includes("/references/resolve")) return json([]);
    if (url.endsWith(`/shots/${SHOT_ID}/references`)) {
      if (method === "POST") return json({ ...BINDING, id: "new-binding", sort_order: 8 }, 201);
      return json([{ ...BINDING, sort_order: 7 }]);
    }
    return json([]);
  });
  renderPicker();
  fireEvent.click(await screen.findByRole("button", { name: "添加" }));
  fireEvent.change(await screen.findByLabelText("选择资产"), { target: { value: ACTIVE_ASSET } });
  fireEvent.click(screen.getByRole("button", { name: "添加引用" }));
  await waitFor(() => {
    const post = calls.find((call) => call.method === "POST" && call.url.endsWith("/references"));
    expect(post?.body?.sort_order).toBe(8);
    expect(post?.body?.asset_id).toBe(ACTIVE_ASSET);
  });
});
