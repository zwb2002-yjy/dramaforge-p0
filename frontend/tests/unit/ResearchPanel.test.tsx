import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UiProvider } from "../../src/components/ui";
import { setSelectedWorkspaceId } from "../../src/lib/navigationPreferences";
import { KnowledgePanel } from "../../src/features/knowledge/KnowledgePanel";
import { ResearchPanel } from "../../src/features/research/ResearchPanel";

const PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const RESULT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const REVISION_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const ENTRY_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const CANDIDATE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";

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
  it("compares the full candidate and accepts it only after the user selects it", async () => {
    const writes: { url: string; body: Record<string, unknown> }[] = [];
    const current = {
      ...REVISION,
      applied_result_version: 2,
      body: { display_name: "张某", aliases: ["船匠"] },
    };
    const candidate = {
      ...current,
      id: CANDIDATE_ID,
      number: 2,
      origin: "model",
      applied_result_version: null,
      body: { display_name: "张某", aliases: ["石匠"] },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
        if (init?.method === "POST") {
          writes.push({ url, body: JSON.parse(String(init.body)) });
          return json({ revision_id: CANDIDATE_ID });
        }
        if (url.includes("/research-results?")) return json({ items: [RESULT], total: 1 });
        if (url.includes("/revisions")) return json({ items: [candidate, current], total: 2 });
        if (url.endsWith(CANDIDATE_ID)) return json(candidate);
        if (url.endsWith(REVISION_ID)) return json(current);
        if (url.endsWith("/files")) return json([]);
        return json({}, 404);
      }),
    );
    renderWithClient(<ResearchPanel projectId={PROJECT_ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "查看版本 2" }));
    const panel = within(await screen.findByLabelText("历史版本对照"));
    expect(await panel.findByText("船匠")).toBeTruthy();
    expect(await panel.findByText("石匠")).toBeTruthy();
    expect(writes).toHaveLength(0);
    const accept = panel.getByRole("button", { name: "采纳候选为新版本" });
    fireEvent.change(screen.getByLabelText("修正内容"), { target: { value: "未保存的内容" } });
    expect(accept).toBeDisabled();
    fireEvent.change(screen.getByLabelText("修正内容"), { target: { value: "" } });
    fireEvent.click(accept);
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].url).toContain(`/research-results/${RESULT_ID}/accept`);
    expect(writes[0].body).toMatchObject({
      base_revision_id: REVISION_ID,
      candidate_revision_id: CANDIDATE_ID,
      expected_version: 2,
    });
  });
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
    expect(await screen.findByRole("heading", { name: "张某" })).toBeTruthy();
    expect(await screen.findByText("名称")).toBeTruthy();
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
  it("previews and republishes the selected full revision independently of new-entry edits", async () => {
    setSelectedWorkspaceId("work-a");
    const writes: Record<string, unknown>[] = [];
    const entry = {
      id: ENTRY_ID,
      kind: "person",
      version: 3,
      publication_status: "published",
      current_revision_id: REVISION_ID,
      title: "古桥匠人",
      summary: "张某",
      allowed_uses: ["research"],
      shared_content_state: "complete",
    };
    const notes = [
      { label: "县志", public_url: "https://museum.example.org/books", locator_note: "卷二" },
    ];
    const revision = {
      id: REVISION_ID,
      number: 2,
      title: entry.title,
      body: { schema_version: 1, display_name: "张某", aliases: ["匠人"], description: "桥东" },
      allowed_uses: ["research"],
      shared_content_state: "complete",
      public_source_notes: notes,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
        if (init?.method === "POST") {
          writes.push(JSON.parse(String(init.body)));
          return json({ entry_id: ENTRY_ID, revision_id: REVISION_ID });
        }
        if (url.includes("/entries?")) return json({ items: [entry], total: 1 });
        if (url.endsWith("/revisions")) return json({ items: [revision], total: 1 });
        if (url.endsWith(ENTRY_ID)) return json(entry);
        return json({}, 404);
      }),
    );
    renderWithClient(<KnowledgePanel />);
    fireEvent.change(await screen.findByLabelText("新版本内容"), { target: { value: "李某" } });
    fireEvent.change(screen.getByLabelText("内容", { exact: true }), {
      target: { value: "另一条草稿" },
    });
    fireEvent.click(screen.getByRole("button", { name: "预览发布新版本" }));
    let dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByText("匠人", { exact: true })).toBeTruthy();
    expect(dialog.getByText("卷二")).toBeTruthy();
    expect(dialog.queryByText("另一条草稿")).toBeNull();
    fireEvent.click(dialog.getByRole("button", { name: "取消" }));
    expect(writes).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "预览发布新版本" }));
    dialog = within(await screen.findByRole("dialog"));
    fireEvent.click(dialog.getByRole("checkbox", { name: "作品创作" }));
    fireEvent.click(dialog.getByRole("button", { name: "确认发布" }));
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]).toMatchObject({
      expected_version: 3,
      allowed_uses: ["research", "creation"],
      body: { ...revision.body, display_name: "李某" },
      public_source_notes: notes,
    });
  });
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
                shared_content_state: "filtered",
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
                shared_content_state: "filtered",
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
            shared_content_state: "filtered",
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
    expect(await screen.findByText(/项目引用受限/)).toBeTruthy();
    expect(await screen.findByText(/部分内容已隐藏/)).toBeTruthy();
    const draft = screen.getByRole("button", { name: "保存草稿" });
    expect(draft.hasAttribute("disabled")).toBe(true);
    fireEvent.change(screen.getByLabelText("标题"), { target: { value: "新知识" } });
    fireEvent.change(screen.getByLabelText("内容"), { target: { value: "内容" } });
    await waitFor(() => expect(draft.hasAttribute("disabled")).toBe(false));
  });
});
