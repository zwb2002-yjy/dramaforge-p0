import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProjectActions } from "../../src/features/project/ProjectActions";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

function setup(status = 204) {
  const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
    Promise.resolve(
      init?.method === "DELETE"
        ? status === 204
          ? new Response(null, { status })
          : new Response(JSON.stringify({ code: "CONFLICT", detail: "项目仍有生成任务" }), {
              status,
              headers: { "Content-Type": "application/json" },
            })
        : new Response(JSON.stringify({ csrf_token: "csrf" }), {
            headers: { "Content-Type": "application/json" },
          }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  localStorage.setItem("dramaforge.last-project-id", "project-1");
  const view = render(
    <QueryClientProvider client={client}>
      <ProjectActions project={{ id: "project-1", name: "我的短剧", version: 3 }} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "删除项目" }));
  return {
    fetchMock,
    changeProject: () =>
      view.rerender(
        <QueryClientProvider client={client}>
          <ProjectActions project={{ id: "project-1", name: "修改后的项目", version: 4 }} />
        </QueryClientProvider>,
      ),
  };
}

it("opens a named confirmation without deleting, and cancellation never writes", () => {
  const { fetchMock } = setup();
  expect(screen.getByRole("dialog", { name: "删除项目「我的短剧」？" })).toBeVisible();
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
});

it("deletes only after confirmation and clears the remembered project on success", async () => {
  const { fetchMock } = setup();
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  const calls = fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE");
  expect(calls).toHaveLength(1);
  expect(calls[0][0]).toBe("/api/v1/projects/project-1?expected_version=3");
  expect(localStorage.getItem("dramaforge.last-project-id")).toBeNull();
});

it("keeps confirmation and project context on a rejected delete without retrying", async () => {
  const { fetchMock } = setup(409);
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("项目仍有生成任务");
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE")).toHaveLength(1);
  expect(localStorage.getItem("dramaforge.last-project-id")).toBe("project-1");
});

it("binds confirmation to the project name and version shown when it opened", async () => {
  const { fetchMock, changeProject } = setup();
  changeProject();
  expect(screen.getByRole("dialog")).toHaveAccessibleName("删除项目「我的短剧」？");
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(fetchMock.mock.calls.find(([, init]) => init?.method === "DELETE")?.[0]).toBe(
    "/api/v1/projects/project-1?expected_version=3",
  );
});
