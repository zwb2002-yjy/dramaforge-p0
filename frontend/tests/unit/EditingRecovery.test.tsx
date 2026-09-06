import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EditingWorkspace } from "../../src/features/editing/EditingWorkspace";

const session = (id = "cut-1", version = 2) => ({
  id,
  project_id: "p1",
  name: `Cut ${id}`,
  status: "draft",
  version,
  created_at: "2026-09-04T00:00:00Z",
  updated_at: "2026-09-05T00:00:00Z",
  clip_count: 1,
  timeline: {
    clips: [
      {
        id: "clip-1",
        shot_id: "shot-1",
        artifact_id: "video-1",
        duration_seconds: 5,
        source_in_seconds: 0,
      },
    ],
    metadata: {},
  },
  production_lineage: { lineage_readonly: true },
});
const film = {
  project_id: "p1",
  edit_session_id: "cut-1",
  timeline_version: 1,
  export_id: "export-1",
  artifact_id: "film-1",
  node_run_id: "run-1",
  provider_operation_id: "op-1",
  format: "dramaforge-final-film-v1",
  status: "completed",
  duration_seconds: "5",
  shot_count: 1,
  timeline_clip_count: 1,
  composite_artifact_ids: [],
  source_commit: "fixture",
  mime_type: "video/mp4",
  byte_size: 42,
  storage_state: "available",
  content_hash: "a".repeat(64),
  formal_references: [],
};
const job = {
  project_id: "p1",
  edit_session_id: "cut-1",
  timeline_version: 1,
  node_run_id: "run-1",
  attempt_no: 1,
  status: "completed",
  result: film,
};
function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
}
function mockApi(history: unknown[] = [job]) {
  const calls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    expect(init?.method ?? "GET").toBe("GET");
    const url = String(input);
    calls.push(url);
    if (url.endsWith("/cut-1/final-films")) return json(history);
    if (url.endsWith("/final-films")) return json([]);
    if (url.endsWith("/edit-sessions")) return json([session(), session("cut-2")]);
    if (url.includes("/edit-sessions/")) return json(session(url.split("/").at(-1)));
    if (url.endsWith("/opencut-manifest"))
      return json({
        timeline: { duration_seconds: "0", aspect_ratio: "9:16" },
        tracks: [],
        shots: [],
      });
    return json({ detail: "unexpected GET" }, 404);
  });
  return calls;
}
function mount(sessionId?: string, onSelect = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = (id?: string) => (
    <QueryClientProvider client={client}>
      <EditingWorkspace projectId="p1" sessionId={id} onSessionSelected={onSelect} />
    </QueryClientProvider>
  );
  return { ...render(view(sessionId)), view, onSelect, client };
}
afterEach(() => vi.restoreAllMocks());

describe("Editing recovery", () => {
  it("lists and explicitly reopens existing sessions without POST", async () => {
    const calls = mockApi();
    const { onSelect } = mount();
    fireEvent.click(await screen.findByRole("button", { name: "继续剪辑 · Cut cut-2 · v2" }));
    expect(onSelect).toHaveBeenCalledWith("cut-2");
    expect(calls).toContain("/api/v1/projects/p1/edit-sessions");
  });
  it("restores historical media with its frozen version and clears it on session change", async () => {
    mockApi();
    const view = mount("cut-1");
    const player = await screen.findByTestId("final-film-player");
    expect(player).toHaveAttribute("src", "/api/v1/projects/p1/artifacts/film-1/content");
    expect(await screen.findByText(/历史成片 · Timeline v1（当前 v2）/)).toBeInTheDocument();
    expect(screen.getByTestId("final-film-download")).toHaveAttribute(
      "href",
      "/api/v1/projects/p1/artifacts/film-1/content",
    );
    view.rerender(view.view("cut-2"));
    await waitFor(() => expect(screen.queryByTestId("final-film-player")).not.toBeInTheDocument());
  });
  it("does not discard dirty timeline through the session picker", async () => {
    mockApi();
    const { onSelect } = mount("cut-1");
    fireEvent.change(await screen.findByLabelText("镜头 1 时长"), { target: { value: "4" } });
    const target = screen.getByRole("button", { name: "继续剪辑 · Cut cut-2 · v2" });
    expect(target).toBeDisabled();
    fireEvent.click(target);
    expect(onSelect).not.toHaveBeenCalled();
  });
  it("shows unavailable history without a broken video or automatic retry", async () => {
    mockApi([
      {
        ...job,
        result: null,
        error_code: "FINAL_FILM_ARTIFACT_UNAVAILABLE",
        error_summary: "成片文件不可用",
      },
    ]);
    mount("cut-1");
    expect(await screen.findByText("成片文件不可用")).toBeInTheDocument();
    expect(screen.queryByTestId("final-film-player")).not.toBeInTheDocument();
  });
});

it("refreshes the session summary after saving a new timeline version", async () => {
  let version = 2;
  let listReads = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url.endsWith("/auth/csrf")) return json({ csrf_token: "fixture" });
    if (url.endsWith("/timeline") && init?.method === "PATCH") {
      version += 1;
      return json({
        ...session("cut-1", version),
        timeline: JSON.parse(String(init.body)).timeline,
      });
    }
    if (url.endsWith("/edit-sessions")) {
      listReads += 1;
      return json([session("cut-1", version), session("cut-2")]);
    }
    if (url.endsWith("/final-films")) return json([]);
    return json(session("cut-1", version));
  });
  mount("cut-1");
  fireEvent.change(await screen.findByLabelText("镜头 1 时长"), { target: { value: "4.5" } });
  fireEvent.click(screen.getByRole("button", { name: "保存时间线" }));
  await waitFor(() =>
    expect(
      within(screen.getByRole("region", { name: "已有剪辑会话" })).getAllByRole("listitem")[0],
    ).toHaveTextContent("v3"),
  );
  expect(listReads).toBeGreaterThanOrEqual(2);
});

it("does not show a late Final Film error in a different session", async () => {
  let resolveRender!: (response: Response) => void;
  let renderRequested = false;
  const pendingRender = new Promise<Response>((resolve) => {
    resolveRender = resolve;
  });
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url.endsWith("/auth/csrf")) return json({ csrf_token: "fixture" });
    if (url.endsWith("/final-film/prepare"))
      return json({
        project_id: "p1",
        edit_session_id: "cut-1",
        timeline_version: 2,
        shot_ids: [],
        node_run_ids: [],
        status: "queued",
      });
    if (url.endsWith("/final-film/render") && init?.method === "POST") {
      renderRequested = true;
      return pendingRender;
    }
    if (url.endsWith("/edit-sessions")) return json([session(), session("cut-2")]);
    if (url.endsWith("/final-films")) return json([]);
    return json(session(url.split("/").at(-1)));
  });
  const view = mount("cut-1");
  const invalidation = vi.spyOn(view.client, "invalidateQueries");
  await screen.findByTestId("edit-session-editor");
  fireEvent.click(screen.getByTestId("export-final-film"));
  await waitFor(() => expect(renderRequested).toBe(true));
  view.rerender(view.view("cut-2"));
  await waitFor(() =>
    expect(screen.getByTestId("editing-workspace")).toHaveAttribute("data-session-id", "cut-2"),
  );
  resolveRender(await json({ detail: "late render failure" }, 503));
  await waitFor(() =>
    expect(invalidation).toHaveBeenCalledWith({ queryKey: ["edit-final-films", "p1", "cut-1", 2] }),
  );
  expect(screen.queryByTestId("final-film-error")).not.toBeInTheDocument();
});
