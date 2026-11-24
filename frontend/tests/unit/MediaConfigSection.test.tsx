import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UiProvider } from "../../src/components/ui";
import { MediaConfigSection } from "../../src/components/provider/MediaConfigSection";

const WORKSPACE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PROFILE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const IMAGE_BINDING = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const FINGERPRINT = "d".repeat(64);

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <UiProvider>
      <QueryClientProvider client={client}>
        <MediaConfigSection workspaceId={WORKSPACE_ID} profileId={PROFILE_ID} profileVersion={3} />
      </QueryClientProvider>
    </UiProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("MediaConfigSection", () => {
  it("saves the three media defaults with the expected profile version", async () => {
    const calls: Array<{ url: string; method: string; body: unknown }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
        calls.push({
          url,
          method: String(init?.method ?? "GET"),
          body: init?.body ? JSON.parse(String(init.body)) : null,
        });
        if (url.includes("/media-config/review")) {
          return json({
            media_config_version: 2,
            review_fingerprint: FINGERPRINT,
            conflicts: [],
          });
        }
        if (url.includes("/media-config")) {
          return json({
            media_config_version: 2,
            image_model_binding_id: null,
            video_model_binding_id: null,
            voice_model_binding_id: null,
            voice_options: {},
          });
        }
        if (url.includes("/model-bindings")) {
          return json([
            {
              id: IMAGE_BINDING,
              media_type: "image",
              purpose: "keyframe",
              model_id: "unit-image",
              enabled: true,
            },
          ]);
        }
        return json({ code: "NOT_FOUND" }, 404);
      }),
    );
    renderSection();
    const save = await screen.findByRole("button", { name: "保存媒体默认" });
    fireEvent.click(save);
    await waitFor(() => expect(save.hasAttribute("disabled")).toBe(true));
    const put = calls.find((call) => call.method === "PUT");
    expect(put?.url).toContain(`/model-profiles/${PROFILE_ID}/media-config`);
    expect(put?.body).toMatchObject({
      expected_version: 3,
      image_model_binding_id: null,
      voice_options: {},
    });
  });

  it("requires the legacy review fingerprint before reconciling", async () => {
    const calls: Array<{ url: string; method: string }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
        calls.push({ url, method: String(init?.method ?? "GET") });
        if (url.includes("/media-config/review")) {
          return json({
            media_config_version: 1,
            review_fingerprint: FINGERPRINT,
            conflicts: [{ slot: "visual.keyframe", model_id: "legacy-image" }],
          });
        }
        if (url.includes("/media-config/reconcile")) {
          return json({
            media_config_version: 2,
            image_model_binding_id: null,
            video_model_binding_id: null,
            voice_model_binding_id: null,
            voice_options: {},
          });
        }
        if (url.includes("/media-config")) {
          return json({
            media_config_version: 1,
            image_model_binding_id: null,
            video_model_binding_id: null,
            voice_model_binding_id: null,
            voice_options: {},
          });
        }
        if (url.includes("/model-bindings")) return json([]);
        return json({ code: "NOT_FOUND" }, 404);
      }),
    );
    renderSection();
    expect(await screen.findByText(/该方案仍是旧媒体配置/)).toBeTruthy();
    const reconcile = await screen.findByRole("button", {
      name: "核对并迁移旧媒体配置",
    });
    fireEvent.click(reconcile);
    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
  });
});
