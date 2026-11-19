import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UiProvider } from "../../src/components/ui";
import { CreativeDirectionPanel } from "../../src/features/script/CreativeDirectionPanel";

const PROJECT = "11111111-1111-4111-8111-111111111111";

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <UiProvider>
      <QueryClientProvider client={client}>
        <CreativeDirectionPanel projectId={PROJECT} />
      </QueryClientProvider>
    </UiProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("CreativeDirectionPanel", () => {
  it("loads and saves the direction with the profile version", async () => {
    const posts: Array<{ url: string; body: unknown }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
        if (init?.method === "POST") {
          posts.push({ url, body: JSON.parse(String(init.body)) });
          return json({ profile_version: 3, direction: "明代江南，克制含蓄。" });
        }
        return json({ profile_version: 2, direction: "旧方向" });
      }),
    );
    renderPanel();
    const textarea = await screen.findByLabelText("创作方向");
    await waitFor(() => expect(textarea).toHaveValue("旧方向"));
    fireEvent.change(textarea, { target: { value: "明代江南，克制含蓄。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存创作方向" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]?.body).toEqual({
      expected_profile_version: 2,
      direction: "明代江南，克制含蓄。",
    });
    expect(await screen.findByRole("status")).toHaveTextContent("创作方向已保存。");
  });

  it("discusses in the project thread and adopts an assistant message", async () => {
    const THREAD = "66666666-6666-4666-8666-666666666666";
    const ASSISTANT = "明代江南，水汽与克制的构图，避免奇观化。";
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
        if (url.endsWith("/director/threads") && init?.method === "POST") {
          return json({
            id: THREAD,
            scope_type: "project",
            scope_entity_id: PROJECT,
          });
        }
        if (url.includes(`/director/threads/${THREAD}/messages`)) {
          return json({
            thread_id: THREAD,
            turn_id: "77777777-7777-4777-8777-777777777777",
            user_message_id: "88888888-8888-4888-8888-888888888888",
            status: "queued",
            accepted_revision: 1,
            read_url: `/api/v1/projects/${PROJECT}/director/threads/${THREAD}`,
            request_key: "direction:1",
          });
        }
        if (url.includes(`/director/threads/${THREAD}`)) {
          return json({
            id: THREAD,
            scope_type: "project",
            scope_entity_id: PROJECT,
            messages: [
              {
                id: "99999999-9999-4999-8999-999999999999",
                turn_id: null,
                role: "assistant",
                content: ASSISTANT,
                created_at: "2026-11-19T00:00:00Z",
              },
            ],
            offset: 0,
            limit: 20,
            total: 1,
            has_more: false,
            has_previous: false,
          });
        }
        return json({ profile_version: 1, direction: "" });
      }),
    );
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "开始方向讨论" }));
    const adopt = await screen.findByRole("button", { name: "采用为方向" });
    expect(screen.getByText(ASSISTANT)).toBeInTheDocument();
    fireEvent.click(adopt);
    await waitFor(() => expect(screen.getByLabelText("创作方向")).toHaveValue(ASSISTANT));
  });

  it("keeps the save button disabled for a blank direction", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => json({ profile_version: 1, direction: "" })),
    );
    renderPanel();
    const button = await screen.findByRole("button", { name: "保存创作方向" });
    expect(button).toBeDisabled();
  });
});
