import { useState, type ReactNode } from "react";
import {
  Aperture,
  ChevronLeft,
  Clapperboard,
  FileText,
  Film,
  FolderKanban,
  Gauge,
  Menu,
  Package,
  SearchCheck,
  Scissors,
  Settings,
} from "lucide-react";

import "./project-shell.css";

export type ProjectWorkspaceView =
  "overview" | "script" | "assets" | "scenes" | "production" | "review" | "edit";

type ProjectWorkspaceShellProps = {
  projectId: string;
  projectName: string;
  activeView: ProjectWorkspaceView;
  children: ReactNode;
  inspector?: ReactNode;
  modeLabel?: string;
};

const NAV_ITEMS: Array<{
  view: Exclude<ProjectWorkspaceView, "overview">;
  label: string;
  icon: typeof Clapperboard;
}> = [
  { view: "script", label: "剧本", icon: FileText },
  { view: "assets", label: "资产", icon: Package },
  { view: "scenes", label: "场景", icon: Film },
  { view: "production", label: "专业生产", icon: Clapperboard },
  { view: "review", label: "审片", icon: SearchCheck },
  { view: "edit", label: "剪辑", icon: Scissors },
];

export function ProjectWorkspaceShell({
  projectId,
  projectName,
  activeView,
  children,
  inspector,
  modeLabel = activeView === "production" ? "专业模式" : "项目工作区",
}: ProjectWorkspaceShellProps) {
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const projectBase = `/projects/${projectId}`;
  const showInspector = Boolean(inspector) && activeView !== "scenes";

  return (
    <div
      className={`qc-preview-shell qc-project-shell${activeView === "scenes" ? " scene-view" : ""}${sidebarExpanded ? " sidebar-expanded" : ""}${inspectorCollapsed ? " director-collapsed" : ""}`}
      data-testid="project-workspace-shell"
    >
      <aside className="qc-sidebar" aria-label="项目工作区导航">
        <div className="qc-sidebar-head">
          <div className="qc-brand">
            <Aperture size={22} aria-hidden="true" />
            <span>DramaForge</span>
          </div>
          <button
            type="button"
            className="qc-icon-button qc-sidebar-toggle"
            onClick={() => setSidebarExpanded((value) => !value)}
            aria-label={sidebarExpanded ? "收起导航" : "展开导航"}
            aria-expanded={sidebarExpanded}
          >
            {sidebarExpanded ? (
              <ChevronLeft size={19} aria-hidden="true" />
            ) : (
              <Menu size={19} aria-hidden="true" />
            )}
          </button>
        </div>
        <nav>
          <a href="/">
            <FolderKanban size={18} aria-hidden="true" />
            <span>项目大厅</span>
          </a>
          {NAV_ITEMS.map(({ view, label, icon: Icon }) => {
            const active = activeView === view;
            return (
              <a
                key={view}
                href={`${projectBase}/${view}`}
                className={active ? "active" : undefined}
                aria-current={active ? "page" : undefined}
              >
                <Icon size={18} aria-hidden="true" />
                <span>{label}</span>
              </a>
            );
          })}
        </nav>
        <div className="qc-sidebar-bottom">
          <a href={`${projectBase}#model-settings`}>
            <Settings size={18} aria-hidden="true" />
            <span>模型设置</span>
          </a>
        </div>
      </aside>

      <div className="qc-workspace">
        <header className="qc-project-bar">
          <span className="qc-project-name">{projectName}</span>
          <span className="qc-project-save">已连接项目事实</span>
          <span className="qc-project-mode">{modeLabel}</span>
          <span className="qc-avatar qc-owner-avatar" aria-label="单用户 Owner">
            创
          </span>
        </header>

        <div className={`qc-content-grid${showInspector ? "" : " no-inspector"}`}>
          <main className="qc-main-canvas qc-project-canvas">{children}</main>
          {showInspector && (
            <aside
              className={`qc-director-panel${inspectorCollapsed ? " collapsed" : ""}`}
              data-testid="project-evidence-inspector"
            >
              {inspectorCollapsed ? (
                <>
                  <button
                    type="button"
                    className="qc-icon-button"
                    onClick={() => setInspectorCollapsed(false)}
                    aria-label="展开项目证据"
                  >
                    <ChevronLeft size={19} aria-hidden="true" />
                  </button>
                  <Gauge size={19} aria-hidden="true" />
                  <span>项目证据</span>
                </>
              ) : (
                <>
                  <header className="qc-director-header">
                    <span className="qc-director-mark">
                      <Gauge size={17} aria-hidden="true" />
                    </span>
                    <span>
                      <strong>项目证据</strong>
                      <small>同一事实源</small>
                    </span>
                    <button
                      type="button"
                      className="qc-icon-button"
                      onClick={() => setInspectorCollapsed(true)}
                      aria-label="收起项目证据"
                    >
                      <ChevronLeft size={19} aria-hidden="true" />
                    </button>
                  </header>
                  <div className="qc-live-director-content">{inspector}</div>
                </>
              )}
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
