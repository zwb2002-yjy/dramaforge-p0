import { afterEach, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";

import { previewProjectIntent, updateProject } from "../../src/features/project/api";
import { setSelectedWorkspaceId } from "../../src/lib/navigationPreferences";
import {
  parseProductionChange,
  productionQueryAffected,
} from "../../src/components/sse/productionInvalidation";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

it.each([previewProjectIntent, updateProject])(
  "does not send a project request after workspace changes during CSRF",
  async (request) => {
    let release!: (value: Response) => void;
    const token = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const fetch = vi.fn().mockReturnValue(token);
    vi.stubGlobal("fetch", fetch);
    setSelectedWorkspaceId("workspace-1");
    const pending = request("project-1", { expected_version: 1, name: "new" }, "workspace-1");
    setSelectedWorkspaceId("workspace-2");
    release(new Response(JSON.stringify({ csrf_token: "synthetic" }), { status: 200 }));
    await expect(pending).rejects.toThrow("工作空间已切换");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toContain("/auth/csrf");
  },
);

it("invalidates only scoped project metadata for a project change notice", () => {
  const envelope = {
    topic: "production.facts.v1",
    workspace_id: "w1",
    project_id: "p1",
    payload: {
      project_id: "p1",
      notice: { kind: "project_changed", project_id: "p1", project_version: 2 },
    },
  };
  const change = parseProductionChange(envelope, "w1");
  expect(change).not.toBeNull();
  if (!change) throw new Error("Expected a scoped change");
  expect(parseProductionChange({ ...envelope, workspace_id: "w2" }, "w1")).toBeNull();
  expect(parseProductionChange({ ...envelope, workspace_id: undefined }, "w1")).toBeNull();
  const client = new QueryClient();
  for (const [key, affected] of [
    [["project", "p1"], true],
    [["workspace-projects", "w1"], true],
    [["workspace-projects", "w2"], false],
    [["project", "p2"], false],
    [["edit-session", "p1", "s1"], false],
  ] as const) {
    client.setQueryData(key, {});
    const query = client.getQueryCache().find({ queryKey: key });
    if (!query) throw new Error("Missing test query");
    expect(productionQueryAffected(query, [change])).toBe(affected);
  }
});
