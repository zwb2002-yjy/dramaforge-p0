import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssetMentionInput } from "../../src/components/assets/AssetMentionInput";

type Binding = {
  id: string;
  label: string;
  asset_id: string;
  purpose: string;
  stage: string;
  sort_order: number;
  version: number;
};
function setup(
  options: {
    value?: string;
    failCreate?: boolean;
    failDelete?: boolean;
    bound?: boolean;
    duplicate?: boolean;
    resolved?: boolean;
  } = {},
) {
  const bindings: Binding[] = options.bound
    ? [
        {
          id: "binding-1",
          label: "@林墨",
          asset_id: "asset-linmo",
          purpose: "identity",
          stage: "image",
          sort_order: 0,
          version: 1,
        },
      ]
    : [];
  const writes: Array<{ method: string; body: Record<string, unknown> }> = [];
  const ready = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const path = String(input);
    const method = init?.method ?? "GET";
    const json = (body: unknown, status = 200) =>
      Promise.resolve(
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      );
    if (path.endsWith("/assets"))
      return json([
        {
          id: "asset-linmo",
          project_id: "project-1",
          kind: "character",
          name: "林墨",
          status: "active",
        },
        ...(options.duplicate
          ? [
              {
                id: "asset-other",
                project_id: "project-1",
                kind: "character",
                name: "林墨",
                status: "active",
              },
            ]
          : []),
        {
          id: "asset-retired",
          project_id: "project-1",
          kind: "character",
          name: "林墨旧稿",
          status: "recycled",
        },
        {
          id: "asset-foreign",
          project_id: "another-project",
          kind: "character",
          name: "林墨别项目",
          status: "active",
        },
      ]);
    if (path.endsWith("/auth/csrf")) return json({ csrf_token: "csrf" });
    if (path.endsWith("/references/resolve"))
      return json(
        options.resolved === false
          ? []
          : bindings.map((binding) => ({
              binding_id: binding.id,
              artifact_id: `artifact-${binding.asset_id}`,
              stage: binding.stage,
              asset_id: binding.asset_id,
            })),
      );
    if (path.endsWith("/references") && method === "GET") return json(bindings);
    if (method === "POST") {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      writes.push({ method, body });
      if (options.failCreate) return json({ code: "CONFLICT", detail: "引用保存冲突" }, 409);
      const row = { id: `binding-${bindings.length + 1}`, ...body, version: 1 } as Binding;
      bindings.push(row);
      return json(row, 201);
    }
    if (method === "DELETE") {
      writes.push({ method, body: {} });
      if (options.failDelete) return json({ code: "CONFLICT", detail: "删除引用失败" }, 409);
      bindings.splice(0, bindings.length);
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return json({});
  });
  function Harness() {
    const [value, setValue] = useState(options.value ?? "");
    return (
      <AssetMentionInput
        projectId="project-1"
        shotId="shot-1"
        stage="image"
        value={value}
        onChange={setValue}
        onValidityChange={ready}
      />
    );
  }
  render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
  return { bindings, writes, ready };
}
const input = () => screen.getByRole("textbox", { name: "提示词（@ 引用资产）" });
afterEach(() => vi.restoreAllMocks());

describe("persisted Asset mentions", () => {
  it("offers only current-project active Assets after an @ token and supports keyboard selection", async () => {
    const state = setup();
    fireEvent.change(input(), { target: { value: "角色" } });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    fireEvent.change(input(), { target: { value: "角色 @林" } });
    const list = await screen.findByRole("listbox");
    await waitFor(() => expect(within(list).getAllByRole("option")).toHaveLength(1));
    fireEvent.keyDown(input(), { key: "Enter" });
    await waitFor(() => expect(input()).toHaveValue("角色 @林墨 "));
    expect(state.writes).toEqual([
      {
        method: "POST",
        body: {
          asset_id: "asset-linmo",
          asset_version_id: null,
          artifact_id: null,
          purpose: "identity",
          resolution_mode: "current_formal",
          label: "@林墨",
          stage: "image",
          sort_order: 0,
        },
      },
    ]);
    await waitFor(() => expect(screen.queryByTestId("mention-unresolved")).not.toBeInTheDocument());
    expect(state.ready).toHaveBeenLastCalledWith(true);
  });
  it("does not claim resolution or erase the typed draft after a refused binding write", async () => {
    const state = setup({ failCreate: true });
    fireEvent.change(input(), { target: { value: "@林" } });
    await screen.findByRole("option");
    fireEvent.keyDown(input(), { key: "Enter" });
    await screen.findByText(/引用保存失败/);
    expect(input()).toHaveValue("@林");
    expect(screen.getByTestId("mention-unresolved")).toBeInTheDocument();
    expect(state.writes).toHaveLength(1);
    expect(state.bindings).toHaveLength(0);
  });
  it("restores the saved label from server bindings without new writes", async () => {
    const state = setup({ bound: true, value: "@林墨 walks" });
    await waitFor(() => expect(state.ready).toHaveBeenLastCalledWith(true));
    expect(screen.queryByTestId("mention-unresolved")).not.toBeInTheDocument();
    expect(state.writes).toEqual([]);
  });
  it("keeps a stored but unresolved binding visibly invalid", async () => {
    const state = setup({ bound: true, value: "@林墨 walks", resolved: false });
    await screen.findByTestId("mention-unresolved");
    await waitFor(() => expect(state.ready).toHaveBeenLastCalledWith(false));
    expect(state.writes).toEqual([]);
  });
  it("binds the selected duplicate-name Asset by ID and gives its label a distinct identity", async () => {
    const state = setup({ bound: true, duplicate: true });
    fireEvent.change(input(), { target: { value: "@林" } });
    const list = await screen.findByRole("listbox");
    await waitFor(() => expect(within(list).getAllByRole("option")).toHaveLength(2));
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.keyDown(input(), { key: "Enter" });
    await waitFor(() => expect(input()).toHaveValue("@林墨_2 "));
    expect(state.writes[0].body).toMatchObject({
      asset_id: "asset-other",
      label: "@林墨_2",
      sort_order: 1,
    });
  });
  it("keyboard deletion removes the real binding and marks only the prompt draft changed", async () => {
    const state = setup({ bound: true, value: "@林墨 walks" });
    const remove = await screen.findByRole("button", { name: "删除提示词引用 @林墨" });
    fireEvent.keyDown(remove, { key: "Delete" });
    await waitFor(() => expect(input()).toHaveValue(" walks"));
    expect(state.writes.map((write) => write.method)).toEqual(["DELETE"]);
    expect(state.bindings).toEqual([]);
  });
  it("a failed delete keeps the original binding and prompt", async () => {
    const state = setup({ bound: true, value: "@林墨 walks", failDelete: true });
    fireEvent.click(await screen.findByRole("button", { name: "删除提示词引用 @林墨" }));
    await screen.findByText(/引用保存失败/);
    expect(input()).toHaveValue("@林墨 walks");
    expect(state.bindings).toHaveLength(1);
  });
});
