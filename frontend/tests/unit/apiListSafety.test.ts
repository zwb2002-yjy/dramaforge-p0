import { afterEach, describe, expect, it, vi } from "vitest";

import { apiGet, apiGetList, fetchProjectShots } from "../../src/lib/api";

/**
 * A list endpoint that answers with a non-array is a contract violation and
 * must stay visible to the query error state instead of becoming a fake empty
 * list.
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

  it("throws when the endpoint answers with an object", async () => {
    stub({ detail: "workspace not found" });
    await expect(apiGetList("/api/v1/projects/p/shots")).rejects.toMatchObject({
      status: 502,
      code: "INVALID_RESPONSE_SHAPE",
      details: { expected: "array", actual: "object" },
    });
  });

  it("throws when the endpoint answers with null", async () => {
    stub(null);
    await expect(apiGetList("/api/v1/projects/p/shots")).rejects.toMatchObject({
      status: 502,
      code: "INVALID_RESPONSE_SHAPE",
      details: { expected: "array", actual: "null" },
    });
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
  it("surfaces a malformed shot-list response", async () => {
    stub({ shots: [] });
    await expect(fetchProjectShots("project-1")).rejects.toMatchObject({
      code: "INVALID_RESPONSE_SHAPE",
    });
  });
});
