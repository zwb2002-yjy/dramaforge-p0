/**
 * Central React Query key factory.
 *
 * Every consumer uses these helpers so query keys and invalidation prefixes
 * are defined once. Shapes are deliberately identical to the pre-factory
 * tuples — this is an organization change, not a cache-semantics change:
 * Formal confirmations still refetch, Candidate previews stay zero-write,
 * and stale operations remain fail-closed.
 */
export const queryKeys = {
  health: () => ["health"] as const,

  auth: {
    bootstrap: () => ["bootstrap-status"] as const,
    currentUser: () => ["current-user"] as const,
  },

  workspace: {
    list: () => ["workspaces"] as const,
    projects: (workspaceId: string | null) => ["workspace-projects", workspaceId] as const,
    /** Bare prefix for cross-workspace invalidation. */
    projectsRoot: () => ["workspace-projects"] as const,
    state: (projectId: string) => ["workspace-state", projectId] as const,
  },

  project: {
    detail: (projectId: string) => ["project", projectId] as const,
  },

  scene: {
    list: (projectId: string) => ["scenes", projectId] as const,
    summaries: (projectId: string) => ["scene-summaries", projectId] as const,
    workspace: (projectId: string, sceneId: string | null | undefined) =>
      ["scene-workspace", projectId, sceneId] as const,
  },

  shot: {
    list: (projectId: string) => ["shots", projectId] as const,
    workbench: (projectId: string, shotId: string | null | undefined) =>
      ["shot-workbench", projectId, shotId] as const,
    productionTrace: (projectId: string, shotId: string | null | undefined) =>
      ["shot-production-trace", projectId, shotId] as const,
    review: (projectId: string) => ["review-shots", projectId] as const,
    reviewWorkbench: (projectId: string, shotId: string | null | undefined) =>
      ["review-shot-workbench", projectId, shotId] as const,
  },

  asset: {
    /** Bare prefix; matches every filtered variant for invalidation. */
    root: (projectId: string) => ["project-assets", projectId] as const,
    list: (
      projectId: string,
      kindFilter: string,
      statusFilter: string,
      nameFilter: string,
      tagFilter: string,
    ) =>
      ["project-assets", projectId, kindFilter, statusFilter, nameFilter, tagFilter] as const,
    tags: (projectId: string) => ["asset-tags", projectId] as const,
    versions: (projectId: string, assetId: string) =>
      ["asset-versions", projectId, assetId] as const,
    card: (projectId: string, assetId: string) => ["asset-card", projectId, assetId] as const,
    mentions: (projectId: string) => ["mention-assets", projectId] as const,
    picker: (projectId: string) => ["picker-assets", projectId] as const,
    shotReferences: (projectId: string, shotId: string | null | undefined) =>
      ["shot-references", projectId, shotId] as const,
    referenceResolution: (projectId: string, shotId: string | null | undefined) =>
      ["shot-reference-resolution", projectId, shotId] as const,
  },

  production: {
    snapshot: (projectId: string) => ["snapshot", projectId] as const,
    workflowOverview: (projectId: string) => ["workflow-overview", projectId] as const,
    provenance: (projectId: string, targetId: string | null | undefined) =>
      ["creative-provenance", projectId, targetId] as const,
    opencutManifest: (projectId: string) => ["opencut-manifest", projectId] as const,
    canvasRevisions: (projectId: string, shotId: string | null | undefined) =>
      ["canvas-revisions", projectId, shotId] as const,
  },

  experiment: {
    list: (projectId: string) => ["experiments", projectId] as const,
  },

  director: {
    board: (projectId: string, shotId: string | null | undefined) =>
      ["director-board", projectId, shotId] as const,
  },

  review: {
    annotations: (projectId: string, shotId: string | null | undefined) =>
      ["review-annotations", projectId, shotId] as const,
  },

  editing: {
    session: (projectId: string, sessionId: string | null | undefined) =>
      ["edit-session", projectId, sessionId] as const,
  },

  script: {
    workspace: (projectId: string) => ["script-workspace", projectId] as const,
  },

  model: {
    catalog: () => ["models"] as const,
    slots: () => ["model-slots"] as const,
    effectiveBindings: (projectId: string) => ["model-bindings-effective", projectId] as const,
    projectProfile: (projectId: string) => ["project-model-profile", projectId] as const,
  },

  provider: {
    connections: (workspaceId: string | null) => ["provider-connections", workspaceId] as const,
    plugins: () => ["provider-plugins"] as const,
    probes: (workspaceId: string | null, connectionId: string | null | undefined) =>
      ["provider-probes", workspaceId, connectionId] as const,
    /** Bare prefix: invalidate probes for every connection of a workspace. */
    probesRoot: (workspaceId: string | null) => ["provider-probes", workspaceId] as const,
    bindings: (workspaceId: string | null, connectionId: string | null | undefined) =>
      ["provider-bindings", workspaceId, connectionId] as const,
    /** Bare prefix: invalidate bindings for every connection of a workspace. */
    bindingsRoot: (workspaceId: string | null) => ["provider-bindings", workspaceId] as const,
  },
} as const;
