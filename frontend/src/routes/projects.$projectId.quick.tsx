import { createRoute, Link } from "@tanstack/react-router";

import { projectRoute } from "./projects.$projectId";

/**
 * Historical quick-mode URL (P10-01, plan 03 §88).
 *
 * The old Quick -> Director Workflow -> Approval/Budget -> ProductionBatch
 * chain is retired.  The URL stays valid as a bookmark, is not a default
 * entry, and receives no new features; this page only explains the legacy
 * path and points to the professional surfaces.
 */
export const projectQuickRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/quick",
  component: QuickLegacyNotice,
});

function QuickLegacyNotice() {
  const { projectId } = projectQuickRoute.useParams();
  return (
    <div className="qc-page-heading" data-testid="quick-legacy">
      <p>历史入口 · Legacy</p>
      <h1>Quick 模式已退役</h1>
      <p className="muted">
        旧的 Quick 模式执行链（导演流程 → ProductionBatch → NodeRun）已由专业工作台替代，
        此页面不再开发新功能，也不会作为默认入口。
      </p>
      <div className="toolbar">
        <Link className="df-btn primary" to="/projects/$projectId/scenes" params={{ projectId }}>
          进入场景工作区
        </Link>
        <Link className="df-btn ghost" to="/projects/$projectId/production" params={{ projectId }}>
          专业生产监控
        </Link>
      </div>
    </div>
  );
}
