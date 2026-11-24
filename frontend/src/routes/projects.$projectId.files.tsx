import { createRoute } from "@tanstack/react-router";

import { ProjectFilesPanel } from "../features/project-files/ProjectFilesPanel";
import { projectRoute } from "./projects.$projectId";

export const projectFilesRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/files",
  component: ProjectFilesRoute,
});

function ProjectFilesRoute() {
  const { projectId } = projectFilesRoute.useParams();
  return <ProjectFilesPanel projectId={projectId} />;
}
