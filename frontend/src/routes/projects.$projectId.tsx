import { Link, Outlet, createRoute } from "@tanstack/react-router";

import { rootRoute } from "./__root";

export const projectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId",
  component: ProjectLayout,
});

function ProjectLayout() {
  const { projectId } = projectRoute.useParams();
  return (
    <section className="panel" data-testid="project-panel">
      <header className="panel-header">
        <h1>项目 {projectId}</h1>
        <nav className="subnav">
          <Link to="/projects/$projectId/quick" params={{ projectId }}>
            快速模式
          </Link>
          <Link to="/projects/$projectId/production" params={{ projectId }}>
            专业生产
          </Link>
        </nav>
      </header>
      <Outlet />
    </section>
  );
}
