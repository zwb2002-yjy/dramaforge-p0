import { afterEach, describe, expect, it, vi } from "vitest";

import { generatePlanFromBrief } from "../../src/lib/api";

describe("generatePlanFromBrief", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("confirms a draft Brief before generating the Agent Plan", async () => {
    const requests: Array<{ path: string; method: string }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input), "http://localhost").pathname;
        requests.push({ path, method: init?.method ?? "GET" });

        if (path === "/api/v1/auth/csrf") {
          return new Response(JSON.stringify({ csrf_token: "csrf-test" }), { status: 200 });
        }
        if (path.endsWith("/brief/revision-1/confirm")) {
          return new Response(JSON.stringify({ id: "revision-1", status: "confirmed" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (path.endsWith("/plans/generate")) {
          return new Response(
            JSON.stringify({
              id: "plan-1",
              project_id: "project-1",
              status: "draft",
              plan: { prompt: "opening shot" },
              context_hash: "hash",
              source: "agent",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response("unexpected request", { status: 404 });
      }),
    );

    const result = await generatePlanFromBrief("project-1", "revision-1", "draft");

    expect(result.id).toBe("plan-1");
    expect(requests).toEqual([
      { path: "/api/v1/auth/csrf", method: "GET" },
      { path: "/api/v1/projects/project-1/brief/revision-1/confirm", method: "POST" },
      { path: "/api/v1/auth/csrf", method: "GET" },
      { path: "/api/v1/projects/project-1/plans/generate", method: "POST" },
    ]);
  });

  it("does not confirm an already confirmed Brief again", async () => {
    const requests: Array<{ path: string; method: string }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input), "http://localhost").pathname;
        requests.push({ path, method: init?.method ?? "GET" });

        if (path === "/api/v1/auth/csrf") {
          return new Response(JSON.stringify({ csrf_token: "csrf-test" }), { status: 200 });
        }
        return new Response(
          JSON.stringify({
            id: "plan-1",
            project_id: "project-1",
            status: "draft",
            plan: { prompt: "opening shot" },
            context_hash: "hash",
            source: "agent",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );

    await generatePlanFromBrief("project-1", "revision-1", "confirmed");

    expect(requests).toEqual([
      { path: "/api/v1/auth/csrf", method: "GET" },
      { path: "/api/v1/projects/project-1/plans/generate", method: "POST" },
    ]);
  });
});
