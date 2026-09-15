import { afterEach, describe, expect, it, vi } from "vitest";

import { apiGet, apiGetList, fetchProjectShots } from "../../src/lib/api";

/**
 * A list endpoint that answers with a non-array must not reach `.find`/`.map`.
 *
 * The container gate failed with `(shots.data ?? []).find is not a function`
 * inside render: one list route answered with an object, the workspace crashed,
 * and the browser test lost its status line. These cases pin the fail-closed
 * behaviour that keeps one wrong payload from blanking a whole workspace.
 */
function stub(body: unknown, status = 200): void {
  vi.spyOn(globalThis, "fetch").mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

afterEach(() => vi.restoreAllMocks());

describe("apiGetList", () => {
  it("returns an array unchanged", async () => {
    stub([{ id: "shot-1" }, { id: "shot-2" }]);
    await expect(apiGetList<{ id: string }>("/api/v1/projects/p/shots")).resolves.toEqual([
      { id: "shot-1" },
      { id: "shot-2" },
    ]);
  });

  it("fails closed to [] when the endpoint answers with an object", async () => {
    stub({ detail: "workspace not found" });
    await expect(apiGetList("/api/v1/projects/p/shots")).resolves.toEqual([]);
  });

  it("fails closed to [] when the endpoint answers with null", async () => {
    stub(null);
    await expect(apiGetList("/api/v1/projects/p/shots")).resolves.toEqual([]);
  });

  it("still reports a real HTTP failure instead of pretending the list is empty", async () => {
    stub({ code: "FORBIDDEN", detail: "no access" }, 403);
    await expect(apiGetList("/api/v1/projects/p/shots")).rejects.toMatchObject({
      status: 403,
      code: "FORBIDDEN",
    });
  });

  it("keeps apiGet's raw shape so object endpoints are unaffected", async () => {
    stub({ state: { last_view: "scenes" } });
    await expect(apiGet("/api/v1/projects/p/workspace-state")).resolves.toEqual({
      state: { last_view: "scenes" },
    });
  });
});

describe("fetchProjectShots", () => {
  it("never resolves to a non-array for the shot list", async () => {
    stub({ shots: [] });
    const shots = await fetchProjectShots("project-1");
    expect(Array.isArray(shots)).toBe(true);
    // The crashing call site shape: `.find` must exist on the result.
    expect(typeof shots.find).toBe("function");
  });
});
