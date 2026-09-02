import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CreativeAutonomySwitcher } from "../../src/features/project/CreativeAutonomySwitcher";
import type { ProjectRead } from "../../src/lib/api";

function profile(directorAutonomy = "ASSIST", version = 1) {
  return {
    id: "profile-1",
    project_id: "project-1",
    start_type: "FREE",
    created_from_template_key: null,
    template_version: null,
    template_contract_hash: null,
    director_autonomy: directorAutonomy,
    selected_genre: null,
    selected_style_ids: [],
    selected_skill_ids: [],
    selected_shot_language: null,
    asset_slot_requirements: {},
    strategy_snapshot: {},
    version,
  };
}

function project(): ProjectRead {
  return {
    id: "project-1",
    workspace_id: "workspace-1",
    name: "测试项目",
    stage: "planning",
    aspect_ratio: "9:16",
    target_platform: "general",
    provider_dispatch_frozen: false,
    version: 1,
    creative_profile: profile(),
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderSwitcher() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CreativeAutonomySwitcher project={project()} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("CreativeAutonomySwitcher", () => {
  it("switches DirectorAutonomy through the canonical creative-profile PATCH", async () => {
    const calls: Array<{ method: string; url: string; body?: unknown }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url.includes("/auth/csrf")) {
        return json({ csrf_token: "csrf-token" });
      }
      if (url.includes("/creative-profile")) {
        return json(profile("AUTO", 2));
      }
      throw new Error(`unexpected fetch ${method} ${url}`);
    });

    renderSwitcher();
    const select = screen.getByTestId("creative-autonomy-select");
    expect(select).toHaveValue("ASSIST");

    fireEvent.change(select, { target: { value: "AUTO" } });
    await waitFor(() => {
      expect(screen.getByTestId("creative-autonomy-message")).toHaveTextContent(
        "导演参与度已切换为 AUTO",
      );
    });

    const patch = calls.find((call) => call.method === "PATCH");
    expect(patch).toBeDefined();
    expect(patch?.url).toContain("/projects/project-1/creative-profile");
    expect(patch?.body).toEqual({ expected_version: 1, director_autonomy: "AUTO" });
  });

  it("surfaces stale/conflict failures without changing the select value", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/auth/csrf")) {
        return json({ csrf_token: "csrf-token" });
      }
      if ((init?.method ?? "GET") === "PATCH") {
        return json(
          {
            code: "CREATIVE_PROFILE_STALE",
            detail: "creative profile version conflict",
          },
          409,
        );
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderSwitcher();
    const select = screen.getByTestId("creative-autonomy-select");
    fireEvent.change(select, { target: { value: "MANUAL" } });
    await waitFor(() => {
      expect(screen.getByTestId("creative-autonomy-message")).toHaveTextContent("切换失败");
    });
    expect(select).toHaveValue("ASSIST");
  });
});
