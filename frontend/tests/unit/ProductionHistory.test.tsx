import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProductionHistoryPanel } from "../../src/features/production/ProductionHistoryPanel";
import { fetchProductionSummary } from "../../src/features/production/api";

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function run(id: string) {
  return { id, node_key: "video", status: "completed", attempt_no: 1 };
}
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = (projectId: string) => (
    <QueryClientProvider client={client}>
      <ProductionHistoryPanel projectId={projectId} />
    </QueryClientProvider>
  );
  const rendered = render(view("p1"));
  return { ...rendered, switchProject: (id: string) => rendered.rerender(view(id)) };
}
afterEach(() => vi.restoreAllMocks());

describe("Bounded production history", () => {
  it("downloads no history until expanded and pages exact cursors without full snapshots", async () => {
    const calls: URL[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input), "http://test");
      calls.push(url);
      return json(
        url.searchParams.has("cursor")
          ? { items: [run("r2")], next_cursor: null }
          : { items: [run("r1")], next_cursor: "cursor+1=" },
      );
    });
    mount();
    expect(calls).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "查看任务历史与媒体结果" }));
    await screen.findByText("r1");
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText("r2");
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    expect(calls).toHaveLength(2);
    expect(calls[1].searchParams.get("cursor")).toBe("cursor+1=");
    expect(
      calls.every(
        (url) =>
          url.searchParams.get("limit") === "25" &&
          url.pathname.endsWith("/production-history/runs"),
      ),
    ).toBe(true);
    expect(screen.queryByText("r1")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "上一页" }));
    await screen.findByText("r1");
  });

  it("refreshes the first page only and switches to media with its own cursor", async () => {
    const calls: URL[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input), "http://test");
      calls.push(url);
      if (url.pathname.endsWith("/artifacts")) return json({ items: [], next_cursor: null });
      return json(
        url.searchParams.has("cursor")
          ? { items: [run("r2")], next_cursor: null }
          : { items: [run("r1")], next_cursor: "next" },
      );
    });
    mount();
    fireEvent.click(screen.getByRole("button", { name: "查看任务历史与媒体结果" }));
    await screen.findByText("r1");
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText("r2");
    fireEvent.click(screen.getByRole("button", { name: "刷新历史" }));
    await screen.findByText("r1");
    await waitFor(() => expect(calls).toHaveLength(3));
    expect(calls[2].searchParams.has("cursor")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "媒体结果" }));
    await screen.findByText("暂无历史记录。");
    expect(calls.at(-1)?.pathname).toBe("/api/v1/projects/p1/production-history/artifacts");
    expect(calls.at(-1)?.searchParams.has("cursor")).toBe(false);
  });

  it("does not turn a read failure into an empty-state success", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ detail: "unavailable" }, 503));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "查看任务历史与媒体结果" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("历史读取失败");
    expect(screen.queryByText("暂无历史记录。")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });

  it("closes history on project change instead of downloading a new project's history implicitly", async () => {
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(json({ items: [run("r1")], next_cursor: null }));
    const { switchProject } = mount();
    fireEvent.click(screen.getByRole("button", { name: "查看任务历史与媒体结果" }));
    await screen.findByText("r1");
    switchProject("p2");
    expect(screen.getByRole("button", { name: "查看任务历史与媒体结果" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByText("r1")).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("rejects incomplete or foreign summary receipts", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch");
    for (const value of [
      {},
      { project_id: "foreign", total_runs: 0 },
      {
        project_id: "p1",
        total_runs: -1,
        completed_runs: 0,
        running_runs: 0,
        failed_runs: 0,
        artifact_count: 0,
        recent_failures: [],
      },
    ]) {
      fetcher.mockResolvedValueOnce(json(value));
      await expect(fetchProductionSummary("p1")).rejects.toThrow("摘要回执不完整");
    }
  });
});
