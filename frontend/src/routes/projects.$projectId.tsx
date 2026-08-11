import { Link, Outlet, createRoute, useRouterState } from "@tanstack/react-router";

import { ModelProfileSettings } from "../components/provider/ModelProfileSettings";
import { getSelectedWorkspaceId } from "../lib/api";
import { rootRoute } from "./__root";

export const projectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId",
  component: ProjectLayout,
});

function ProjectLayout() {
  const { projectId } = projectRoute.useParams();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const onQuick = pathname.includes("/quick");
  const onProd = pathname.includes("/production");
  const isOverview = !onQuick && !onProd;

  return (
    <div data-testid="project-panel">
      <div className="mode-banner">
        <strong>同一 Project</strong>
        <span className="muted">
          <code>{projectId.slice(0, 8)}…</code> · 快速与专业共享资产 / Graph / Run / 成本
        </span>
        <nav className="subnav" style={{ marginLeft: "auto" }}>
          <Link
            to="/projects/$projectId"
            params={{ projectId }}
            style={
              isOverview
                ? { borderColor: "var(--accent)", color: "var(--text)" }
                : undefined
            }
          >
            总览
          </Link>
          <Link
            to="/projects/$projectId/quick"
            params={{ projectId }}
            style={onQuick ? { borderColor: "var(--brand)", color: "var(--brand)" } : undefined}
          >
            快速创作
          </Link>
          <Link
            to="/projects/$projectId/production"
            params={{ projectId }}
            style={onProd ? { borderColor: "var(--brand)", color: "var(--brand)" } : undefined}
          >
            专业生产板
          </Link>
        </nav>
      </div>
      {isOverview ? (
        <section className="panel">
          <h2>项目总览</h2>
          <p className="muted">
            选择入口继续：快速模式完成 Brief→首帧竖切；专业模式导入 10 Shot 剧本、导出交付。
          </p>
          <div className="status-grid">
            <div className="status-card">
              <span className="status-label">推荐路径</span>
              <strong>快速 → 专业</strong>
            </div>
            <div className="status-card">
              <span className="status-label">画幅</span>
              <strong>9:16 竖屏</strong>
            </div>
            <div className="status-card">
              <span className="status-label">验收口径</span>
              <strong className="status-pending">§3.1 真路径</strong>
            </div>
          </div>
          <div className="toolbar">
            <Link to="/projects/$projectId/quick" params={{ projectId }}>
              <button type="button" className="primary">
                进入快速创作
              </button>
            </Link>
            <Link to="/projects/$projectId/production" params={{ projectId }}>
              <button type="button" className="accent">
                进入专业生产板
              </button>
            </Link>
          </div>
          <ModelProfileSettings projectId={projectId} workspaceId={getSelectedWorkspaceId()} />
        </section>
      ) : (
        <Outlet />
      )}
    </div>
  );
}
