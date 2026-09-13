const SELECTED_WORKSPACE_STORAGE_KEY = "dramaforge.selected-workspace-id";
const LAST_PROJECT_STORAGE_KEY = "dramaforge.last-project-id";

function readStorage(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(storage: Storage, key: string, value: string | null): void {
  try {
    if (value) storage.setItem(key, value);
    else storage.removeItem(key);
  } catch {
    // Browsers can deny persistent storage. The other storage tier may still work.
  }
}

function readNavigationPreference(key: string): string | null {
  if (typeof window === "undefined") return null;

  const sessionValue = readStorage(window.sessionStorage, key);
  if (sessionValue) return sessionValue;

  const durableValue = readStorage(window.localStorage, key);
  if (durableValue) writeStorage(window.sessionStorage, key, durableValue);
  return durableValue;
}

function writeNavigationPreference(key: string, value: string | null): void {
  if (typeof window === "undefined") return;
  writeStorage(window.sessionStorage, key, value);
  writeStorage(window.localStorage, key, value);
}

export function getSelectedWorkspaceId(): string | null {
  return readNavigationPreference(SELECTED_WORKSPACE_STORAGE_KEY);
}

export function setSelectedWorkspaceId(workspaceId: string | null): void {
  writeNavigationPreference(SELECTED_WORKSPACE_STORAGE_KEY, workspaceId);
}

export function getRememberedProjectId(): string | null {
  return readNavigationPreference(LAST_PROJECT_STORAGE_KEY);
}

export function setRememberedProjectId(projectId: string | null): void {
  writeNavigationPreference(LAST_PROJECT_STORAGE_KEY, projectId);
}
