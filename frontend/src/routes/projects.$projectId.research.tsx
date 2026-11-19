import { createRoute } from "@tanstack/react-router";

import { ResearchPanel } from "../features/research/ResearchPanel";
import { projectRoute } from "./projects.$projectId";

export const projectResearchRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/research",
  component: ProjectResearchRoute,
});

function ProjectResearchRoute() {
  const { projectId } = projectResearchRoute.useParams();
  return <ResearchPanel projectId={projectId} />;
}
