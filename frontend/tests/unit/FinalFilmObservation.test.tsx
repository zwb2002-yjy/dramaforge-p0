import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useFinalFilmExport } from "../../src/features/editing/useFinalFilmExport";
import { fetchRunStatuses } from "../../src/features/production/api";

const json = (data: unknown) =>
  new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
function mount({ projectId = "p1", sessionId = "cut1", version = 1 } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderHook(
    ({ sessionId, version }) =>
      useFinalFilmExport({
        projectId,
        sessionId,
        version,
        dirty: false,
      }),
    {
      initialProps: { sessionId, version },
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
}
afterEach(() => vi.restoreAllMocks());

describe("FinalFilm observation", () => {
  it("reads only exact tail identities and admits just one explicit export intent", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith("/final-films")) return json([]);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
      if (url.endsWith("/prepare"))
        return json({ preparation_fingerprint: "a".repeat(64), node_run_ids: ["r1", "r2"] });
      if (url.includes("/node-runs/status?"))
        return json([
          { id: "r1", status: "completed", result_artifact_id: "a1" },
          { id: "r2", status: "cached", result_artifact_id: "a2" },
        ]);
      if (url.endsWith("/render"))
        return json({
          status: "completed",
          result: {
            project_id: "p1",
            edit_session_id: "cut1",
            timeline_version: 1,
            artifact_id: "film1",
          },
        });
      throw new Error("Unexpected request: " + url);
    });
    const { result } = mount();
    expect(calls.filter((url) => url.endsWith("/prepare"))).toHaveLength(0);
    await act(async () => {
      await Promise.all([result.current.exportFilm(), result.current.exportFilm()]);
    });
    expect(calls.filter((url) => url.endsWith("/prepare"))).toHaveLength(1);
    expect(calls.filter((url) => url.endsWith("/render"))).toHaveLength(1);
    expect(calls).toContain("/api/v1/projects/p1/node-runs/status?run_id=r1&run_id=r2");
    expect(calls.some((url) => url.endsWith("/snapshot"))).toBe(false);
    expect(result.current.displayedFilm?.artifact_id).toBe("film1");
  });

  it("aborts observation on unmount without cancelling or resubmitting production", async () => {
    let finish: ((response: Response) => void) | undefined;
    let observationSignal: AbortSignal | undefined;
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith("/final-films")) return json([]);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
      if (url.endsWith("/prepare"))
        return json({ preparation_fingerprint: "a".repeat(64), node_run_ids: ["r1"] });
      if (url.includes("/node-runs/status?")) {
        observationSignal = init?.signal ?? undefined;
        return await new Promise<Response>((resolve) => {
          finish = resolve;
        });
      }
      throw new Error("Unexpected request: " + url);
    });
    const view = mount();
    let work: Promise<void> | undefined;
    act(() => {
      work = view.result.current.exportFilm();
    });
    await waitFor(() => expect(finish).toBeDefined());
    view.unmount();
    expect(observationSignal?.aborted).toBe(true);
    finish!(json([{ id: "r1", status: "completed", result_artifact_id: "a1" }]));
    await work;
    expect(calls.some((url) => /cancel|render|snapshot/.test(url))).toBe(false);
    expect(calls.filter((url) => url.endsWith("/prepare"))).toHaveLength(1);
  });

  it("rejects partial or wrong-task receipts instead of continuing export", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json([{ id: "other", status: "completed", result_artifact_id: "a1" }]),
    );
    await expect(fetchRunStatuses("p1", ["r1"])).rejects.toThrow("任务状态回执不完整");
  });

  it("chunks large plans at the server limit without fetching a project snapshot", async () => {
    const sizes: number[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input), "http://test");
      const ids = url.searchParams.getAll("run_id");
      sizes.push(ids.length);
      return json(ids.map((id) => ({ id, status: "completed", result_artifact_id: null })));
    });
    const ids = Array.from({ length: 205 }, (_, index) => "run-" + index);
    expect(await fetchRunStatuses("p1", ids)).toHaveLength(205);
    expect(sizes).toEqual([100, 100, 5]);
  });
});

it("refuses an incomplete preparation receipt without rendering or retrying", async () => {
  const calls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    calls.push(url);
    if (url.endsWith("/final-films")) return json([]);
    if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
    if (url.endsWith("/prepare")) return json({ node_run_ids: [] });
    throw new Error("Unexpected request: " + url);
  });
  const { result } = mount();
  await act(async () => {
    await result.current.exportFilm();
  });
  expect(result.current.error).toContain("缺少素材版本");
  expect(calls.filter((url) => url.endsWith("/prepare"))).toHaveLength(1);
  expect(calls.some((url) => url.endsWith("/render"))).toBe(false);
});

it("stops on an ambiguous tail submission without rendering or retrying", async () => {
  const calls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    calls.push(url);
    if (url.endsWith("/final-films")) return json([]);
    if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
    if (url.endsWith("/prepare")) {
      return json({ preparation_fingerprint: "a".repeat(64), node_run_ids: ["r1"] });
    }
    if (url.includes("/node-runs/status?")) {
      return json([
        {
          id: "r1",
          status: "failed",
          result_artifact_id: null,
          error_code: "PROVIDER_SUBMISSION_UNKNOWN",
        },
      ]);
    }
    throw new Error("Unexpected request: " + url);
  });

  const { result } = mount();
  await act(async () => {
    await result.current.exportFilm();
  });

  expect(result.current.error).toContain("提交结果未知");
  expect(result.current.error).toContain("不要盲目重试");
  expect(calls.filter((url) => url.includes("/node-runs/status?"))).toHaveLength(1);
  expect(calls.some((url) => url.endsWith("/render"))).toBe(false);
});

it("keeps real UUID export keys within the server limit and distinguishes saved and prepared versions", async () => {
  const projectId = "9a0b1dc8-f938-4699-b567-231339655d22";
  const sessionId = "23512641-a87d-49c3-bd51-22921980a4e7";
  const keys: string[] = [];
  let fingerprint = "a".repeat(64);
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/final-films")) return json([]);
    if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
    if (url.endsWith("/prepare"))
      return json({ preparation_fingerprint: fingerprint, node_run_ids: [] });
    if (url.endsWith("/render")) {
      keys.push(new Headers(init?.headers).get("Idempotency-Key") ?? "");
      return json({
        status: "completed",
        result: { project_id: projectId, edit_session_id: sessionId, artifact_id: "film-new" },
      });
    }
    throw new Error("Unexpected request: " + url);
  });
  const view = mount({ projectId, sessionId, version: 2147483646 });
  await act(async () => {
    await view.result.current.exportFilm();
  });
  await act(async () => {
    await view.result.current.exportFilm();
  });
  fingerprint = "b".repeat(64);
  await act(async () => {
    await view.result.current.exportFilm();
  });
  view.rerender({ sessionId, version: 2147483647 });
  await act(async () => {
    await view.result.current.exportFilm();
  });
  expect(keys).toHaveLength(4);
  for (const key of keys) {
    expect(key.length).toBeGreaterThan(0);
    expect(key.length).toBeLessThanOrEqual(120);
  }
  expect(keys[0]).toBe(keys[1]);
  expect(keys[2]).not.toBe(keys[1]);
  expect(keys[3]).not.toBe(keys[2]);
  expect(view.result.current.error).toBeNull();
});
