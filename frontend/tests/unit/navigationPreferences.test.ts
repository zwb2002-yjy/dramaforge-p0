import { beforeEach, describe, expect, it } from "vitest";

import {
  getRememberedProjectId,
  getSelectedWorkspaceId,
  setRememberedProjectId,
  setSelectedWorkspaceId,
} from "../../src/lib/navigationPreferences";

describe("durable navigation preferences", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  it("restores workspace and recent Project selections after tab storage is lost", () => {
    setSelectedWorkspaceId("workspace-1");
    setRememberedProjectId("project-1");

    window.sessionStorage.clear();

    expect(getSelectedWorkspaceId()).toBe("workspace-1");
    expect(getRememberedProjectId()).toBe("project-1");
    expect(window.sessionStorage.getItem("dramaforge.selected-workspace-id")).toBe("workspace-1");
    expect(window.sessionStorage.getItem("dramaforge.last-project-id")).toBe("project-1");
  });

  it("clears both storage tiers on an explicit owner/workspace reset", () => {
    setSelectedWorkspaceId("workspace-1");
    setRememberedProjectId("project-1");

    setSelectedWorkspaceId(null);
    setRememberedProjectId(null);

    expect(getSelectedWorkspaceId()).toBeNull();
    expect(getRememberedProjectId()).toBeNull();
    expect(window.localStorage.getItem("dramaforge.selected-workspace-id")).toBeNull();
    expect(window.localStorage.getItem("dramaforge.last-project-id")).toBeNull();
  });
});
