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

const GENERATED = {
  proposal: PROPOSAL,
  draft_text:
    "# Episode 1 — AI Draft\n## Scene 1 — Station / night\nRain.\n### Shot 1 — medium\nVisual: Lin waits\nDialogue: Do not wait.\nCamera: static\n",
  director_evidence: {
    turn_id: "44444444-4444-4444-8444-444444444444",
    request_key: "story-generation:test",
    context_hash: "a".repeat(64),
    output_hash: "b".repeat(64),
    slot: "planning.script",
    model_id: "litellm/script-quality",
    model_binding_ref: "production-model-profile:test@2:planning.script",
    actual_model: "upstream/story-v1",
    transport_status: "succeeded",
    token_usage: { total_tokens: 100 },
    reported_cost: "0.006",
    cost_status: "reported",
    currency: "USD",
    schema_repair_count: 0,
  },
};

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

  it("uses a brief to generate a model-backed draft and the same typed proposal preview", async () => {
    let generationBody: Record<string, unknown> | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/script")) return json(EMPTY);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf" });
      if (url.endsWith("/story/proposals/generate") && init?.method === "POST") {
        generationBody = init.body
          ? (JSON.parse(String(init.body)) as Record<string, unknown>)
          : undefined;
        return json(GENERATED, 201);
      }
      return json({});
    });
    renderWorkspace();
    await screen.findByTestId("story-proposal-composer");
    expect(screen.getByTestId("story-proposal-generate")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("故事方向"), {
      target: { value: "雨夜车站的克制告别" },
    });
    fireEvent.click(screen.getByTestId("story-proposal-generate"));
    expect(await screen.findByTestId("story-proposal-preview")).toBeInTheDocument();
    expect(screen.getByLabelText("剧本文本")).toHaveValue(GENERATED.draft_text);
    expect(screen.getByTestId("story-generation-evidence")).toHaveTextContent("upstream/story-v1");
    expect(screen.getByTestId("story-generation-evidence")).toHaveTextContent("44444444");
    expect(generationBody).toEqual({
      request_key: expect.stringMatching(/^story-generation:[0-9a-f-]{36}$/),
      brief: "雨夜车站的克制告别",
      filename: "story-draft.md",
    });
    expect(screen.getAllByTestId(/story-operation-/)).toHaveLength(3);
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
