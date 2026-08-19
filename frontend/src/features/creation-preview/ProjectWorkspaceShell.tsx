import { useState, type ReactNode } from "react";
import {
  Aperture,
  ChevronLeft,
  Clapperboard,
  FolderKanban,
  Gauge,
  Menu,
  Settings,
  Sparkles,
} from "lucide-react";

import { StageStepper } from "./components";
import type { PreviewStage } from "./types";
import "./quick-creation-preview.css";

type ProjectWorkspaceShellProps = {
  projectId: string;
  projectName: string;
  activeView: "overview" | "quick" | "production";
  stages: PreviewStage[];
  children: ReactNode;
  inspector?: ReactNode;
  modeLabel?: string;
};

export function ProjectWorkspaceShell({
  projectId,
  projectName,
  activeView,
  stages,
  children,
  inspector,
  modeLabel = activeView === "production" ? "专业模式" : "项目总览",
}: ProjectWorkspaceShellProps) {
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const projectBase = `/projects/${projectId}`;

  return (
    <div
      className={`qc-preview-shell qc-project-shell${sidebarExpanded ? " sidebar-expanded" : ""}${inspectorCollapsed ? " director-collapsed" : ""}`}
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
            {sidebarExpanded ? <ChevronLeft size={19} aria-hidden="true" /> : <Menu size={19} aria-hidden="true" />}
          </button>
        </div>
        <nav>
          <a href="/">
            <FolderKanban size={18} aria-hidden="true" />
            <span>项目大厅</span>
          </a>
          <a href={projectBase} className={activeView === "overview" ? "active" : undefined} aria-current={activeView === "overview" ? "page" : undefined}>
            <Gauge size={18} aria-hidden="true" />
            <span>项目总览</span>
          </a>
          <a href={`${projectBase}/quick`} className={activeView === "quick" ? "active" : undefined} aria-current={activeView === "quick" ? "page" : undefined}>
            <Sparkles size={18} aria-hidden="true" />
            <span>快速创作</span>
          </a>
          <a href={`${projectBase}/production`} className={activeView === "production" ? "active" : undefined} aria-current={activeView === "production" ? "page" : undefined}>
            <Clapperboard size={18} aria-hidden="true" />
            <span>专业生产</span>
          </a>
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
          <span className="qc-avatar qc-owner-avatar" aria-label="单用户 Owner">创</span>
        </header>

        <div className={`qc-content-grid${inspector ? "" : " no-inspector"}`}>
          <main className="qc-main-canvas qc-project-canvas">
            <StageStepper stages={stages} testId="director-stage-rail" />
            {children}
          </main>
          {inspector && (
            <aside className={`qc-director-panel${inspectorCollapsed ? " collapsed" : ""}`} data-testid="project-evidence-inspector">
              {inspectorCollapsed ? (
                <>
                  <button type="button" className="qc-icon-button" onClick={() => setInspectorCollapsed(false)} aria-label="展开项目证据">
                    <ChevronLeft size={19} aria-hidden="true" />
                  </button>
                  <Gauge size={19} aria-hidden="true" />
                  <span>项目证据</span>
                </>
              ) : (
                <>
                  <header className="qc-director-header">
                    <span className="qc-director-mark"><Gauge size={17} aria-hidden="true" /></span>
                    <span><strong>项目证据</strong><small>同一事实源</small></span>
                    <button type="button" className="qc-icon-button" onClick={() => setInspectorCollapsed(true)} aria-label="收起项目证据">
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
