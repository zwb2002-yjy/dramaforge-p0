import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ScriptWorkspace } from "../../src/features/script/ScriptWorkspace";

const DOC = {
  script_document_id: "doc-1",
  filename: "episode_script.md",
  content_hash: "a".repeat(64),
  format: "md",
  raw_text: "# Episode 1 — Neon Rain\n## Scene 1 — Street / night\nOpening.\n",
  version: 1,
};

const EPISODES = [
  {
    id: "ep-1",
    episode_number: 1,
    title: "Neon Rain",
    synopsis: "A lead",
    version: 1,
    scenes: [
      {
        id: "sc-1",
        scene_number: 1,
        location_name: "Street",
        time_of_day: "night",
        synopsis: "Opening.",
        shot_count: 3,
        version: 1,
      },
    ],
  },
];

const PROPOSAL = {
  id: "proposal-1",
  project_id: "project-1",
  status: "pending",
  summary: "Story authoring proposal",
  created_at: "2026-09-03T00:00:00Z",
  operations: [
    {
      id: "op-1",
      command: "story.upsert_episode",
      action: "create",
      key: "episode:1",
      expected_target_version: null,
      rationale: "Episode 结构",
      impact: "episode:1",
      payload: { episode_number: 1, action: "create" },
    },
    {
      id: "op-2",
      command: "story.upsert_scene",
      action: "create",
      key: "scene:1.1",
      expected_target_version: null,
      rationale: "Scene 结构",
      impact: "scene:1.1",
      payload: { episode_number: 1, scene_number: 1, action: "create" },
    },
    {
      id: "op-3",
      command: "story.upsert_shot",
      action: "create",
      key: "shot:1.1.1",
      expected_target_version: null,
      rationale: "Shot 结构",
      impact: "shot:1.1.1",
      payload: { episode_number: 1, scene_number: 1, shot_number: 1, action: "create" },
    },
  ],
};

const EMPTY = { document: null, episodes: [] };

function json(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function renderWorkspace(projectId = "project-1") {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ScriptWorkspace projectId={projectId} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("ScriptWorkspace proposal-first UI", () => {
  it("shows the current document and episodes when Canonical Story exists", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/script")) return json({ document: DOC, episodes: EPISODES });
      return json({});
    });
    renderWorkspace();
    expect(await screen.findByTestId("script-document")).toBeInTheDocument();
    const episodes = screen.getByTestId("script-episodes");
    expect(within(episodes).getByText(/Neon Rain/)).toBeInTheDocument();
    expect(screen.getByTestId("story-proposal-composer")).toBeInTheDocument();
  });

  it("shows the empty state and always offers a Story proposal composer", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/script")) return json(EMPTY);
      return json({});
    });
    renderWorkspace();
    expect(await screen.findByTestId("script-empty")).toBeInTheDocument();
    expect(screen.getByTestId("story-proposal-composer")).toBeInTheDocument();
    expect(screen.getByText("Story 导演提案")).toBeInTheDocument();
  });

  it("creates a proposal and renders the typed diff", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/script")) return json(EMPTY);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf" });
      if (url.endsWith("/story/proposals") && init?.method === "POST") {
        return json(PROPOSAL, 201);
      }
      return json({});
    });
    renderWorkspace();
    await screen.findByTestId("story-proposal-composer");
    fireEvent.change(screen.getByLabelText("故事方向"), {
      target: { value: "双人冲突" },
    });
    fireEvent.change(screen.getByLabelText("剧本文本"), {
      target: {
        value:
          "# Episode 1 — X\n## Scene 1 — Studio / day\nbody\n### Shot 1 — medium\nVisual: v\nDialogue: d",
      },
    });
    fireEvent.click(screen.getByTestId("story-proposal-create"));
    expect(await screen.findByTestId("story-proposal-preview")).toBeInTheDocument();
    expect(screen.getAllByTestId(/story-operation-/)).toHaveLength(3);
    expect(screen.getByText(/Episode 1/)).toBeInTheDocument();
    expect(screen.getByText(/pending/)).toBeInTheDocument();
  });

  it("applies only the selected operations", async () => {
    let applyBody: unknown;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/script")) return json(EMPTY);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf" });
      if (url.endsWith("/story/proposals") && init?.method === "POST") {
        return json(PROPOSAL, 201);
      }
      if (url.endsWith("/story/proposals/proposal-1/apply") && init?.method === "POST") {
        applyBody = init.body ? JSON.parse(String(init.body)) : null;
        return json({ accepted: ["op-1"], rejected: [], failed: [] });
      }
      return json({});
    });
    renderWorkspace();
    await screen.findByTestId("story-proposal-composer");
    fireEvent.change(screen.getByLabelText("剧本文本"), {
      target: {
        value:
          "# Episode 1 — X\n## Scene 1 — Studio / day\nbody\n### Shot 1 — medium\nVisual: v\nDialogue: d",
      },
    });
    fireEvent.click(screen.getByTestId("story-proposal-create"));
    await screen.findByTestId("story-proposal-preview");

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[1]);
    fireEvent.click(checkboxes[2]);
    fireEvent.click(screen.getByTestId("story-proposal-apply-selected"));

    await waitFor(() => {
      expect(applyBody).toEqual({
        decisions: [{ item_id: "op-1", decision: "accepted" }],
      });
    });
  });
});
