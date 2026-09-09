import { ChevronLeft, Gauge } from "lucide-react";
import { useState, type ReactNode } from "react";

import "./project-shell.css";
import "./project-shell-visual.css";

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

const VIEW_LABELS: Record<ProjectWorkspaceView, string> = {
  overview: "场景总览",
  script: "剧本",
  assets: "资产",
  scenes: "场景",
  production: "制作",
  review: "制作 · 待审内容",
  edit: "剪辑",
};

export function ProjectWorkspaceShell({
  projectId,
  projectName,
  activeView,
  children,
  inspector,
  modeLabel,
}: ProjectWorkspaceShellProps) {
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const showInspector = Boolean(inspector) && activeView !== "scenes";
  const displayModeLabel = modeLabel ?? VIEW_LABELS[activeView];

  return (
    <div
      className={`qc-project-shell${activeView === "scenes" ? " scene-view" : ""}${inspectorCollapsed ? " director-collapsed" : ""}`}
      data-testid="project-workspace-shell"
      data-project-id={projectId}
    >
      <header className="qc-project-bar">
        <span className="qc-project-name">{projectName}</span>
        <span className="qc-project-save">已连接项目事实</span>
        <span className="qc-project-mode">{displayModeLabel}</span>
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
  );
}
