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
