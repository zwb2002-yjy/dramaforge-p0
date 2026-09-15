import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ScriptImportPanel } from "../../src/features/script/ScriptImportPanel";

const PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function importResult(overrides: Record<string, unknown> = {}) {
  return {
    script_document_id: "11111111-1111-4111-8111-111111111111",
    episode_id: "22222222-2222-4222-8222-222222222222",
    scene_count: 2,
    shot_count: 3,
    shot_ids: [
      "33333333-3333-4333-8333-333333333333",
      "44444444-4444-4444-8444-444444444444",
      "55555555-5555-4555-8555-555555555555",
    ],
    content_hash: "a".repeat(64),
    import_outcome: "created",
    ...overrides,
  };
}

function renderPanel(onOpenFirstShot = vi.fn(), onImported = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ScriptImportPanel
        projectId={PROJECT_ID}
        onImported={onImported}
        onOpenFirstShot={onOpenFirstShot}
      />
    </QueryClientProvider>,
  );
  return { onOpenFirstShot, onImported };
}

describe("ScriptImportPanel", () => {
  afterEach(() => vi.restoreAllMocks());

  it("explains the supported format before anything is submitted", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({}));
    renderPanel();

    const example = screen.getByTestId("script-import-format-example");
    expect(example).toHaveTextContent("# Episode 1");
    expect(example).toHaveTextContent("## Scene 1");
    expect(example).toHaveTextContent("### Shot 1");
    expect(screen.getByLabelText("选择剧本文件")).toHaveAttribute(
      "accept",
      ".md,.txt,text/plain,text/markdown",
    );
    expect(screen.getByTestId("script-import-submit")).toBeDisabled();
  });

  it("posts the pasted text and reports created counts with the first-shot action", async () => {
    const calls: Array<{ url: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      calls.push({
        url,
        body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {},
      });
      return json(importResult());
    });
    const { onImported, onOpenFirstShot } = renderPanel();

    fireEvent.change(screen.getByLabelText("剧本内容"), {
      target: { value: "# Episode 1 — Rain\n## Scene 1 — Platform / night\n### Shot 1 — medium\n" },
    });
    fireEvent.change(screen.getByLabelText("导入文件名"), {
      target: { value: "episode_script.md" },
    });
    fireEvent.click(screen.getByTestId("script-import-submit"));

    const result = await screen.findByTestId("script-import-result");
    expect(result).toHaveAttribute("data-outcome", "created");
    expect(result).toHaveTextContent("新增 2 个场景 / 3 个镜头");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe(`/api/v1/projects/${PROJECT_ID}/scripts/import`);
    expect(calls[0]?.body).toMatchObject({
      filename: "episode_script.md",
      text: expect.stringContaining("# Episode 1"),
    });
    expect(onImported).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByTestId("script-import-open-first-shot"));
    expect(onOpenFirstShot).toHaveBeenCalledOnce();
  });

  it("separates a re-imported identical script from a new creation", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      return json(importResult({ import_outcome: "reused" }));
    });
    renderPanel();

    fireEvent.change(screen.getByLabelText("剧本内容"), {
      target: { value: "# Episode 1 — Rain" },
    });
    fireEvent.click(screen.getByTestId("script-import-submit"));

    const result = await screen.findByTestId("script-import-result");
    expect(result).toHaveAttribute("data-outcome", "reused");
    expect(result).toHaveTextContent("不会重复创建");
  });

  it("keeps the text and shows the server reason when the import fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      return json({ code: "VALIDATION_ERROR", detail: "script has no shots" }, 422);
    });
    renderPanel();

    const textarea = screen.getByLabelText("剧本内容");
    fireEvent.change(textarea, { target: { value: "# Episode 1 — Rain" } });
    fireEvent.click(screen.getByTestId("script-import-submit"));

    const error = await screen.findByTestId("script-import-error");
    expect(error).toHaveTextContent("script has no shots");
    expect((textarea as HTMLTextAreaElement).value).toBe("# Episode 1 — Rain");
    expect(screen.queryByTestId("script-import-result")).not.toBeInTheDocument();
  });

  it("blocks an oversized file before any request is sent", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      calls.push(url);
      return json({ csrf_token: "csrf-test" });
    });
    renderPanel();

    fireEvent.change(screen.getByLabelText("剧本内容"), {
      target: { value: "x".repeat(1024 * 1024 + 1) },
    });

    expect(await screen.findByTestId("script-import-size-error")).toHaveTextContent("1 MiB");
    expect(screen.getByTestId("script-import-submit")).toBeDisabled();
    fireEvent.click(screen.getByTestId("script-import-submit"));
    await waitFor(() => expect(calls).toHaveLength(0));
  });

  it("loads a chosen local file into the textarea", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({}));
    renderPanel();

    const file = new File(
      ["# Episode 2 — Snow\n## Scene 1 — Street / day\n### Shot 1 — wide\n"],
      "snow.md",
      { type: "text/markdown" },
    );
    fireEvent.change(screen.getByLabelText("选择剧本文件"), { target: { files: [file] } });

    await waitFor(() =>
      expect((screen.getByLabelText("剧本内容") as HTMLTextAreaElement).value).toContain(
        "# Episode 2 — Snow",
      ),
    );
    expect((screen.getByLabelText("导入文件名") as HTMLInputElement).value).toBe("snow.md");
  });
});
