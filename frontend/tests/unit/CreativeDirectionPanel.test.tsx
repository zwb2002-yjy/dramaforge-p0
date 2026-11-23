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

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

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
    fireEvent.click(await screen.findByRole("button", { name: "创作方向" }));
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

  it("opens only on send, preserves newer typing, and restores replies in a fresh tab by reading", async () => {
    const THREAD = "66666666-6666-4666-8666-666666666666";
    const ref = { id: THREAD, scope_type: "project", scope_entity_id: PROJECT };
    const assistant = "以石桥与灯火为对景。";
    const posts: string[] = [];
    let opened = false,
      completed = false;
    let finish!: () => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), "http://local.test");
        if (url.pathname.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
        if (init?.method === "POST") posts.push(url.pathname);
        if (url.pathname.endsWith("/director/threads")) {
          if (init?.method === "POST") opened = true;
          else expect(url.searchParams.get("scope_entity_id")).toBe(PROJECT);
          return json(opened ? ref : null);
        }
        if (url.pathname.endsWith("/messages")) {
          expect(JSON.parse(String(init?.body))).toMatchObject({
            content: "请解释画面",
            intent: "conversation",
          });
          await new Promise<void>((r) => {
            finish = r;
          });
          completed = true;
          return json({ thread_id: THREAD, status: "queued" }, 202);
        }
        if (url.pathname.endsWith("/requests"))
          return json({ turn: { status: "completed", transport_status: "succeeded" } });
        if (url.pathname.endsWith(THREAD))
          return json({
            ...ref,
            messages: completed ? [{ id: "answer", role: "assistant", content: assistant }] : [],
          });
        return json({ profile_version: 1, direction: "" });
      }),
    );
    const first = renderPanel();
    const input = screen.getByRole("textbox", { name: "给导演的想法" });
    fireEvent.change(input, { target: { value: "请解释画面" } });
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(posts).toHaveLength(0);
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(posts).toHaveLength(2));
    fireEvent.change(input, { target: { value: "下一条意见" } });
    finish();
    expect(await screen.findByText(assistant)).toBeTruthy();
    expect(input).toHaveValue("下一条意见");
    fireEvent.click(screen.getByRole("button", { name: "采用为方向草稿" }));
    await waitFor(() => expect(screen.getByLabelText("创作方向")).toHaveValue(assistant));
    first.unmount();
    sessionStorage.clear();
    renderPanel();
    expect(await screen.findByText(assistant)).toBeTruthy();
    expect(posts).toHaveLength(2);
  });

  it("points model configuration refusals to the project and keeps the composer usable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
        if (url.endsWith("/messages"))
          return json(
            {
              title: "model unavailable",
              details: { code: "MODEL_PROFILE_NO_AVAILABLE_MODEL", request_accepted: false },
            },
            422,
          );
        if (url.endsWith("/director/threads"))
          return json({ id: "thread", scope_type: "project", scope_entity_id: PROJECT });
        if (url.includes("/threads?")) return json(null);
        return json({ messages: [] });
      }),
    );
    renderPanel();
    const input = screen.getByRole("textbox", { name: "给导演的想法" });
    fireEvent.change(input, { target: { value: "给灯会一个开场" } });
    const send = screen.getByRole("button", { name: "发送给导演" });
    fireEvent.click(send);
    expect(await screen.findByRole("link", { name: "配置项目模型" })).toHaveAttribute(
      "href",
      expect.stringContaining(PROJECT),
    );
    expect(send).toBeEnabled();
    expect(input).toHaveValue("给灯会一个开场");
  });

  it("observes an ambiguous submission without replay and reuses its key on explicit retry", async () => {
    const keys: string[] = [];
    const thread = {
      id: "original",
      scope_type: "project",
      scope_entity_id: PROJECT,
      messages: [],
    };
    let completed = false;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
        if (url.endsWith("/messages")) {
          keys.push(JSON.parse(String(init?.body)).request_key);
          if (keys.length === 1) throw new TypeError("连接中断");
          completed = true;
          return json({ thread_id: thread.id, request_key: keys[0], status: "queued" }, 202);
        }
        if (url.includes("/requests?"))
          return completed
            ? json({ turn: { status: "completed", transport_status: "succeeded" } })
            : json({ code: "AGENT_REQUEST_NOT_FOUND" }, 404);
        return json(thread);
      }),
    );
    renderPanel();
    fireEvent.change(screen.getByRole("textbox", { name: "给导演的想法" }), {
      target: { value: "草稿" },
    });
    const send = screen.getByRole("button", { name: "发送给导演" });
    fireEvent.click(send);
    const retry = await screen.findByRole("button", { name: "按原请求键发送当前内容" });
    expect(keys).toHaveLength(1);
    expect(send).toBeDisabled();
    fireEvent.click(retry);
    await waitFor(() => expect(keys).toEqual([keys[0], keys[0]]));
  });

  it("keeps the save button disabled for a blank direction", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => json({ profile_version: 1, direction: "" })),
    );
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "创作方向" }));
    const button = await screen.findByRole("button", { name: "保存创作方向" });
    expect(button).toBeDisabled();
  });
});
