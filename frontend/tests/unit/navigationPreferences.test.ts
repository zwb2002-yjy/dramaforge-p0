import { beforeEach, describe, expect, it } from "vitest";

import {
  getRememberedProjectId,
  getSelectedWorkspaceId,
  setRememberedProjectId,
  setSelectedWorkspaceId,
  getRememberedProjectPath,
  rememberProjectPath,
  validateSettingsReturnTo,
} from "../../src/lib/navigationPreferences";

describe("durable navigation preferences", () => {
  it("preserves internal return locations and rejects external or recursive settings destinations", () => {
    for (const path of [
      "/?create=false&panel=workspace",
      "/projects/a/edit?session=session-1",
      "/projects/a/scenes/scene-1",
    ]) {
      expect(validateSettingsReturnTo(path)).toBe(path);
    }
    for (const path of [
      "https://example.com",
      "//example.com",
      "/settings/account",
      "/projects/a/scenes/..",
      "/projects/%2e%2e/edit",
      "/projects/a\\b/edit",
      null,
    ]) {
      expect(validateSettingsReturnTo(path)).toBeUndefined();
    }
  });
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
  it("restores only a valid location belonging to the requested project", () => {
    rememberProjectPath("a", "/projects/a/scenes/scene-1");
    rememberProjectPath("b", "/projects/b/edit");
    window.sessionStorage.clear();
    expect(getRememberedProjectPath("a")).toBe("/projects/a/scenes/scene-1");
    expect(getRememberedProjectPath("b")).toBe("/projects/b/edit");
    rememberProjectPath("a", "/projects/b/production");
    expect(getRememberedProjectPath("a")).toBe("/projects/a/scenes/scene-1");
    window.sessionStorage.setItem("dramaforge.project-path:a", "/projects/a/scenes/..");
    expect(getRememberedProjectPath("a")).toBeNull();
  });
});
