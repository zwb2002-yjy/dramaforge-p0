import { createRoute } from "@tanstack/react-router";

import { ResearchPanel } from "../features/research/ResearchPanel";
import { projectRoute } from "./projects.$projectId";

export const projectResearchRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/research",
  validateSearch: (
    search: Record<string, unknown>,
  ): { revision?: string; extraction?: string; fragment?: string; offset?: number } => ({
    revision: typeof search.revision === "string" ? search.revision : undefined,
    extraction: typeof search.extraction === "string" ? search.extraction : undefined,
    offset:
      typeof search.offset === "number" && Number.isSafeInteger(search.offset) && search.offset >= 0
        ? search.offset
        : undefined,
    fragment: typeof search.fragment === "string" ? search.fragment : undefined,
  }),
  component: ProjectResearchRoute,
});

function ProjectResearchRoute() {
  const { projectId } = projectResearchRoute.useParams();
  const source = projectResearchRoute.useSearch();
  return (
    <ResearchPanel
      key={JSON.stringify([projectId, source])}
      projectId={projectId}
      source={source}
    />
  );
}
