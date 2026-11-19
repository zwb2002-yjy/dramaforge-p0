import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UiProvider } from "../../src/components/ui";
import { KnowledgePanel } from "../../src/features/knowledge/KnowledgePanel";
import { ResearchPanel } from "../../src/features/research/ResearchPanel";

const PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const RESULT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const REVISION_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const ENTRY_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const RESULT = {
  id: RESULT_ID,
  project_id: PROJECT_ID,
  kind: "person",
  version: 2,
  current_revision_id: REVISION_ID,
  archived: false,
  current: { summary: "张某" },
  created_at: "2026-11-19T00:00:00Z",
  updated_at: "2026-11-19T00:00:00Z",
};

const REVISION = {
  id: REVISION_ID,
  result_id: RESULT_ID,
  number: 1,
  body: { schema_version: 1, display_name: "张某" },
  citations: [],
  verification: "unverified",
  origin: "user",
  summary: "张某",
  created_at: "2026-11-19T00:00:00Z",
};

function renderWithClient(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <UiProvider>
      <QueryClientProvider client={client}>{node}</QueryClientProvider>
    </UiProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("ResearchPanel", () => {
  it("lists typed findings and shows the current revision body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/research-results?")) {
          return json({ items: [RESULT], total: 1, next_offset: null });
        }
        if (url.includes(`/research-revisions/${REVISION_ID}`)) return json(REVISION);
        if (url.includes(`/research-results/${RESULT_ID}/revisions`)) {
          return json({ items: [REVISION], total: 1, next_offset: null });
        }
        if (url.endsWith("/files")) return json([]);
        return json({ code: "NOT_FOUND" }, 404);
      }),
    );
    renderWithClient(<ResearchPanel projectId={PROJECT_ID} />);
    expect(await screen.findByText("张某")).toBeTruthy();
    expect(await screen.findByText(/display_name/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "保存修正为新版本" })).toBeTruthy();
  });

  it("keeps analysis preview disabled until a parsed source is selected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/research-results?")) {
          return json({ items: [], total: 0, next_offset: null });
        }
        if (url.endsWith("/files")) return json([]);
        return json({ code: "NOT_FOUND" }, 404);
      }),
    );
    renderWithClient(<ResearchPanel projectId={PROJECT_ID} />);
    const preview = await screen.findByRole("button", { name: "分析预览" });
    expect(preview.hasAttribute("disabled")).toBe(true);
  });
});

describe("KnowledgePanel", () => {
  it("lists published knowledge and requires an explicit draft before creating", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/knowledge/entries?")) {
          return json({
            items: [
              {
                id: ENTRY_ID,
                kind: "person",
                version: 2,
                publication_status: "published",
                current_revision_id: REVISION_ID,
                title: "古桥匠人",
                summary: "张某",
                allowed_uses: ["research"],
                updated_at: "2026-11-19T00:00:00Z",
              },
            ],
            total: 1,
            next_offset: null,
          });
        }
        if (url.includes(`/knowledge/entries/${ENTRY_ID}/revisions`)) {
          return json({
            items: [
              {
                id: REVISION_ID,
                entry_id: ENTRY_ID,
                number: 1,
                title: "古桥匠人",
                body: { schema_version: 1, display_name: "张某" },
                allowed_uses: ["research"],
                public_source_notes: [],
                content_hash: "a".repeat(64),
                operation: "publish",
                publication_status: "published",
                result_entry_version: 2,
                created_at: "2026-11-19T00:00:00Z",
              },
            ],
            total: 1,
            next_offset: null,
          });
        }
        if (url.includes(`/knowledge/entries/${ENTRY_ID}`)) {
          return json({
            id: ENTRY_ID,
            kind: "person",
            version: 2,
            publication_status: "published",
            current_revision_id: REVISION_ID,
            title: "古桥匠人",
            summary: "张某",
            allowed_uses: ["research"],
            updated_at: "2026-11-19T00:00:00Z",
          });
        }
        return json({ code: "NOT_FOUND" }, 404);
      }),
    );
    renderWithClient(<KnowledgePanel />);
    expect((await screen.findAllByText("古桥匠人")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("已发布")).length).toBeGreaterThan(0);
    const draft = screen.getByRole("button", { name: "保存草稿" });
    expect(draft.hasAttribute("disabled")).toBe(true);
    fireEvent.change(screen.getByLabelText("标题"), { target: { value: "新知识" } });
    fireEvent.change(screen.getByLabelText("内容"), { target: { value: "内容" } });
    await waitFor(() => expect(draft.hasAttribute("disabled")).toBe(false));
  });
});
