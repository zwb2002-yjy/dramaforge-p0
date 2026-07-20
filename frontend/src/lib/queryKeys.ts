/** Central Query Key factory. */

export const queryKeys = {
  health: ["health"] as const,
  project: (projectId: string) => ["project", projectId] as const,
};
