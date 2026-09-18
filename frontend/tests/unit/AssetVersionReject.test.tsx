import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssetCardsPanel } from "../../src/features/assets/AssetCardsPanel";
import {
  fetchAssetCard,
  fetchAssetTags,
  fetchAssetVersions,
  rejectAssetVersion,
} from "../../src/features/assets/api";

vi.mock("../../src/features/assets/api", () => ({
  createAssetCandidate: vi.fn(),
  fetchAssetCard: vi.fn(),
  fetchAssetTags: vi.fn(),
  fetchAssetVersions: vi.fn(),
  promoteAssetVersion: vi.fn(),
  rejectAssetVersion: vi.fn(),
  recycleAsset: vi.fn(),
  restoreAsset: vi.fn(),
  setAssetTags: vi.fn(),
}));

const asset = {
  id: "asset-1",
  project_id: "project-1",
  kind: "character",
  name: "林澈",
  description: "",
  status: "active",
  version: 2,
  tags: [],
  current_version_id: "version-2",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
} as never;

afterEach(() => vi.restoreAllMocks());

describe("Asset version decisions", () => {
  it("rejects a candidate version through the explicit decision endpoint", async () => {
    vi.mocked(fetchAssetTags).mockResolvedValue([]);
    vi.mocked(fetchAssetVersions).mockResolvedValue([
      {
        id: "version-2",
        asset_id: "asset-1",
        version_number: 2,
        name: "候选 B",
        status: "candidate",
        is_primary: false,
        created_at: "2026-01-01T00:00:00Z",
      },
    ] as never);
    vi.mocked(fetchAssetCard).mockResolvedValue({ missing_reference_roles: [] } as never);
    vi.mocked(rejectAssetVersion).mockResolvedValue({} as never);
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify([asset]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <AssetCardsPanel projectId="project-1" />
      </QueryClientProvider>,
    );

    await screen.findByTestId("asset-card");
    fireEvent.click(screen.getByRole("button", { name: "版本" }));
    fireEvent.click(await screen.findByTestId("asset-version-reject"));

    await waitFor(() =>
      expect(rejectAssetVersion).toHaveBeenCalledWith("project-1", "asset-1", "version-2"),
    );
  });
});
