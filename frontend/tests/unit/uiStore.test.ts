import { beforeEach, describe, expect, it } from "vitest";

import { useUiStore } from "../../src/stores/uiStore";

describe("uiStore", () => {
  beforeEach(() => {
    useUiStore.setState({ leftNavOpen: true, selectedShotId: null });
  });

  it("toggles left navigation", () => {
    expect(useUiStore.getState().leftNavOpen).toBe(true);
    useUiStore.getState().toggleLeftNav();
    expect(useUiStore.getState().leftNavOpen).toBe(false);
  });
});
