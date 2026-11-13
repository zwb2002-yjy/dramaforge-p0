import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProjectModelInheritance } from "../../src/components/provider/ProjectModelInheritance";
import { queryKeys } from "../../src/lib/queryKeys";

afterEach(() => vi.restoreAllMocks());

it("releases only media overrides after an explicit click, preserving text options and version checking", async () => {
  const text = {
    model_id: "litellm/text",
    enabled: false,
    native_options: { temperature: 0.4, extension: { enabled: false, count: 0, tags: ["keep"] } },
  };
  let profile = {
    id: "profile",
    workspace_id: "workspace",
    version: 8,
    name: "Keep project profile name",
    is_default: false,
    bindings: {
      "planning.script": text,
      "visual.keyframe": { model_id: "binding:old-image", enabled: true, native_options: {} },
      "video.shot": { model_id: "binding:old-video", enabled: true, native_options: {} },
    },
  };
  const writes: unknown[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body));
      writes.push(body);
      profile = { ...profile, bindings: body.bindings, version: 9 };
    }
    return new Response(JSON.stringify(url.endsWith("/csrf") ? { csrf_token: "csrf" } : profile), {
      status: 200,
    });
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  client.setQueryData(queryKeys.model.projectProfile("project"), profile);
  render(
    <QueryClientProvider client={client}>
      <ProjectModelInheritance projectId="project" workspaceId="workspace" />
    </QueryClientProvider>,
  );
  const button = screen.getByRole("button", { name: "本项目改用工作空间生图和视频模型" });
  expect(writes).toEqual([]);
  fireEvent.click(button);
  await waitFor(() =>
    expect(writes).toEqual([{ expected_version: 8, bindings: { "planning.script": text } }]),
  );
  expect(profile.name).toBe("Keep project profile name");
  expect(profile.is_default).toBe(false);
  expect(profile.bindings["planning.script"]).toEqual(text);
  await waitFor(() =>
    expect(screen.queryByTestId("project-model-inheritance")).not.toBeInTheDocument(),
  );
});

it("does not offer to change a project from a different selected workspace", () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  client.setQueryData(queryKeys.model.projectProfile("project"), {
    workspace_id: "other",
    bindings: { "video.shot": { model_id: "binding:video" } },
  });
  render(
    <QueryClientProvider client={client}>
      <ProjectModelInheritance projectId="project" workspaceId="workspace" />
    </QueryClientProvider>,
  );
  expect(screen.queryByTestId("project-model-inheritance")).not.toBeInTheDocument();
});
