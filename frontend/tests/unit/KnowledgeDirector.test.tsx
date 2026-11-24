import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { UiProvider } from "../../src/components/ui";
import {
  StudioSelection,
  type StudioAttachment,
} from "../../src/components/workstation/StudioSelection";
import { ProjectKnowledgeReferences } from "../../src/features/knowledge/ProjectKnowledgeReferences";
import { CreativeDirectionPanel } from "../../src/features/script/CreativeDirectionPanel";
import { setSelectedWorkspaceId } from "../../src/lib/navigationPreferences";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});
function Workspace() {
  const [attachment, showAttachment] = useState<StudioAttachment | null>(null);
  return (
    <StudioSelection.Provider
      value={{ attachment, showAttachment, media: null, show: () => undefined }}
    >
      <ProjectKnowledgeReferences projectId="p" />
      <CreativeDirectionPanel projectId="p" />
    </StudioSelection.Provider>
  );
}
it("previews the selected pinned knowledge and sends its immutable reference only on explicit send", async () => {
  setSelectedWorkspaceId("w");
  const writes: Record<string, unknown>[] = [];
  const hash = "f".repeat(64);
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const json = (body: unknown, status = 200) =>
        Promise.resolve(
          new Response(JSON.stringify(body), {
            status,
            headers: { "content-type": "application/json" },
          }),
        );
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
      if (url.includes("/knowledge-references?"))
        return json({
          total: 2,
          next_offset: null,
          items: ["external_processing", "research"].map((use) => ({
            id: "pin-" + use,
            knowledge_entry_id: "entry",
            knowledge_revision_id: "rev",
            allowed_use: use,
            detached_at: null,
            availability: "published",
            version: 1,
          })),
        });
      if (url.includes("/knowledge/entries/entry/revisions"))
        return json({
          items: [
            {
              id: "rev",
              title: "桥梁",
              body: { text: "固定桥志公开片段" },
              number: 1,
              content_hash: hash,
              shared_content_state: "complete",
              allowed_uses: ["research", "external_processing"],
            },
          ],
          total: 1,
          next_offset: null,
        });
      if (url.endsWith("/messages") && init?.method === "POST") {
        writes.push(JSON.parse(String(init.body)));
        return json({ thread_id: "thread", turn_id: "turn", status: "queued" }, 202);
      }
      if (url.includes("/requests?")) return json({ turn: { status: "completed" } });
      return json({ id: "thread", scope_type: "project", scope_entity_id: "p", messages: [] });
    }),
  );
  render(
    <UiProvider>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <Workspace />
      </QueryClientProvider>
    </UiProvider>,
  );
  fireEvent.click(await screen.findByText("知识库引用", { exact: true }));
  const attach = await screen.findByRole("button", { name: "附到导演对话" });
  await waitFor(() => expect(attach).toBeEnabled());
  fireEvent.click(attach);
  expect(await screen.findByLabelText("将随消息发送的知识正文")).toHaveTextContent(
    "固定桥志公开片段",
  );
  expect(writes).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "发送给导演" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({
    intent: "conversation",
    knowledge_ref: {
      reference_id: "pin-external_processing",
      revision_id: "rev",
      content_hash: hash,
    },
  });
  expect(JSON.stringify(writes[0])).not.toContain("固定桥志公开片段");
});
