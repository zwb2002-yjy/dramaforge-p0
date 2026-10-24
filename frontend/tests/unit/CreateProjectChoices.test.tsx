import { findSelectOption, selectValue } from "./selectValue";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CreateProjectForm } from "../../src/features/project/CreateProjectForm";
import { createProject } from "../../src/lib/api";
import { fetchProjectCreativeOptions } from "../../src/features/project/creative-options";
vi.mock("../../src/lib/api", async (original) => ({
  ...(await original<typeof import("../../src/lib/api")>()),
  createProject: vi.fn(),
}));
vi.mock("../../src/features/project/creative-options", () => ({
  fetchProjectCreativeOptions: vi.fn(),
}));
afterEach(() => vi.clearAllMocks());
function show() {
  const onCreated = vi.fn();
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CreateProjectForm
        open
        workspaceId="w1"
        workspaces={[{ id: "w1", name: "我的空间" }] as never}
        onWorkspaceChange={vi.fn()}
        onCancel={vi.fn()}
        onCreated={onCreated}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "风格与类型（可选）" }));
  return onCreated;
}
it("submits the explicit type and style in the single creation request", async () => {
  vi.mocked(fetchProjectCreativeOptions).mockResolvedValue({
    genres: [{ key: "drama", display_name: "剧情短片" }],
    styles: [{ key: "film", display_name: "电影写实" }],
  } as never);
  vi.mocked(createProject).mockResolvedValue({ id: "p1" } as never);
  const onCreated = show();
  await findSelectOption(screen.getByLabelText("画面风格"), "电影写实");
  await selectValue(screen.getByRole("combobox", { name: "创作类型" }), "drama");
  await selectValue(screen.getByRole("combobox", { name: "画面风格" }), "film");
  fireEvent.submit(screen.getByRole("textbox", { name: "项目名" }).closest("form")!);
  await waitFor(() => expect(createProject).toHaveBeenCalledTimes(1));
  expect(createProject).toHaveBeenCalledWith(
    expect.objectContaining({ genre_key: "drama", style_key: "film", workspace_id: "w1" }),
  );
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith("p1"));
});
it("shows a catalog error and does not invent selectable styles", async () => {
  vi.mocked(fetchProjectCreativeOptions).mockRejectedValue(new Error("offline"));
  show();
  expect(await screen.findByRole("alert")).toHaveTextContent("无法读取类型与风格");
  expect(screen.getByRole("combobox", { name: "画面风格" })).toBeDisabled();
  expect(createProject).not.toHaveBeenCalled();
});
