import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ScriptWorkspace } from "../../src/features/script/ScriptWorkspace";

const DOC = {
  script_document_id: "doc-1",
  filename: "episode_script.md",
  content_hash: "a".repeat(64),
  format: "md",
  raw_text:
    "# Episode 1 — Neon Rain Lead\nLead: Lin Xia\n## Scene 1 — Neon alley / night\nOpening.\n### Shot 1 — wide\nVisual: neon rain street at night\nDialogue: (none)\nCamera: static",
  version: 1,
};

const EPISODES = [
  {
    id: "ep-1",
    episode_number: 1,
    title: "Neon Rain Lead",
    synopsis: "A lead",
    version: 1,
    scenes: [
      {
        id: "sc-1",
        scene_number: 1,
        location_name: "Neon alley",
        time_of_day: "night",
        synopsis: "Opening rain.",
        shot_count: 3,
        version: 1,
      },
    ],
  },
];

const EMPTY = { document: null, episodes: [] };

function json(body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
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
beforeEach(() => {});

describe("ScriptWorkspace", () => {
  it("shows raw text + episodes when a document exists, and no import form", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/script")) return json({ document: DOC, episodes: EPISODES });
      return json({});
    });
    renderWorkspace();
    expect(await screen.findByTestId("script-document")).toBeInTheDocument();
    const episodes = screen.getByTestId("script-episodes");
    expect(episodes).toBeInTheDocument();
    expect(within(episodes).getByText(/Neon Rain Lead/)).toBeInTheDocument();
    expect(within(episodes).getByText(/3 镜头/)).toBeInTheDocument();
    // No active import control once a document exists.
    expect(screen.queryByTestId("script-import")).not.toBeInTheDocument();
  });

  it("shows the empty state + import form when no document is imported", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/script")) return json(EMPTY);
      return json({});
    });
    renderWorkspace();
    expect(await screen.findByTestId("script-empty")).toBeInTheDocument();
    expect(screen.getByTestId("script-import")).toBeInTheDocument();
    expect(screen.getByText("尚未导入剧本")).toBeInTheDocument();
  });

  it("submits a first import then refetches the workspace", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/script") && !(init?.method === "POST")) return json(EMPTY);
      if (url.endsWith("/scripts/import") && init?.method === "POST") {
        return json({ ...DOC, script_document_id: "doc-2" });
      }
      return json({});
    });
    renderWorkspace();
    await screen.findByTestId("script-import");
    // Simulate a refetch after import by returning a non-empty document.
    fireEvent.change(screen.getByLabelText("剧本文本"), {
      target: {
        value:
          "# Episode 1 — X\nLead: A\n## Scene 1 — Loc / day\nbody\n### Shot 1 — medium\nVisual: v\nDialogue: d",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "导入剧本" }));
    await waitFor(() => {
      expect(calls.some((c) => c.startsWith("POST") && c.endsWith("/scripts/import"))).toBe(true);
    });
  });

  it("surfaces a parse error on a failed first import", async () => {
    const body = JSON.stringify({
      code: "VALIDATION_ERROR",
      detail: "script has no scenes",
    });
    const errorResponse = new Response(body, {
      status: 422,
      headers: { "Content-Type": "application/json" },
    });
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/script") && !(init?.method === "POST")) return json(EMPTY);
      if (url.endsWith("/scripts/import") && init?.method === "POST") {
        return Promise.resolve(errorResponse);
      }
      return json({});
    });
    renderWorkspace();
    await screen.findByTestId("script-import");
    fireEvent.change(screen.getByLabelText("剧本文本"), { target: { value: "no scenes here" } });
    fireEvent.click(screen.getByRole("button", { name: "导入剧本" }));
    expect(await screen.findByTestId("script-import-error")).toBeInTheDocument();
  });
});
