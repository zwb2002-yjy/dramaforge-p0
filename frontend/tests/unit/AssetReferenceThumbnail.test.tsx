import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssetMentionInput } from "../../src/components/assets/AssetMentionInput";
import {
  AssetReferenceThumbnail,
  FormalAssetThumbnail,
} from "../../src/components/assets/AssetReferenceThumbnail";
import { artifactContentUrl } from "../../src/lib/api";

const imageId = "11111111-1111-4111-8111-111111111111";
const laterImageId = "22222222-2222-4222-8222-222222222222";
const card = {
  asset_id: "asset-1",
  project_id: "project-1",
  kind: "character",
  status: "active",
  current_version_id: "version-1",
  current_version_status: "formal",
  references: [
    { artifact_id: laterImageId, reference_role: "front_face", sort_order: 1 },
    { artifact_id: imageId, reference_role: "profile", sort_order: 0 },
  ],
};
function json(value: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } }),
  );
}
function renderCard(value: unknown) {
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => json(value));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <FormalAssetThumbnail projectId="project-1" assetId="asset-1" label="林墨" />
    </QueryClientProvider>,
  );
  return fetch;
}
afterEach(() => vi.restoreAllMocks());

describe("canonical reference thumbnails", () => {
  it("reads the Formal card and displays the first explicit image reference without writes", async () => {
    const fetch = renderCard(card);
    const image = await screen.findByRole("img", { name: "林墨参考图" });
    expect(image).toHaveAttribute("src", artifactContentUrl("project-1", imageId));
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1]?.method ?? "GET").toBe("GET");
    fireEvent.error(image);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("林")).toBeInTheDocument();
  });

  it.each([
    { ...card, current_version_status: "candidate" },
    { ...card, project_id: "other-project" },
    { ...card, asset_id: "other-asset" },
    { ...card, status: "recycled" },
    { ...card, kind: "video", references: [{ artifact_id: imageId, reference_role: "primary" }] },
  ])("keeps an unqualified card as a visible placeholder", async (value) => {
    const fetch = renderCard(value);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("林")).toBeInTheDocument();
  });

  it("keeps a pinned/direct image on its exact Artifact and recovers after that identity changes", () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const result = render(
      <AssetReferenceThumbnail projectId="project-1" artifactId={imageId} label="@林墨" />,
    );
    fireEvent.error(screen.getByRole("img"));
    result.rerender(
      <AssetReferenceThumbnail projectId="project-1" artifactId={laterImageId} label="@林墨" />,
    );
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      artifactContentUrl("project-1", laterImageId),
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it("loads cards only for at most eight visible @ suggestions and browsing does not write", async () => {
    const calls: Array<{ url: string; method: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ url, method });
      if (url.endsWith("/assets"))
        return json(
          Array.from({ length: 12 }, (_, index) => ({
            id: `asset-${index}`,
            project_id: "project-1",
            name: `角色${index}`,
            kind: "character",
            status: "active",
          })),
        );
      if (url.endsWith("/card")) return json({ ...card, references: [] });
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf" });
      return json([]);
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function Harness() {
      const [value, setValue] = useState("");
      return (
        <AssetMentionInput
          projectId="project-1"
          shotId="shot-1"
          stage="image"
          value={value}
          onChange={setValue}
        />
      );
    }
    render(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>,
    );
    expect(calls).toEqual([]);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "@" } });
    const list = await screen.findByRole("listbox");
    await waitFor(() => expect(within(list).getAllByRole("option")).toHaveLength(8));
    await waitFor(() => expect(calls.filter((call) => call.url.endsWith("/card"))).toHaveLength(8));
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(calls.filter((call) => call.method !== "GET").map((call) => call.url)).toEqual([
      expect.stringContaining("/references/resolve"),
    ]);
    expect(calls.filter((call) => call.url.endsWith("/card"))).toHaveLength(8);
  });
});
