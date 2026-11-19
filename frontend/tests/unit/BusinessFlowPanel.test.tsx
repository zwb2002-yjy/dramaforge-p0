import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UiProvider } from "../../src/components/ui";
import { BusinessFlowPanel } from "../../src/features/director/BusinessFlowPanel";

const PROJECT = "11111111-1111-4111-8111-111111111111";
const RUN = "22222222-2222-4222-8222-222222222222";
const FLOW = "33333333-3333-4333-8333-333333333333";

function json(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <UiProvider>
      <QueryClientProvider client={client}>
        <BusinessFlowPanel projectId={PROJECT} runId={RUN} />
      </QueryClientProvider>
    </UiProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("BusinessFlowPanel", () => {
  it("lists flows and expands their steps without submitting", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        calls.push(url);
        if (url.endsWith("/steps")) {
          return json([
            {
              id: "44444444-4444-4444-8444-444444444444",
              instance_id: FLOW,
              step_key: "list_assets",
              revision: 1,
              status: "succeeded",
              required: true,
              dependencies: [],
              wait_reason: null,
            },
          ]);
        }
        return json([
          {
            id: FLOW,
            master_run_id: RUN,
            plan_id: "55555555-5555-4555-8555-555555555555",
            plan_revision: 1,
            definition_key: "project_asset_audit",
            definition_version: "1",
            revision: 2,
            status: "waiting",
            scope: { type: "project", entity_id: PROJECT },
            wait_reason: "flow_progress_pending",
            terminal_reason: null,
            created_at: "2026-11-19T00:00:00Z",
            finished_at: null,
          },
        ]);
      }),
    );
    renderPanel();
    const flowButton = await screen.findByRole("button", {
      name: /project_asset_audit · waiting/,
    });
    expect(flowButton).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(flowButton);
    expect(await screen.findByText(/list_assets · succeeded/)).toBeInTheDocument();
    await waitFor(() => expect(flowButton).toHaveAttribute("aria-expanded", "true"));
    expect(
      calls.some((url) => url.includes("/master-runs/") && url.endsWith("/business-flows")),
    ).toBe(true);
    expect(calls.some((url) => url.endsWith("/steps"))).toBe(true);
  });

  it("shows an empty state when the run has no flows", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => json([])),
    );
    renderPanel();
    expect(await screen.findByText("当前目标还没有业务流程。")).toBeInTheDocument();
  });
});
