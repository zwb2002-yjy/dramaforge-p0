import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { UiProvider } from "../../src/components/ui";
import { FileUseEditor } from "../../src/features/project-files/FileUseEditor";

afterEach(() => vi.unstubAllGlobals());
it("loads cross-project counts and paged local impacts on demand", async () => {
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method ?? "GET").toBe("GET");
      const url = String(input);
      requests.push(url);
      const data = url.includes("/impact?")
        ? {
            items: [
              {
                kind: "artifact",
                id: url.includes("cursor=next") ? "local-two" : "local-one",
                usage: "video",
                status: "available",
              },
            ],
            other_project_uses_count: 3,
            next_cursor: url.includes("cursor=next") ? null : "next",
          }
        : { subject_id: "sub", version: 2, state: "revoked", allowed_uses: [] };
      return Promise.resolve(
        new Response(JSON.stringify(data), { headers: { "content-type": "application/json" } }),
      );
    }),
  );
  render(
    <UiProvider>
      <QueryClientProvider client={new QueryClient()}>
        <FileUseEditor projectId="p" revisionId="f" />
      </QueryClientProvider>
    </UiProvider>,
  );
  fireEvent.click(await screen.findByText("来源与使用许可"));
  const button = await screen.findByText("查看使用影响");
  expect(requests.some((url) => url.includes("/impact?"))).toBe(false);
  fireEvent.click(button);
  expect(await screen.findByText(/其它项目的关联使用：3/)).toBeInTheDocument();
  expect(await screen.findByText(/local-one/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "更多使用记录" }));
  expect(await screen.findByText(/local-two/)).toBeInTheDocument();
});
