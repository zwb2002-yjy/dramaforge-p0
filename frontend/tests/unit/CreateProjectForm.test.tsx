import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { CreateProjectForm } from "../../src/features/project/CreateProjectForm";
import type { WorkspaceRead } from "../../src/lib/api";

const workspace: WorkspaceRead = {
  id: "workspace-1",
  name: "创作空间",
  owner_user_id: "owner-1",
  created_at: "2026-09-17T00:00:00Z",
  updated_at: "2026-09-17T00:00:00Z",
  version: 1,
};
function setup() {
  const writes: unknown[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (String(input).endsWith("/auth/csrf"))
      return new Response(JSON.stringify({ csrf_token: "test" }));
    if (init?.method === "POST") writes.push(JSON.parse(String(init.body)));
    return new Response(JSON.stringify({ id: "project-new" }));
  });
  const props = {
    open: true,
    workspaceId: workspace.id,
    workspaces: [workspace],
    onWorkspaceChange: vi.fn(),
    onCancel: vi.fn(),
    onCreated: vi.fn(),
  };
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <CreateProjectForm {...props} />
    </QueryClientProvider>,
  );
  return {
    writes,
    props,
    rerender: (open: boolean) =>
      view.rerender(
        <QueryClientProvider client={client}>
          <CreateProjectForm {...props} open={open} />
        </QueryClientProvider>,
      ),
  };
}
afterEach(() => vi.restoreAllMocks());

it("creates with explicit defaults only after submission and trims the project name", async () => {
  const { writes, props } = setup();
  expect(screen.getByLabelText("项目名")).toHaveFocus();
  fireEvent.change(screen.getByLabelText("项目名"), { target: { value: "  雨夜  " } });
  expect(writes).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "创建并进入剧本" }));
  await waitFor(() => expect(props.onCreated).toHaveBeenCalledWith("project-new"));
  expect(writes).toEqual([
    {
      workspace_id: workspace.id,
      name: "雨夜",
      aspect_ratio: "9:16",
      start_type: "FREE",
      template_key: null,
      director_autonomy: "ASSIST",
    },
  ]);
});

it("preserves the draft on cancel/reopen and prevents whitespace-only submissions", () => {
  const { writes, rerender } = setup();
  fireEvent.change(screen.getByLabelText("项目名"), { target: { value: "保留的草稿" } });
  rerender(false);
  expect(screen.queryByRole("textbox", { name: "项目名" })).not.toBeInTheDocument();
  rerender(true);
  expect(screen.getByLabelText("项目名")).toHaveValue("保留的草稿");
  fireEvent.change(screen.getByLabelText("项目名"), { target: { value: "   " } });
  expect(screen.getByRole("button", { name: "创建并进入剧本" })).toBeDisabled();
  expect(writes).toEqual([]);
});

it("submits the selected template and autonomy, not hidden defaults", async () => {
  const { writes, props } = setup();
  fireEvent.click(screen.getByText("创作选项"));
  fireEvent.change(screen.getByLabelText("创作起点"), { target: { value: "TEMPLATE" } });
  fireEvent.change(screen.getByLabelText("创作模板"), { target: { value: "single_monologue_v1" } });
  fireEvent.change(screen.getByLabelText("导演参与度"), { target: { value: "MANUAL" } });
  fireEvent.click(screen.getByRole("button", { name: "创建并进入剧本" }));
  await waitFor(() => expect(props.onCreated).toHaveBeenCalled());
  expect(writes[0]).toMatchObject({
    start_type: "TEMPLATE",
    template_key: "single_monologue_v1",
    director_autonomy: "MANUAL",
  });
});
