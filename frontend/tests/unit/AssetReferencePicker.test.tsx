import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssetReferencePicker } from "../../src/components/assets/AssetReferencePicker";

function renderPicker() {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <AssetReferencePicker projectId="project-1" shotId="shot-1" purpose="identity" />
    </QueryClientProvider>,
  );
}

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function mockBackend() {
  const calls: Array<{ method: string; url: string; body?: unknown }> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ method, url, body: init?.body });
    if (url.endsWith("/assets") && method === "GET") {
      return json([
        {
          id: "asset-linmo",
          project_id: "project-1",
          kind: "character",
          name: "林墨",
          description: "",
          metadata: {},
          status: "active",
          version: 1,
          created_at: "",
          updated_at: "",
        },
      ]);
    }
    if (url.endsWith("/shots/shot-1/references") && method === "GET") {
      return json([
        {
          id: "binding-1",
          project_id: "project-1",
          shot_id: "shot-1",
          shot_experiment_id: null,
          stage: "both",
          asset_id: "asset-linmo",
          asset_version_id: null,
          artifact_id: null,
          resolution_mode: "current_formal",
          purpose: "identity",
          label: "@林墨",
          sort_order: 0,
          metadata: {},
          version: 1,
          created_at: "",
          updated_at: "",
        },
      ]);
    }
    if (url.endsWith("/references/resolve") && method === "POST") {
      return json([
        {
          purpose: "identity",
          role: "front_face",
          artifact_id: "artifact-1",
          label: "@林墨",
          source: "current_formal",
          asset_id: "asset-linmo",
          asset_version_id: "version-1",
        },
      ]);
    }
    if (url.includes("/references") && method === "POST") {
      return json(
        {
          id: "binding-2",
          project_id: "project-1",
          shot_id: "shot-1",
          shot_experiment_id: null,
          stage: "both",
          asset_id: "asset-linmo",
          asset_version_id: null,
          artifact_id: null,
          resolution_mode: "current_formal",
          purpose: "identity",
          label: "@林墨",
          sort_order: 0,
          metadata: {},
          version: 1,
          created_at: "",
          updated_at: "",
        },
        201,
      );
    }
    return json({});
  });
  return calls;
}

describe("AssetReferencePicker", () => {
  it("lists existing business-purpose bindings", async () => {
    mockBackend();
    renderPicker();
    expect(await screen.findByText(/@林墨/)).toBeInTheDocument();
    const list = screen.getByTestId("binding-list");
    expect(list).toHaveTextContent("identity · current_formal");
    expect(screen.getByText("asset-linmo")).toBeInTheDocument();
  });

  it("adds a binding for the selected asset", async () => {
    const calls = mockBackend();
    renderPicker();
    await screen.findByRole("option", { name: /林墨/ });
    fireEvent.change(screen.getByLabelText("选择资产"), { target: { value: "asset-linmo" } });
    fireEvent.click(screen.getByRole("button", { name: "添加引用" }));
    await waitFor(() => {
      const post = calls.find((call) => call.method === "POST" && call.url.includes("/references"));
      expect(post).toBeTruthy();
    });
  });

  it("resolves the shot references to frozen artifact ids", async () => {
    mockBackend();
    renderPicker();
    await screen.findByText(/@林墨/);
    fireEvent.click(screen.getByRole("button", { name: "解析引用" }));
    const resolved = await screen.findByTestId("resolved-references");
    expect(resolved).toHaveTextContent("identity / front_face / current_formal");
    expect(resolved).toHaveTextContent("artifact-1");
  });
});

afterEach(() => vi.restoreAllMocks());
