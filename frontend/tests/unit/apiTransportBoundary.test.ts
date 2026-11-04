import { ESLint } from "eslint";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiGet, apiSend, openEventStream } from "../../src/lib/api";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("API transport origin boundary", () => {
  it.each([
    "https://provider.example/generate",
    "http://provider.example/generate",
    "//provider.example/generate",
    "\\\\provider.example\\generate",
    "/\\provider.example/generate",
    "/\n/provider.example/generate",
    "data:text/plain,request",
    "api/v1/projects",
  ])("rejects %j before any request", async (path) => {
    const fetch = vi.spyOn(globalThis, "fetch");
    await expect(apiGet(path)).rejects.toMatchObject({ code: "INVALID_API_PATH" });
    await expect(apiSend("POST", path, {})).rejects.toMatchObject({ code: "INVALID_API_PATH" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("preserves the configured backend origin, workspace and CSRF headers", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://backend.example");
    const client = await import("../../src/lib/api");
    client.setSelectedWorkspaceId("workspace-1");
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));
    await client.apiSend("POST", "/api/v1/projects", { name: "project" }, "csrf-token");
    expect(fetch).toHaveBeenCalledWith(
      "https://backend.example/api/v1/projects",
      expect.objectContaining({
        credentials: "include",
        headers: expect.objectContaining({
          "X-CSRF-Token": "csrf-token",
          "X-Workspace-Id": "workspace-1",
        }),
        body: JSON.stringify({ name: "project" }),
      }),
    );
    client.setSelectedWorkspaceId(null);
  });

  it("keeps an unavailable EventSource a no-subscription result", () => {
    vi.stubGlobal("EventSource", undefined);
    expect(openEventStream("workspace-1")).toBeNull();
  });
});

describe("frontend network entrypoint lint", () => {
  const eslint = new ESLint();
  const filePath = "src/features/network-boundary-example.ts";
  const networkRuleIds = ["no-restricted-globals", "no-restricted-properties"];
  const apis = ["fetch", "EventSource", "XMLHttpRequest", "WebSocket"];
  const forbidden = apis.flatMap((api) => [
    `${api}('/api/v1/projects');`,
    `const request = ${api}; request('/api/v1/projects');`,
    ...["window", "globalThis", "self"].flatMap((owner) => [
      `${owner}.${api}('/api/v1/projects');`,
      `${owner}['${api}']('/api/v1/projects');`,
      `const { ${api}: request } = ${owner}; request('/api/v1/projects');`,
      `const request = ${owner}.${api}; request('/api/v1/projects');`,
    ]),
  ]);

  it.each(forbidden)(
    "rejects direct access and function aliases of browser I/O: %s",
    async (source) => {
      const [result] = await eslint.lintText(source, { filePath });
      expect(
        result?.messages.some((message) => networkRuleIds.includes(message.ruleId ?? "")),
      ).toBe(true);
    },
  );

  it("allows clients to call the unified transport", async () => {
    const [result] = await eslint.lintText(
      'import { apiGet } from "../../lib/api"; export const read = () => apiGet("/api/v1/projects");',
      { filePath },
    );
    expect(result?.errorCount).toBe(0);
  });

  it("does not mistake an unrelated business fetch property for browser I/O", async () => {
    const [result] = await eslint.lintText(
      "const repository = { fetch: () => ({ id: 1 }) }; export const read = () => repository.fetch();",
      { filePath },
    );
    expect(result?.errorCount).toBe(0);
  });

  it("allows the transport implementation to own browser I/O", async () => {
    const [result] = await eslint.lintText('fetch("/api/v1/projects");', {
      filePath: "src/lib/api.ts",
    });
    expect(result?.errorCount).toBe(0);
  });
});
