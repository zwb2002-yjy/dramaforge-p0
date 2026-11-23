import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  StudioSelection,
  type StudioAttachment,
} from "../../src/components/workstation/StudioSelection";
import { ResearchPanel } from "../../src/features/research/ResearchPanel";
import { CreativeDirectionPanel } from "../../src/features/script/CreativeDirectionPanel";
import { UiProvider } from "../../src/components/ui";

const project = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const result = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const revision = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const hash = "b".repeat(64);
function Workbench() {
  const [attachment, showAttachment] = useState<StudioAttachment | null>(null);
  return (
    <StudioSelection.Provider value={{ attachment, showAttachment, media: null, show: () => {} }}>
      <ResearchPanel projectId={project} />
      <CreativeDirectionPanel projectId={project} />
    </StudioSelection.Provider>
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});
it("previews only the selected research body, sends one typed identity, and retains the question after refusal", async () => {
  const posts: Record<string, unknown>[] = [];
  const ref = { result_id: result, revision_id: revision, content_hash: hash };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://local.test").pathname;
      let data: unknown = { items: [], total: 0 };
      let status = 200;
      if (path.endsWith("/research-results"))
        data = {
          items: [
            {
              id: result,
              current_revision_id: revision,
              kind: "person",
              version: 2,
              current: { summary: "桥匠" },
              project_id: project,
              archived_at: null,
            },
          ],
          total: 1,
        };
      if (path.endsWith("/research-revisions/" + revision))
        data = {
          id: revision,
          result_id: result,
          number: 1,
          content_hash: hash,
          verification: "unverified",
          body: { schema_version: 1, display_name: "张先生" },
          citations: [{ id: "source", quoted_text: "私有引文原句", source_available: true }],
        };
      if (path.endsWith("/files")) data = [];
      if (path.endsWith("/director/threads"))
        data = { id: "thread", scope_type: "project", scope_entity_id: project };
      if (path.endsWith("/threads/thread")) data = { messages: [] };
      if (path.endsWith("/auth/csrf")) data = { csrf_token: "test" };
      if (path.endsWith("/messages")) {
        posts.push(JSON.parse(String(init?.body)));
        status = 422;
        data = {
          title: "研究来源未允许本次导演解读",
          details: { request_accepted: false, code: "RESEARCH_CONTEXT_SOURCE_RESTRICTED" },
        };
      }
      return new Response(JSON.stringify(data), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <UiProvider>
      <QueryClientProvider client={client}>
        <Workbench />
      </QueryClientProvider>
    </UiProvider>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "请导演解释" }));
  const preview = within(await screen.findByLabelText("将随消息发送的研究正文"));
  expect(preview.getByText("张先生")).toBeVisible();
  expect(preview.queryByText(/私有引文/)).toBeNull();
  expect(posts).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "请导演建议补充" }));
  const input = screen.getByRole("textbox", { name: "给导演的想法" });
  expect(input).toHaveValue("请建议这条研究还可以补充哪些内容，并指出需要核实的地方。");
  fireEvent.change(input, { target: { value: "我有自己的问题" } });
  fireEvent.click(screen.getByRole("button", { name: "请导演解释" }));
  expect(input).toHaveValue("我有自己的问题");
  fireEvent.click(screen.getByRole("button", { name: "发送给导演" }));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).toEqual({
    content: "我有自己的问题",
    intent: "conversation",
    request_key: expect.any(String),
    research_ref: ref,
  });
  expect(await screen.findByText("研究来源未允许本次导演解读")).toBeVisible();
  expect(input).toHaveValue("我有自己的问题");
  fireEvent.click(screen.getByRole("button", { name: "移除研究附件" }));
  expect(screen.queryByLabelText("将随消息发送的研究正文")).toBeNull();
});
