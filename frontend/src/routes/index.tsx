import { Link, createRoute } from "@tanstack/react-router";

import { rootRoute } from "./__root";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});

function HomePage() {
  return (
    <section className="panel" data-testid="home-panel">
      <h1>DramaForge 工作台</h1>
      <p>BOOT-0 应用壳：快速模式与专业模式将共享同一个 Project。</p>
      <div className="actions">
        <Link to="/projects/$projectId" params={{ projectId: "demo" }}>
          打开演示项目
        </Link>
        <Link to="/projects/$projectId/quick" params={{ projectId: "demo" }}>
          快速模式入口
        </Link>
        <Link to="/projects/$projectId/production" params={{ projectId: "demo" }}>
          专业生产入口
        </Link>
      </div>
    </section>
  );
}
